import type sqlite3 from 'sqlite3';

import * as store from '../intake/store';
import type { Envelope } from '../intake/types';
import * as outbox from './outbox';

/**
 * Recognising the desk's own send coming back over the gateway.
 *
 * On a desk whose transport reflects, everything the desk puts on the wire
 * arrives at intake afterwards as an ordinary delivery: a transport identifier
 * the gateway has just generated, and the identifier the console chose for the
 * message. Every rule intake has says to record it. It has already been
 * recorded, by the dispatcher, in the transaction that put it on the wire.
 *
 * The two identifiers pull in opposite directions here and that is the whole
 * difficulty. `transport_id` is what says a delivery has been seen, and this
 * delivery has not been: the gateway made the identifier a moment ago and
 * nothing has it. `message_id` is what says a *message* has been seen, and
 * ordinarily that is not a reason to drop anything — a message can be delivered
 * twice over two handoffs and the second handoff is still a delivery, which is
 * exactly what `findEnvelopeByTransport` keying on the transport is for.
 *
 * What separates the two cases is not either identifier. It is the outbox:
 *
 *   this message is in the outbox, under a reply the desk composed  and
 *   the delivery in front of us is not that reply's own record
 *
 * then this is the desk being shown its own send, and the desk already knows.
 * A message that is not in the outbox is somebody else's however many times it
 * has been through here, and the dispatcher's own placement — whose transport
 * identifier *is* the reply's key — is not a reflection of itself.
 *
 * The desk that does not reflect never produces one of these, and needs no
 * special case: the reply is on its ticket because the dispatcher put it there,
 * and nothing else ever arrives.
 */

export interface Reflection {
  ticket_id: string | null;
}

export async function reflectionOf(
  envelope: Envelope,
  connection: sqlite3.Database,
): Promise<Reflection | null> {
  const composed = await outbox.findByMessageId(
    envelope.tenant_id,
    envelope.message_id,
    connection,
  );
  if (composed === undefined) return null;
  if (composed.reply_id === envelope.transport_id) return null;

  // The ticket to answer with is the one holding the message, because a merge
  // may have moved it since it went out. The outbox row's own ticket is the
  // fallback for the window where the reply is queued and not yet placed.
  const recorded = await store.findEnvelopeByMessageId(
    envelope.tenant_id,
    envelope.message_id,
    connection,
  );
  return { ticket_id: recorded?.ticket_id ?? composed.ticket_id };
}
