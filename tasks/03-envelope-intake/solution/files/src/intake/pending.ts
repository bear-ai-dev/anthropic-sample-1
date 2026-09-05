import type sqlite3 from 'sqlite3';

import { parseEnvelope, type ParsedEnvelope } from './parseEnvelope';
import * as store from './store';
import type { Envelope } from './types';

/**
 * Deliveries that cannot be placed yet.
 *
 * A reply with no reference chain names its parent and nothing else, so until
 * the parent is stored there is no conversation to put it in. Rejecting it would
 * lose it: the gateway has handed it over and will not hand it over again. It is
 * held instead, and released by the delivery it was waiting for.
 *
 * Release is recursive. A held reply can itself be the parent of another held
 * reply, so placing one delivery can make a chain of them placeable, and the
 * drain keeps going until nothing more comes free.
 */

/** Circular import with dispatch: the drain routes, and routing can hold. */
type Router = (parsed: ParsedEnvelope, connection: sqlite3.Database) => Promise<unknown>;

let router: Router | null = null;

/**
 * Wires the drain to the routing decision. Called once at startup; kept out of
 * a direct import so the two modules do not have to be loaded in a fixed order.
 */
export function useRouter(fn: Router): void {
  router = fn;
}

export async function holdForParent(
  parsed: ParsedEnvelope,
  connection: sqlite3.Database,
): Promise<void> {
  if (parsed.root.kind !== 'parent') {
    throw new Error('only a delivery waiting on a parent can be held');
  }
  await store.holdEnvelope(parsed.envelope, parsed.root.messageId, connection);
}

/**
 * Places everything that was waiting on `messageId`, and everything that
 * becomes placeable as a result.
 *
 * Each release is its own transaction: a delivery that fails to place must not
 * take the delivery that unblocked it down with it, and the one that unblocked
 * it is already committed. The caller holds the tenant's intake lock throughout,
 * so no other request is interleaving with any of this.
 */
export async function drainHeldFor(tenantId: string, messageId: string): Promise<number> {
  if (router === null) throw new Error('pending drain has no router');

  let placed = 0;
  const frontier: string[] = [messageId];
  const visited = new Set<string>();

  while (frontier.length > 0) {
    const awaiting = frontier.shift() as string;
    if (visited.has(awaiting)) continue;
    visited.add(awaiting);

    const waiting = await store.findHeldFor(tenantId, awaiting);
    for (const row of waiting) {
      const envelope = revive(row.payload);
      if (envelope === null) {
        // Unreadable payload: drop the row rather than spin on it forever.
        await store.inTransaction((connection) =>
          store.releaseHeld(tenantId, row.transport_id, connection),
        );
        continue;
      }
      const parsed = parseEnvelope(envelope);
      if (!parsed.ok) {
        await store.inTransaction((connection) =>
          store.releaseHeld(tenantId, row.transport_id, connection),
        );
        continue;
      }

      // The row goes before the routing, in the same transaction, so a
      // delivery that places successfully is never also still waiting.
      await store.inTransaction(async (connection) => {
        await store.releaseHeld(tenantId, row.transport_id, connection);
        await (router as Router)(parsed.parsed, connection);
      });
      placed += 1;
      frontier.push(envelope.message_id);
    }
  }

  return placed;
}

function revive(payload: string): Envelope | null {
  try {
    return JSON.parse(payload) as Envelope;
  } catch {
    return null;
  }
}
