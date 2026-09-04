import { intakeLock } from '../intake/lock';
import { parseEnvelope } from '../intake/parseEnvelope';
import { drainHeldFor } from '../intake/pending';
import { route } from '../intake/dispatch';
import * as store from '../intake/store';
import { handOff } from './handoff';
import * as outbox from './outbox';
import type { Reply } from './types';

import type sqlite3 from 'sqlite3';

/**
 * Getting what the desk is holding onto the wire, exactly once.
 *
 * Nothing here can be exactly-once on its own. The handoff is a call to
 * something outside this process and its answer can be lost, so the only two
 * choices are to risk sending twice or to risk not sending at all — and the
 * transport settles which by keying the wire on `message_id` and answering
 * `already_sent`. That turns *sending again* into a safe operation, and once
 * sending again is safe the right side to fail on is obvious: a reply stays
 * queued until the transport has said something, and a reply the transport has
 * said nothing about is offered again.
 *
 * So the order is: hand off first, record afterwards. The three states it can
 * leave behind are all recoverable.
 *
 *   the handoff was refused          nothing is on the wire and nothing ever
 *                                    will be, so the reply is refused and the
 *                                    ticket is left alone.
 *   the handoff landed and we
 *   crashed before recording it      the reply is still queued, the next tick
 *                                    offers it again, and the transport says
 *                                    `already_sent`, which is `sent` as far as
 *                                    anything downstream of here is concerned.
 *   the handoff did not say          identical to the above, and deliberately
 *                                    so. `unknown` is not a failure and it is
 *                                    not a success; it is a reply whose state
 *                                    is still queued, which is where it
 *                                    already is.
 *
 * The other way round — mark it sent, then hand it off — has a fourth state
 * that is not recoverable: a reply nothing will ever offer to the transport,
 * recorded on its ticket as an answer the customer never got.
 *
 * The recording is not an insert. A reply going out is a delivery on the
 * conversation like any other and it goes through the same routing decision:
 * that is what puts its identifier in the conversation, so that the customer's
 * answer to it — which names it and nothing else — has somewhere to land. It is
 * also what places it on the ticket the conversation is *now* on rather than the
 * one the console had in front of it, which may since have been merged away.
 */

export interface TickReport {
  sent: number;
  refused: number;
  unsettled: number;
}

export async function dispatchTick(tenantId?: string): Promise<TickReport> {
  const tenants =
    tenantId === undefined
      ? (await outbox.tenantsWithQueued()).map((row) => row.tenant_id)
      : [tenantId];

  const report: TickReport = { sent: 0, refused: 0, unsettled: 0 };
  for (const tenant of tenants) {
    await drainTenant(tenant, report);
  }
  return report;
}

async function drainTenant(tenantId: string, report: TickReport): Promise<void> {
  // The queue is read once. A reply composed while this tick is running is the
  // next tick's, which is what makes the tick finite however busy the desk is.
  const queued = await outbox.listQueued(tenantId);

  for (const row of queued) {
    const reply = outbox.rowToReply(row);

    // The whole of one reply happens under the tenant's intake lock, so the
    // handoff, the placement and the mark cannot interleave with a delivery ---
    // including the gateway handing this very message back, which is the
    // interleaving that matters and the reason the lock is taken out here
    // rather than around the transaction alone.
    const outcome = await intakeLock.withLock(tenantId, async () => {
      // Re-read inside the lock: a tick that overlaps another one must not
      // offer the same reply twice on the strength of a stale queue read.
      const current = await outbox.findReply(tenantId, reply.reply_id);
      if (current === undefined || current.state !== 'queued') return 'settled';

      const result = await handOff(reply);

      if (result.outcome === 'unknown') {
        // Left where it is, on purpose. See the header.
        return 'unsettled';
      }

      if (result.outcome === 'refused') {
        await store.inTransaction((connection) =>
          outbox.markRefused(
            tenantId,
            reply.reply_id,
            result.reason ?? 'refused by transport',
            connection,
          ),
        );
        return 'refused';
      }

      await store.inTransaction(async (connection) => {
        await place(reply, connection);
        await outbox.markSent(tenantId, reply.reply_id, connection);
      });
      // Anything held waiting on this message can be placed now that it is
      // committed. Outside the transaction and inside the lock, exactly as the
      // inbound path does it.
      await drainHeldFor(tenantId, reply.message_id);
      return 'sent';
    });

    if (outcome === 'sent') report.sent += 1;
    else if (outcome === 'refused') report.refused += 1;
    else if (outcome === 'unsettled') report.unsettled += 1;
  }
}

/**
 * Puts an outgoing message through the routing decision as a delivery.
 *
 * Its transport identifier is the reply's own key. The gateway did not deliver
 * it, so there is no identifier from the gateway to use, and the console's key
 * is the one thing that is unique per message the desk sends — which also means
 * a second attempt at the same reply routes to the same identifier and is
 * refused by the store as the redelivery it is.
 */
async function place(reply: Reply, connection: sqlite3.Database): Promise<void> {
  const parsed = parseEnvelope({
    transport_id: reply.reply_id,
    tenant_id: reply.tenant_id,
    message_id: reply.message_id,
    from_address: reply.from_address,
    to_addresses: reply.to_addresses,
    in_reply_to: reply.in_reply_to,
    references: reply.references,
    subject_token: null,
    received_at: reply.composed_at,
  });
  if (!parsed.ok) {
    throw new Error(`a stored reply no longer validates: ${parsed.errors.join('; ')}`);
  }
  await route(parsed.parsed, connection);
}
