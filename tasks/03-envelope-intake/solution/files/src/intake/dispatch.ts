import { reflectionOf } from '../egress/echo';
import { resolveRequester } from './alias';
import { deskAddresses, directionOf } from './direction';
import { mintTicketId } from './ids';
import { intakeLock } from './lock';
import { drainHeldFor, holdForParent, useRouter } from './pending';
import * as store from './store';
import { resolveConversation } from './threadmap';
import type { Envelope } from './types';
import { withinReopenWindow } from './window';

import type sqlite3 from 'sqlite3';
import type { ParsedEnvelope } from './parseEnvelope';
import type { ThreadedTicket } from './store';

/**
 * Routing a delivery onto a ticket.
 *
 * The decision is one of five, and it is taken against state that cannot change
 * while it is being taken: the whole of `route` runs under the tenant's intake
 * lock, and its reads and writes share one transaction on one connection.
 *
 *   duplicate  this transport delivery has already been accepted
 *   pending    it replies to something not seen yet, so it cannot be placed
 *   created    it is the first delivery of a conversation, or the first after a
 *              ticket the conversation outlived
 *   appended   it joins the conversation's open ticket
 *   reopened   it returns the conversation's closed ticket to open
 *
 * A delivery that brings two conversations together is not a sixth case. The
 * conversations are reconciled first, by `resolveConversation`, and then the
 * delivery is placed against the conversation that came out of it like any
 * other — which is why the merge has to be committed in the same transaction as
 * the placement. Half a merge is a conversation with two open tickets, and every
 * decision after it would be taken against the wrong one.
 *
 * Nor is a delivery of a message the desk itself put on the wire, which on a
 * reflecting gateway comes over intake a moment after the dispatcher sent it.
 * That is a `duplicate` of a delivery intake never saw, and it is recognised
 * from the outbox rather than from either identifier — see `src/egress/echo.ts`.
 *
 * Nor is a delivery the desk sent. Which conversation it belongs to, and which
 * ticket that conversation is on, are the same questions with the same answers
 * whoever sent it. What direction settles is narrower and it is only here:
 * `reopened`, and `created` on the back of a close, are answers to the customer
 * getting back in touch. The desk following up on its own case is not the case
 * starting again — a desk whose own answer reopened the ticket it was answering
 * could never close one — so an outbound delivery is recorded on the ticket
 * exactly as it finds it and moves nothing on. The one exception is not one: a
 * conversation with no ticket at all has no lifecycle to leave alone, and the
 * delivery has to go somewhere.
 */

export type IntakeAction = 'created' | 'appended' | 'reopened' | 'duplicate' | 'pending';

export interface IntakeOutcome {
  ticket_id: string | null;
  action: IntakeAction;
}

export async function dispatch(parsed: ParsedEnvelope): Promise<IntakeOutcome> {
  const { envelope } = parsed;
  return intakeLock.withLock(envelope.tenant_id, async () => {
    const outcome = await store.inTransaction((connection) => route(parsed, connection));
    // Anything that was waiting on this delivery can now be placed. The drain
    // runs after the commit that made this delivery visible, and inside the same
    // lock hold, so nothing else has changed the conversation in between.
    if (outcome.action !== 'duplicate' && outcome.action !== 'pending') {
      await drainHeldFor(envelope.tenant_id, envelope.message_id);
    }
    return outcome;
  });
}

/**
 * The decision itself, inside the caller's transaction.
 *
 * Exported for the pending drain, which has already taken the lock and opened a
 * transaction and must not do either again.
 */
export async function route(
  parsed: ParsedEnvelope,
  connection: sqlite3.Database,
): Promise<IntakeOutcome> {
  const { envelope } = parsed;

  // A delivery already accepted records nothing further, and answers with the
  // ticket it is on when it is asked again. That is not necessarily the ticket
  // it was first answered with: if its ticket has since been merged away, the
  // delivery moved with it, and the row says so. This is keyed on the transport
  // identifier — the message identifier is stable across deliveries and says
  // nothing about whether this handoff has been seen.
  const seen = await store.findEnvelopeByTransport(
    envelope.tenant_id,
    envelope.transport_id,
    connection,
  );
  if (seen !== undefined) {
    return { ticket_id: seen.ticket_id, action: 'duplicate' };
  }
  const held = await store.findHeldEnvelope(
    envelope.tenant_id,
    envelope.transport_id,
    connection,
  );
  if (held !== undefined) {
    return { ticket_id: null, action: 'duplicate' };
  }

  // A message of the desk's own, shown back to it by a gateway that reflects.
  // Keyed on neither identifier alone; see src/egress/echo.ts.
  const reflection = await reflectionOf(envelope, connection);
  if (reflection !== null) {
    return { ticket_id: reflection.ticket_id, action: 'duplicate' };
  }

  const resolved = await resolveConversation(parsed, connection);
  if (resolved === null) {
    // The message it replies to has not arrived. Hold it; the delivery that
    // completes the chain will release it.
    await holdForParent(parsed, connection);
    return { ticket_id: null, action: 'pending' };
  }

  // Which way the delivery was going. `desk_addresses` is reference data and
  // nothing in this transaction writes it, so this is a lookup rather than part
  // of the decision's state.
  const desk = await deskAddresses(envelope.tenant_id);
  const direction = directionOf(envelope.from_address, desk);

  const conversationId = resolved.conversationId;
  const tickets = await store.ticketsOfConversation(
    envelope.tenant_id,
    conversationId,
    connection,
  );
  const live = currentTicket(tickets);

  if (live === undefined) {
    const requester =
      direction === 'inbound'
        ? await resolveRequester(envelope.tenant_id, envelope.from_address)
        : null;
    return await open(envelope, conversationId, requester, null, connection);
  }
  if (live.status === 'open') {
    await store.insertEnvelope(envelope, live.ticket_id, connection);
    await nameRequester(envelope, live.ticket_id, direction, connection);
    return { ticket_id: live.ticket_id, action: 'appended' };
  }
  return await afterClose(envelope, conversationId, live, direction, connection);
}

/**
 * Settles whose case a ticket is, if it is not settled already.
 *
 * A ticket belongs to whoever wrote in on it. The desk's own addresses resolve
 * to an identity like anybody else's — an agent is a person the desk knows — and
 * that identity is not the requester, so an outbound delivery leaves the
 * question open. A ticket the desk opened by writing first has nobody's name on
 * it until somebody writes back.
 *
 * Once a ticket has a requester it keeps it. A colleague of the requester
 * joining the thread does not hand them the case.
 */
async function nameRequester(
  envelope: Envelope,
  ticketId: string,
  direction: 'inbound' | 'outbound',
  connection: sqlite3.Database,
): Promise<void> {
  if (direction === 'outbound') return;
  const requester = await resolveRequester(envelope.tenant_id, envelope.from_address);
  if (requester === null) return;
  await store.nameRequesterIfUnset(envelope.tenant_id, ticketId, requester, connection);
}

/**
 * The ticket a decision is taken against.
 *
 * A conversation has at most one open ticket, and while it has one that is the
 * only candidate. Once it has none, the ticket that matters is the one holding
 * the conversation's most recent close — which is the anchor the window is
 * measured from, and is not the same thing as the newest ticket: a merge can
 * hand a conversation a ticket opened later that closed earlier.
 */
function currentTicket(tickets: ThreadedTicket[]): ThreadedTicket | undefined {
  const open = tickets.find((ticket) => ticket.status === 'open');
  if (open !== undefined) return open;

  let latest: ThreadedTicket | undefined;
  for (const ticket of tickets) {
    const closedAt = ticket.closed_at ?? '';
    if (
      latest === undefined ||
      closedAt > (latest.closed_at ?? '') ||
      (closedAt === (latest.closed_at ?? '') && ticket.sequence > latest.sequence)
    ) {
      latest = ticket;
    }
  }
  return latest;
}

/** Opens a ticket for a conversation that does not have a live one. */
async function open(
  envelope: Envelope,
  conversationId: string,
  requester: string | null,
  priorTicketId: string | null,
  connection: sqlite3.Database,
): Promise<IntakeOutcome> {
  const ticketId = mintTicketId();
  await store.insertTicket(
    {
      ticketId,
      tenantId: envelope.tenant_id,
      conversationId,
      requesterIdentityId: requester,
      priorTicketId,
      createdAt: envelope.received_at,
    },
    connection,
  );
  await store.insertEnvelope(envelope, ticketId, connection);
  return { ticket_id: ticketId, action: 'created' };
}

/**
 * A delivery arriving on a conversation whose live ticket is closed.
 *
 * Inside the window of that close, the case is the same case: the ticket comes
 * back to open and keeps the identifier it has always had. Outside it, the case
 * is a new one — a new ticket with a new identifier, on the same conversation,
 * recording the ticket it continues.
 *
 * Both of those are answers to the customer getting back in touch, and neither
 * is what the desk sending a follow-up means. An outbound delivery is recorded
 * on the closed ticket and leaves it closed: the window is untouched, so the
 * next inbound delivery is measured against the same close it would have been
 * measured against had the desk said nothing.
 */
async function afterClose(
  envelope: Envelope,
  conversationId: string,
  closed: ThreadedTicket,
  direction: 'inbound' | 'outbound',
  connection: sqlite3.Database,
): Promise<IntakeOutcome> {
  if (direction === 'outbound') {
    await store.insertEnvelope(envelope, closed.ticket_id, connection);
    return { ticket_id: closed.ticket_id, action: 'appended' };
  }
  if (withinReopenWindow(closed.closed_at, envelope.received_at)) {
    await store.reopenTicket(envelope.tenant_id, closed.ticket_id, connection);
    await store.insertEnvelope(envelope, closed.ticket_id, connection);
    await nameRequester(envelope, closed.ticket_id, direction, connection);
    return { ticket_id: closed.ticket_id, action: 'reopened' };
  }
  const requester = await resolveRequester(envelope.tenant_id, envelope.from_address);
  return await open(envelope, conversationId, requester, closed.ticket_id, connection);
}

// The drain places held deliveries by taking the same decision they would have
// got had they arrived in order.
useRouter(route);
