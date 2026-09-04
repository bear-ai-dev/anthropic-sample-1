/**
 * Serialisation by key.
 *
 * The store's primitives each return to the event loop before their result is
 * known, so a request that reads the ticket table and then writes to it is not
 * one step: a second request can read the same rows in between and reach the
 * same conclusion. Two first deliveries in one conversation arriving together is
 * exactly that case, and it produces two tickets for one conversation.
 *
 * Everything that reads intake state and then writes it runs inside
 * `withLock`, keyed by tenant. Waiters queue in arrival order, so the outcome
 * does not depend on how the runtime happened to interleave them.
 */
export class KeyedLock {
  /** For each key, the promise the next arrival must wait on. */
  private readonly tails = new Map<string, Promise<void>>();

  /**
   * Runs `body` with exclusive hold on `key`, and releases the hold however
   * `body` ends. The returned promise settles with `body`'s result.
   */
  async withLock<T>(key: string, body: () => Promise<T>): Promise<T> {
    const ahead = this.tails.get(key);

    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });

    // The tail is what the next arrival waits on, so it must settle even if
    // this body throws: a rejected tail would propagate to every later waiter
    // on this key and wedge the tenant.
    const tail = ahead === undefined ? held : ahead.then(() => held);
    this.tails.set(key, tail);

    if (ahead !== undefined) await ahead;
    try {
      return await body();
    } finally {
      release();
      // Only the last holder clears the key; anyone still queued behind us has
      // already replaced the tail with their own.
      if (this.tails.get(key) === tail) this.tails.delete(key);
    }
  }

  /** How many keys currently carry a queue. Diagnostics only. */
  size(): number {
    return this.tails.size;
  }
}

export const intakeLock = new KeyedLock();
