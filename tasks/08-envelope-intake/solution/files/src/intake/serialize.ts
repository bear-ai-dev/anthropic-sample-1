import * as store from './store';
import type { ThreadedTicket } from './store';
import type { EnvelopeRow } from './types';

/**
 * The wire shapes for a ticket read, per docs/openapi.json.
 *
 * Deliveries come back in the order they arrived — ascending `received_at`,
 * with the transport identifier settling a tie so the list is stable rather
 * than merely sorted.
 */

export interface TicketEnvelopeView {
  transport_id: string;
  message_id: string;
  from_address: string;
  received_at: string;
}

export interface TicketView {
  ticket_id: string;
  tenant_id: string;
  conversation_id: string;
  status: string;
  requester_identity_id: string | null;
  prior_ticket_id: string | null;
  merged_into_ticket_id: string | null;
  created_at: string;
  closed_at: string | null;
  envelopes: TicketEnvelopeView[];
}

export function envelopeView(row: EnvelopeRow): TicketEnvelopeView {
  return {
    transport_id: row.transport_id,
    message_id: row.message_id,
    from_address: row.from_address,
    received_at: row.received_at,
  };
}

export async function ticketView(ticket: ThreadedTicket): Promise<TicketView> {
  const envelopes = await store.listTicketEnvelopes(ticket.tenant_id, ticket.ticket_id);
  return {
    ticket_id: ticket.ticket_id,
    tenant_id: ticket.tenant_id,
    conversation_id: ticket.conversation_id,
    status: ticket.status,
    requester_identity_id: ticket.requester_identity_id ?? null,
    prior_ticket_id: ticket.prior_ticket_id ?? null,
    merged_into_ticket_id: ticket.merged_into_ticket_id ?? null,
    created_at: ticket.created_at,
    closed_at: ticket.closed_at ?? null,
    envelopes: envelopes.map(envelopeView),
  };
}
