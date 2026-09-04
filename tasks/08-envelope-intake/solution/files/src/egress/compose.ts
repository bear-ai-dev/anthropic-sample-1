import { intakeLock } from '../intake/lock';
import * as store from '../intake/store';
import * as outbox from './outbox';
import type { Reply } from './types';

/**
 * Taking a reply the console has composed.
 *
 * The call returns when the reply is durable, not when it is on the wire. The
 * console cannot be kept waiting on a transport, and it does not need to be: it
 * has an identifier for the reply and it can ask where the reply got to. What
 * this must not do is send, and it must not put the reply on the ticket either
 * — nothing has gone out, and a ticket holds the deliveries that happened.
 *
 * The retry is the whole of the rest. The console reissues the same `reply_id`
 * on anything it did not get an answer to, including the answer it lost after
 * this succeeded, and by then a dispatcher may well have sent the reply. So the
 * second call must not re-queue it, must not send it again, and must not claim
 * it is queued: it answers with the state the reply is actually in.
 */

export type ComposeResult =
  | { ok: true; entry: outbox.OutboxRow }
  | { ok: false; status: 404 };

export async function compose(reply: Reply): Promise<ComposeResult> {
  return intakeLock.withLock(reply.tenant_id, async () => {
    const entry = await store.inTransaction(async (connection) => {
      const ticket = await store.findTicket(reply.tenant_id, reply.ticket_id, connection);
      if (ticket === undefined) return null;
      await outbox.enqueue(reply, connection);
      // Read back rather than return what was written: on a retry the row that
      // is there is the one that counts, and it may have moved on since.
      return await outbox.findReply(reply.tenant_id, reply.reply_id, connection);
    });
    if (entry === null || entry === undefined) return { ok: false as const, status: 404 as const };
    return { ok: true as const, entry };
  });
}
