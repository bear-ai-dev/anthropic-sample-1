import type sqlite3 from 'sqlite3';

import { all, get, run } from '../db/client';
import * as store from '../intake/store';
import type { Reply } from './types';

/**
 * The outbox's reads and writes, and no policy at all.
 *
 * The mirror of `src/intake/store.ts` for the other direction, and on the same
 * write connection, because the two directions have to commit together: the
 * transaction that marks a reply sent is the transaction that records it on its
 * ticket.
 */

export type OutboxState = 'queued' | 'sent' | 'refused';

export interface OutboxRow {
  tenant_id: string;
  reply_id: string;
  ticket_id: string;
  message_id: string;
  from_address: string;
  to_addresses: string;
  in_reply_to: string | null;
  references_json: string;
  composed_at: string;
  state: OutboxState;
  reason: string | null;
}

export function rowToReply(row: OutboxRow): Reply {
  if (row.in_reply_to === null) {
    // The column is nullable because the rows the migration brings over from
    // history predate the requirement, and those arrive already sent, so
    // nothing that dispatches ever reads one.
    throw new Error(`outbox row ${row.reply_id} has no parent message`);
  }
  return {
    reply_id: row.reply_id,
    tenant_id: row.tenant_id,
    ticket_id: row.ticket_id,
    message_id: row.message_id,
    from_address: row.from_address,
    to_addresses: JSON.parse(row.to_addresses) as string[],
    in_reply_to: row.in_reply_to,
    references: JSON.parse(row.references_json) as string[],
    composed_at: row.composed_at,
  };
}

/**
 * Records a composed reply, or leaves an existing one exactly as it is.
 *
 * `INSERT OR IGNORE` is the whole of the idempotence. The console retries with
 * the same key, and a retry must not put a reply that has already gone out back
 * into the queue: the row that is there wins, whatever state it has reached, and
 * the caller reads it back afterwards to answer with where the reply actually
 * is.
 */
export async function enqueue(reply: Reply, connection: sqlite3.Database): Promise<void> {
  await run(
    `INSERT OR IGNORE INTO outbox
       (tenant_id, reply_id, ticket_id, message_id, from_address, to_addresses,
        in_reply_to, references_json, composed_at, state, reason)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', NULL)`,
    [
      reply.tenant_id,
      reply.reply_id,
      reply.ticket_id,
      reply.message_id,
      reply.from_address,
      JSON.stringify(reply.to_addresses),
      reply.in_reply_to,
      JSON.stringify(reply.references),
      reply.composed_at,
    ],
    connection,
  );
}

export function findReply(
  tenantId: string,
  replyId: string,
  connection?: sqlite3.Database,
): Promise<OutboxRow | undefined> {
  return get<OutboxRow>(
    'SELECT * FROM outbox WHERE tenant_id = ? AND reply_id = ?',
    [tenantId, replyId],
    connection ?? store.writeConnection(),
  );
}

/**
 * Whether this desk has a message of its own under this identifier.
 *
 * Asked by intake of every delivery that reaches the placement, which is why it
 * is one indexed lookup. It is asked of the outbox and not of `desk_addresses`:
 * a delivery from one of the desk's addresses is the desk speaking, which is a
 * different fact from this message being one the desk has itself put on the
 * wire and already accounted for.
 */
export function findByMessageId(
  tenantId: string,
  messageId: string,
  connection?: sqlite3.Database,
): Promise<OutboxRow | undefined> {
  return get<OutboxRow>(
    `SELECT * FROM outbox
      WHERE tenant_id = ? AND message_id = ?
      ORDER BY composed_at ASC, reply_id ASC
      LIMIT 1`,
    [tenantId, messageId],
    connection ?? store.writeConnection(),
  );
}

/** Everything the desk is still holding, in the order the agents wrote it. */
export function listQueued(
  tenantId: string,
  connection?: sqlite3.Database,
): Promise<OutboxRow[]> {
  return all<OutboxRow>(
    `SELECT * FROM outbox
      WHERE tenant_id = ? AND state = 'queued'
      ORDER BY composed_at ASC, reply_id ASC`,
    [tenantId],
    connection ?? store.writeConnection(),
  );
}

export function listOutbox(
  tenantId: string,
  state: OutboxState | null,
): Promise<OutboxRow[]> {
  const clause = state === null ? '' : ' AND state = ?';
  const parameters = state === null ? [tenantId] : [tenantId, state];
  return all<OutboxRow>(
    `SELECT * FROM outbox
      WHERE tenant_id = ?${clause}
      ORDER BY composed_at ASC, reply_id ASC`,
    parameters,
  );
}

/** Every desk with something queued, so a tick with no tenant can find them. */
export function tenantsWithQueued(): Promise<{ tenant_id: string }[]> {
  return all<{ tenant_id: string }>(
    "SELECT DISTINCT tenant_id FROM outbox WHERE state = 'queued' ORDER BY tenant_id",
    [],
    store.writeConnection(),
  );
}

/**
 * Marks a reply as being on the wire.
 *
 * The `state = 'queued'` in the predicate keeps a second dispatcher from
 * re-marking a reply another one has already settled, and keeps a mark from
 * moving a refusal back.
 */
export async function markSent(
  tenantId: string,
  replyId: string,
  connection: sqlite3.Database,
): Promise<void> {
  await run(
    `UPDATE outbox SET state = 'sent', reason = NULL
      WHERE tenant_id = ? AND reply_id = ? AND state = 'queued'`,
    [tenantId, replyId],
    connection,
  );
}

export async function markRefused(
  tenantId: string,
  replyId: string,
  reason: string,
  connection: sqlite3.Database,
): Promise<void> {
  await run(
    `UPDATE outbox SET state = 'refused', reason = ?
      WHERE tenant_id = ? AND reply_id = ? AND state = 'queued'`,
    [reason, tenantId, replyId],
    connection,
  );
}
