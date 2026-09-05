import * as store from './store';
import { conversationKey } from './threading';
import type { ParsedEnvelope } from './parseEnvelope';
import type { ThreadedTicket } from './store';

import type sqlite3 from 'sqlite3';

/**
 * Which conversation a delivery belongs to, once every assertion is accounted
 * for.
 *
 * `src/intake/threading.ts` says what a delivery asserts: the identifiers it
 * names are one conversation. It stops there, and everything awkward is on this
 * side of the line. A delivery can name identifiers that already sit in two
 * different conversations, and when it does, those conversations were one all
 * along and the store has been wrong about them since before this delivery
 * existed. Putting that right is a write, not a read.
 *
 * The order matters and is the reason this is not a lookup:
 *
 *   1. Find the conversation each named identifier is currently in.
 *   2. If they agree, or only one of them is known, there is nothing to
 *      reconcile and this is an ordinary placement.
 *   3. If they do not agree, choose which conversation survives, move the other
 *      conversations' identifiers and tickets into it, and only then reconcile
 *      the tickets themselves.
 *   4. Record every identifier this delivery named against the survivor, so the
 *      next delivery that names any of them lands in one lookup.
 *
 * Step 3 is the only place in the service that decides which of two histories is
 * the one that continues.
 */

export interface Resolution {
  conversationId: string;
  /** Tickets folded into another by this delivery, absorbed first. */
  merged: { absorbed: string; into: string }[];
}

/**
 * Resolves and, where necessary, repairs the conversation for a delivery.
 *
 * Returns null when the delivery names only a parent that has not arrived: its
 * conversation is that parent's conversation and there is not yet one to name.
 * The caller holds it.
 */
export async function resolveConversation(
  parsed: ParsedEnvelope,
  connection: sqlite3.Database,
): Promise<Resolution | null> {
  const { envelope } = parsed;
  const tenantId = envelope.tenant_id;

  const stated = await statedConversation(parsed, connection);
  if (stated === null) return null;

  const candidates = [stated];
  for (const identifier of parsed.linked) {
    const existing = await store.conversationOfIdentifier(tenantId, identifier, connection);
    if (existing !== undefined && !candidates.includes(existing)) candidates.push(existing);
  }

  let conversationId = stated;
  const merged: { absorbed: string; into: string }[] = [];

  if (candidates.length > 1) {
    const ranked = await rank(tenantId, candidates, connection);
    conversationId = ranked[0];
    for (const absorbed of ranked.slice(1)) {
      await store.remapConversation(tenantId, absorbed, conversationId, connection);
    }
    merged.push(
      ...(await reconcileTickets(tenantId, conversationId, envelope.received_at, connection)),
    );
  }

  await store.mapIdentifiers(tenantId, parsed.linked, conversationId, connection);
  return { conversationId, merged };
}

/**
 * The conversation the delivery's own headers point at.
 *
 * A stated root gives it outright. A delivery that names only a parent does not:
 * its conversation is whatever the parent's is, so a delivery carrying that
 * message identifier has to have arrived and been placed. Until one has, this is
 * null and the delivery waits.
 */
async function statedConversation(
  parsed: ParsedEnvelope,
  connection: sqlite3.Database,
): Promise<string | null> {
  if (parsed.statedRootKey !== null) return parsed.statedRootKey;

  const tenantId = parsed.envelope.tenant_id;
  const parentId = parsed.root.messageId;
  const parent = await store.findEnvelopeByMessageId(tenantId, parentId, connection);
  if (parent === undefined) return null;
  const known = await store.conversationOfIdentifier(tenantId, parent.message_id, connection);
  return known ?? conversationKey(tenantId, parent.message_id);
}

/**
 * Orders conversations by which of them opened first.
 *
 * A conversation opened when its first ticket did. `sequence` settles ties and
 * puts a conversation that has no tickets yet — one this delivery is the first
 * to mention — last, since it has not opened at all.
 */
async function rank(
  tenantId: string,
  candidates: string[],
  connection: sqlite3.Database,
): Promise<string[]> {
  const keyed: { conversationId: string; sort: [number, string, number] }[] = [];
  for (const conversationId of candidates) {
    const tickets = await store.ticketsOfConversation(tenantId, conversationId, connection);
    const first = tickets[0];
    keyed.push({
      conversationId,
      sort: first === undefined ? [1, '', 0] : [0, first.created_at, first.sequence],
    });
  }
  keyed.sort((left, right) => compare(left.sort, right.sort));
  return keyed.map((entry) => entry.conversationId);
}

/**
 * Leaves the merged conversation with at most one open ticket.
 *
 * Each side of a merge could have had one, and a conversation has one at most,
 * so all but the earliest are folded into it: their deliveries move across, they
 * close at the instant of the delivery that brought them together, and each
 * records the ticket it was merged into. Tickets that were already closed are
 * left exactly as they are — they are history, and this conversation's history is
 * now longer than it looked.
 */
async function reconcileTickets(
  tenantId: string,
  conversationId: string,
  closedAt: string,
  connection: sqlite3.Database,
): Promise<{ absorbed: string; into: string }[]> {
  const tickets = await store.ticketsOfConversation(tenantId, conversationId, connection);
  const open = tickets.filter((ticket) => ticket.status === 'open');
  if (open.length < 2) return [];

  open.sort((left, right) => compare(opened(left), opened(right)));
  const survivor = open[0];

  const merged: { absorbed: string; into: string }[] = [];
  for (const ticket of open.slice(1)) {
    await store.moveEnvelopes(tenantId, ticket.ticket_id, survivor.ticket_id, connection);
    await store.closeAsMerged(
      tenantId,
      ticket.ticket_id,
      survivor.ticket_id,
      closedAt,
      connection,
    );
    merged.push({ absorbed: ticket.ticket_id, into: survivor.ticket_id });
  }
  return merged;
}

function opened(ticket: ThreadedTicket): [number, string, number] {
  return [0, ticket.created_at, ticket.sequence];
}

function compare(left: [number, string, number], right: [number, string, number]): number {
  if (left[0] !== right[0]) return left[0] - right[0];
  if (left[1] !== right[1]) return left[1] < right[1] ? -1 : 1;
  return left[2] - right[2];
}
