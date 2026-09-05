import type sqlite3 from 'sqlite3';

import { all, get, openConnection, run } from '../db/client';
import { byArrival } from './arrival';
import type { Envelope, EnvelopeRow, TicketRow } from './types';

/**
 * Intake's own reads and writes, and no policy at all.
 *
 * Writes go to a connection of this module's own rather than the shared one, so
 * a transaction opened here cannot be interleaved with somebody else's
 * statements on the same handle. Reads that a decision depends on are taken on
 * the same connection, inside the same transaction, so what a decision saw is
 * what it committed against.
 */

let writer: sqlite3.Database | null = null;

/**
 * The connection every write in the service goes through.
 *
 * Exported because the egress path writes here too: a reply going out is
 * recorded on its ticket and marked as gone in one transaction, and one
 * transaction means one connection.
 */
export function writeConnection(): sqlite3.Database {
  if (writer === null) writer = openConnection();
  return writer;
}

/**
 * Runs `body` inside `BEGIN IMMEDIATE` ... `COMMIT`, rolling back if it throws.
 *
 * `IMMEDIATE` takes the write lock at the start rather than on first write, so
 * the reads inside see a state nobody else can change underneath them. Callers
 * must already hold the intake lock for the tenant: two overlapping
 * transactions on one connection is an error, not a queue.
 */
export async function inTransaction<T>(
  body: (connection: sqlite3.Database) => Promise<T>,
): Promise<T> {
  const connection = writeConnection();
  await run('BEGIN IMMEDIATE', [], connection);
  try {
    const result = await body(connection);
    await run('COMMIT', [], connection);
    return result;
  } catch (error) {
    await run('ROLLBACK', [], connection).catch(() => undefined);
    throw error;
  }
}

export async function closeWriteConnection(): Promise<void> {
  const connection = writer;
  writer = null;
  if (connection === null) return;
  await new Promise<void>((resolve) => connection.close(() => resolve()));
}

/** A ticket with the relationships `ticket_thread` holds for it. */
export interface ThreadedTicket extends TicketRow {
  conversation_id: string;
  prior_ticket_id: string | null;
  merged_into_ticket_id: string | null;
  sequence: number;
}

const THREADED = `SELECT t.*, h.conversation_id, h.prior_ticket_id,
                         h.merged_into_ticket_id, h.sequence
                    FROM tickets t JOIN ticket_thread h
                      ON h.tenant_id = t.tenant_id AND h.ticket_id = t.ticket_id`;

// -- deliveries ------------------------------------------------------------

/** The stored delivery with this transport identifier, if it has been accepted. */
export function findEnvelopeByTransport(
  tenantId: string,
  transportId: string,
  connection?: sqlite3.Database,
): Promise<EnvelopeRow | undefined> {
  return get<EnvelopeRow>(
    'SELECT * FROM envelopes WHERE tenant_id = ? AND transport_id = ?',
    [tenantId, transportId],
    connection ?? writeConnection(),
  );
}

/**
 * The stored delivery carrying this message identifier.
 *
 * A message identifier can arrive on more than one transport delivery, and the
 * conversation is the same either way, so the earliest is as good an answer as
 * any and is the stable one.
 */
export async function findEnvelopeByMessageId(
  tenantId: string,
  messageId: string,
  connection?: sqlite3.Database,
): Promise<EnvelopeRow | undefined> {
  const rows = await all<EnvelopeRow>(
    `SELECT * FROM envelopes
      WHERE tenant_id = ? AND message_id = ? AND ticket_id IS NOT NULL`,
    [tenantId, messageId],
    connection ?? writeConnection(),
  );
  return rows.sort(byArrival)[0];
}

/**
 * Records a delivery against a ticket.
 *
 * The transport identifier is the primary key, so a redelivery that reaches
 * here at all is refused by the store rather than recorded twice. Callers check
 * for it first; this is the backstop for the case where two copies of one
 * delivery are in flight together.
 */
export async function insertEnvelope(
  envelope: Envelope,
  ticketId: string,
  connection: sqlite3.Database,
): Promise<boolean> {
  const result = await run(
    `INSERT OR IGNORE INTO envelopes
       (transport_id, tenant_id, ticket_id, message_id, from_address,
        to_addresses, in_reply_to, references_json, subject_token, received_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      envelope.transport_id,
      envelope.tenant_id,
      ticketId,
      envelope.message_id,
      envelope.from_address,
      JSON.stringify(envelope.to_addresses),
      envelope.in_reply_to,
      JSON.stringify(envelope.references),
      envelope.subject_token,
      envelope.received_at,
    ],
    connection,
  );
  return result.changes > 0;
}

/** Every delivery on a ticket, in the order it arrived. */
export async function listTicketEnvelopes(
  tenantId: string,
  ticketId: string,
): Promise<EnvelopeRow[]> {
  // Ordered here rather than in the query: `ORDER BY received_at` compares the
  // text and the text is not the instant. See src/intake/instant.ts.
  const rows = await all<EnvelopeRow>(
    `SELECT * FROM envelopes
      WHERE tenant_id = ? AND ticket_id = ?`,
    [tenantId, ticketId],
  );
  return rows.sort(byArrival);
}

/**
 * Hands every delivery on one ticket to another.
 *
 * Nothing about a delivery changes except which ticket holds it, so the
 * arrival order the read sorts by is untouched and a moved delivery can land
 * ahead of the one that opened the ticket it moved to.
 */
export async function moveEnvelopes(
  tenantId: string,
  fromTicketId: string,
  toTicketId: string,
  connection: sqlite3.Database,
): Promise<number> {
  const result = await run(
    'UPDATE envelopes SET ticket_id = ? WHERE tenant_id = ? AND ticket_id = ?',
    [toTicketId, tenantId, fromTicketId],
    connection,
  );
  return result.changes;
}

// -- conversations --------------------------------------------------------

/** The conversation this message identifier is already known to be in. */
export async function conversationOfIdentifier(
  tenantId: string,
  identifier: string,
  connection: sqlite3.Database,
): Promise<string | undefined> {
  const row = await get<{ conversation_id: string }>(
    'SELECT conversation_id FROM identifier_conversation WHERE tenant_id = ? AND identifier = ?',
    [tenantId, identifier],
    connection,
  );
  return row?.conversation_id;
}

/** Puts these identifiers in this conversation, leaving any already there. */
export async function mapIdentifiers(
  tenantId: string,
  identifiers: string[],
  conversationId: string,
  connection: sqlite3.Database,
): Promise<void> {
  for (const identifier of identifiers) {
    await run(
      `INSERT INTO identifier_conversation (tenant_id, identifier, conversation_id)
       VALUES (?, ?, ?)
       ON CONFLICT (tenant_id, identifier) DO UPDATE SET conversation_id = excluded.conversation_id`,
      [tenantId, identifier, conversationId],
      connection,
    );
  }
}

/**
 * Moves everything that belonged to one conversation into another.
 *
 * Both sides of the mapping move together: the identifiers, so that a later
 * delivery naming any of them lands in the survivor, and the tickets, so that
 * the survivor's history is one history. This is the whole of what a merge does
 * to conversation membership; what it does to the tickets themselves is a
 * separate decision, taken in dispatch.
 */
export async function remapConversation(
  tenantId: string,
  from: string,
  to: string,
  connection: sqlite3.Database,
): Promise<void> {
  await run(
    'UPDATE identifier_conversation SET conversation_id = ? WHERE tenant_id = ? AND conversation_id = ?',
    [to, tenantId, from],
    connection,
  );
  await run(
    'UPDATE ticket_thread SET conversation_id = ? WHERE tenant_id = ? AND conversation_id = ?',
    [to, tenantId, from],
    connection,
  );
}

// -- tickets --------------------------------------------------------------

/**
 * Every ticket of a conversation that has not been merged away, oldest first.
 *
 * A ticket that was merged into another is deliberately absent: it is a
 * historical record with no deliveries on it, and no decision is ever taken
 * against it again.
 */
export function ticketsOfConversation(
  tenantId: string,
  conversationId: string,
  connection: sqlite3.Database,
): Promise<ThreadedTicket[]> {
  return all<ThreadedTicket>(
    `${THREADED}
      WHERE t.tenant_id = ? AND h.conversation_id = ?
        AND h.merged_into_ticket_id IS NULL
      ORDER BY h.sequence ASC`,
    [tenantId, conversationId],
    connection,
  );
}

export function findTicket(
  tenantId: string,
  ticketId: string,
  connection?: sqlite3.Database,
): Promise<ThreadedTicket | undefined> {
  return get<ThreadedTicket>(
    `${THREADED} WHERE t.tenant_id = ? AND t.ticket_id = ?`,
    [tenantId, ticketId],
    connection,
  );
}

export interface NewTicket {
  ticketId: string;
  tenantId: string;
  conversationId: string;
  requesterIdentityId: string | null;
  priorTicketId: string | null;
  createdAt: string;
}

export async function insertTicket(
  ticket: NewTicket,
  connection: sqlite3.Database,
): Promise<void> {
  await run(
    `INSERT INTO tickets
       (ticket_id, tenant_id, status, requester_identity_id, created_at, closed_at)
     VALUES (?, ?, 'open', ?, ?, NULL)`,
    [ticket.ticketId, ticket.tenantId, ticket.requesterIdentityId, ticket.createdAt],
    connection,
  );
  await run(
    `INSERT INTO ticket_thread
       (tenant_id, ticket_id, conversation_id, prior_ticket_id,
        merged_into_ticket_id, sequence)
     VALUES (?, ?, ?, ?, NULL,
             (SELECT COALESCE(MAX(sequence), 0) + 1 FROM ticket_thread WHERE tenant_id = ?))`,
    [
      ticket.tenantId,
      ticket.ticketId,
      ticket.conversationId,
      ticket.priorTicketId,
      ticket.tenantId,
    ],
    connection,
  );
}

/**
 * Names the requester of a ticket that has not got one.
 *
 * The `IS NULL` in the predicate is the whole of the rule: the first delivery
 * that can settle whose case this is settles it, and every delivery after it
 * leaves it alone.
 */
export async function nameRequesterIfUnset(
  tenantId: string,
  ticketId: string,
  identityId: string,
  connection: sqlite3.Database,
): Promise<void> {
  await run(
    `UPDATE tickets SET requester_identity_id = ?
      WHERE tenant_id = ? AND ticket_id = ? AND requester_identity_id IS NULL`,
    [identityId, tenantId, ticketId],
    connection,
  );
}

/**
 * Returns a closed ticket to open.
 *
 * `closed_at` is cleared with it: the ticket is not sitting in a close any more,
 * so there is no window to measure against it. The next close stamps a fresh
 * one.
 */
export async function reopenTicket(
  tenantId: string,
  ticketId: string,
  connection: sqlite3.Database,
): Promise<void> {
  await run(
    `UPDATE tickets SET status = 'open', closed_at = NULL
      WHERE tenant_id = ? AND ticket_id = ?`,
    [tenantId, ticketId],
    connection,
  );
}

/**
 * Closes a ticket because it turned out to be part of another one, and records
 * which. Its deliveries are moved separately; this only settles its own state.
 */
export async function closeAsMerged(
  tenantId: string,
  ticketId: string,
  intoTicketId: string,
  closedAt: string,
  connection: sqlite3.Database,
): Promise<void> {
  await run(
    `UPDATE tickets SET status = 'closed', closed_at = ?
      WHERE tenant_id = ? AND ticket_id = ?`,
    [closedAt, tenantId, ticketId],
    connection,
  );
  await run(
    'UPDATE ticket_thread SET merged_into_ticket_id = ? WHERE tenant_id = ? AND ticket_id = ?',
    [intoTicketId, tenantId, ticketId],
    connection,
  );
}

// -- held deliveries ------------------------------------------------------

export interface HeldRow {
  tenant_id: string;
  transport_id: string;
  awaiting: string;
  payload: string;
  received_at: string;
}

export async function holdEnvelope(
  envelope: Envelope,
  awaiting: string,
  connection: sqlite3.Database,
): Promise<void> {
  await run(
    `INSERT OR IGNORE INTO held_deliveries
       (tenant_id, transport_id, awaiting, payload, received_at)
     VALUES (?, ?, ?, ?, ?)`,
    [
      envelope.tenant_id,
      envelope.transport_id,
      awaiting,
      JSON.stringify(envelope),
      envelope.received_at,
    ],
    connection,
  );
}

export function findHeldEnvelope(
  tenantId: string,
  transportId: string,
  connection?: sqlite3.Database,
): Promise<HeldRow | undefined> {
  return get<HeldRow>(
    'SELECT * FROM held_deliveries WHERE tenant_id = ? AND transport_id = ?',
    [tenantId, transportId],
    connection ?? writeConnection(),
  );
}

/** Held deliveries waiting on this message identifier, in arrival order. */
export async function findHeldFor(
  tenantId: string,
  messageId: string,
  connection?: sqlite3.Database,
): Promise<HeldRow[]> {
  const rows = await all<HeldRow>(
    `SELECT * FROM held_deliveries
      WHERE tenant_id = ? AND awaiting = ?`,
    [tenantId, messageId],
    connection ?? writeConnection(),
  );
  return rows.sort(byArrival);
}

export async function releaseHeld(
  tenantId: string,
  transportId: string,
  connection: sqlite3.Database,
): Promise<void> {
  await run(
    'DELETE FROM held_deliveries WHERE tenant_id = ? AND transport_id = ?',
    [tenantId, transportId],
    connection,
  );
}
