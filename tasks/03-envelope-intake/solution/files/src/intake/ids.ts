import { randomUUID } from 'node:crypto';

/**
 * Ticket identifiers.
 *
 * Minted here and nowhere else. A ticket keeps the identifier it was minted
 * with for as long as it exists: closing it does not change it and reopening it
 * does not change it. A conversation that outlives a ticket gets a new ticket
 * with a new identifier, which records the one it continues.
 */
export function mintTicketId(): string {
  return randomUUID();
}
