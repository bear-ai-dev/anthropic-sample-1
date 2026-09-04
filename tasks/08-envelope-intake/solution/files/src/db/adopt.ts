import { all, get, run } from './client';
import { byArrival } from '../intake/arrival';
import { conversationKey, linkedIdentifiers, resolveRoot } from '../intake/threading';
import type { Envelope } from '../intake/types';

/**
 * The conversations a store already held, brought into the tables routing uses.
 *
 * A desk that has been open for a while is handed over with rows in `tickets`
 * and `envelopes` and nothing else — those are the only two tables the shipped
 * schema has for a desk's past. Everything routing needs beyond them is in
 * `002_routing.sql`, and none of it exists for a ticket that was already there:
 * no conversation owns its message identifiers, and no `ticket_thread` row says
 * which ticket that conversation is currently on.
 *
 * Until that is repaired the history is inert, and a delivery continuing one of
 * those conversations opens a second ticket beside the one it belongs on. So
 * this runs from `migrate`, which is run over the life of a store rather than
 * once at the start of it: the second run, after the desk's rows are in place,
 * is the one that does the work.
 *
 * A historical ticket is threaded exactly as a live one would have been. Every
 * identifier its deliveries mention belongs to its conversation, and the
 * conversation is named by the root of the delivery that opened it — the same
 * derivation `src/intake/threading.ts` states, so an adopted conversation and a
 * conversation that arrived over intake are the same conversation under the
 * same name.
 *
 * Idempotent twice over: only tickets with no thread row are considered, and
 * every write is `INSERT OR IGNORE`. A conversation an identifier already
 * belongs to wins over a freshly derived name, so a ticket the store held and a
 * ticket intake opened cannot end up as two conversations that share an
 * identifier.
 */

interface HistoricTicket {
  tenant_id: string;
  ticket_id: string;
  created_at: string;
}

interface HistoricEnvelope {
  transport_id: string;
  message_id: string;
  in_reply_to: string | null;
  references_json: string;
  received_at: string;
}

function asEnvelope(tenantId: string, row: HistoricEnvelope): Envelope {
  let references: string[] = [];
  try {
    const parsed: unknown = JSON.parse(row.references_json || '[]');
    if (Array.isArray(parsed)) references = parsed.filter((item): item is string => typeof item === 'string');
  } catch {
    references = [];
  }
  return {
    transport_id: row.transport_id,
    tenant_id: tenantId,
    message_id: row.message_id,
    from_address: '',
    to_addresses: [],
    in_reply_to: row.in_reply_to,
    references,
    subject_token: null,
    received_at: row.received_at,
  };
}

export async function adoptHistory(): Promise<number> {
  // Oldest first, so the sequence numbers an adopted desk ends up with are the
  // order its tickets actually opened in. Sequence is what decides which of two
  // tickets survives a merge, so getting it backwards would make the history
  // lose to anything that arrives later.
  const orphans = await all<HistoricTicket>(
    `SELECT t.tenant_id, t.ticket_id, t.created_at
       FROM tickets t
       LEFT JOIN ticket_thread h
         ON h.tenant_id = t.tenant_id AND h.ticket_id = t.ticket_id
      WHERE h.ticket_id IS NULL
      ORDER BY t.tenant_id ASC, t.created_at ASC, t.ticket_id ASC`,
  );

  let adopted = 0;
  for (const ticket of orphans) {
    const rows = (
      await all<HistoricEnvelope>(
        `SELECT transport_id, message_id, in_reply_to, references_json, received_at
           FROM envelopes
          WHERE tenant_id = ? AND ticket_id = ?`,
        [ticket.tenant_id, ticket.ticket_id],
      )
    ).sort(byArrival);

    const identifiers: string[] = [];
    for (const row of rows) {
      for (const identifier of linkedIdentifiers(asEnvelope(ticket.tenant_id, row))) {
        if (!identifiers.includes(identifier)) identifiers.push(identifier);
      }
    }

    let conversationId: string | null = null;
    for (const identifier of identifiers) {
      const existing = await get<{ conversation_id: string }>(
        'SELECT conversation_id FROM identifier_conversation WHERE tenant_id = ? AND identifier = ?',
        [ticket.tenant_id, identifier],
      );
      if (existing) {
        conversationId = existing.conversation_id;
        break;
      }
    }
    if (conversationId === null) {
      const opener = rows[0];
      const root = opener
        ? resolveRoot(asEnvelope(ticket.tenant_id, opener)).messageId
        : ticket.ticket_id;
      conversationId = conversationKey(ticket.tenant_id, root);
    }

    for (const identifier of identifiers) {
      await run(
        `INSERT OR IGNORE INTO identifier_conversation (tenant_id, identifier, conversation_id)
         VALUES (?, ?, ?)`,
        [ticket.tenant_id, identifier, conversationId],
      );
    }
    await run(
      `INSERT OR IGNORE INTO ticket_thread
         (tenant_id, ticket_id, conversation_id, prior_ticket_id, merged_into_ticket_id, sequence)
       VALUES (?, ?, ?, NULL, NULL,
         (SELECT COALESCE(MAX(sequence), 0) + 1 FROM ticket_thread WHERE tenant_id = ?))`,
      [ticket.tenant_id, ticket.ticket_id, conversationId, ticket.tenant_id],
    );
    adopted += 1;
  }

  return adopted;
}
