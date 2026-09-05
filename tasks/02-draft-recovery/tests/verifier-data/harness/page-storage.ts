/**
 * The substrate that stands in for browser storage.
 *
 * One `Map` is the durable medium. It outlives every simulated reload; nothing
 * else does. Two views sit on top of it:
 *
 *   - a synchronous Web Storage shim, installed as `localStorage` /
 *     `sessionStorage`, because Node 22 ships a built-in `localStorage` global
 *     that shadows jsdom's and throws on `getItem`;
 *   - an asynchronous key/value port, installed as
 *     `window.__ExampleCo_DRAFT_STORAGE__`, which the workspace's draft storage
 *     module picks up in preference to the Web Storage backend.
 *
 * The asynchronous port settles on virtual time, so the harness decides the
 * order in which concurrent writes land instead of hoping for one.
 */

export interface DraftStoragePort {
    read(key: string): Promise<string | null>;
    write(key: string, value: string): Promise<void>;
    remove(key: string): Promise<void>;
    keys(): Promise<string[]>;
}

export interface PortOp {
    kind: "read" | "write" | "remove" | "keys";
    key: string;
    seq: number;
    issuedAt: number;
    settledAt?: number;
    failed?: boolean;
}

export type OpDescriptor = { kind: PortOp["kind"]; key: string; seq: number };
export type DelayPlan = (op: OpDescriptor) => number;
/** Return a message to make the operation reject instead of settling. */
export type FaultPlan = (op: OpDescriptor) => string | null;

const DEFAULT_DELAY = 1;

export class DurableMedium {
    /** The only state that survives a reload. */
    readonly cells = new Map<string, string>();
    /** Every port operation, in issue order, across the whole scenario. */
    readonly ops: PortOp[] = [];
    /** Number of port operations issued but not yet settled. */
    inflight = 0;

    private opSeq = 0;
    private delayPlan: DelayPlan = () => DEFAULT_DELAY;
    private faultPlan: FaultPlan = () => null;

    snapshot(): Record<string, string> {
        return Object.fromEntries(this.cells);
    }

    /** Install a per-operation virtual delay, used to force out-of-order completion. */
    planDelays(plan: DelayPlan | null): void {
        this.delayPlan = plan ?? (() => DEFAULT_DELAY);
    }

    /** Make chosen operations fail, the way a full or disabled store does. */
    planFaults(plan: FaultPlan | null): void {
        this.faultPlan = plan ?? (() => null);
    }

    portTouched(): boolean {
        return this.ops.length > 0;
    }

    private schedule<T>(kind: PortOp["kind"], key: string, effect: () => T): Promise<T> {
        const seq = ++this.opSeq;
        const record: PortOp = { kind, key, seq, issuedAt: Date.now() };
        this.ops.push(record);
        this.inflight += 1;
        const descriptor: OpDescriptor = { kind, key, seq };
        const delay = Math.max(0, this.delayPlan(descriptor));
        const fault = this.faultPlan(descriptor);
        return new Promise<T>((resolve, reject) => {
            setTimeout(() => {
                record.settledAt = Date.now();
                this.inflight -= 1;
                if (fault !== null) {
                    record.failed = true;
                    reject(new Error(fault));
                    return;
                }
                resolve(effect());
            }, delay);
        });
    }

    /** The asynchronous port handed to the workspace. */
    port(): DraftStoragePort {
        return {
            // A read answers with what was there when it was asked, the way a
            // request already in flight does. A write that lands while it is
            // outstanding does not change the answer it is going to give.
            read: (key) => {
                const answer = this.cells.get(key) ?? null;
                return this.schedule("read", key, () => answer);
            },
            write: (key, value) =>
                this.schedule("write", key, () => {
                    this.cells.set(key, value);
                }),
            remove: (key) =>
                this.schedule("remove", key, () => {
                    this.cells.delete(key);
                }),
            keys: () => this.schedule("keys", "*", () => [...this.cells.keys()]),
        };
    }

    /**
     * The synchronous Web Storage view over the same medium.
     *
     * A candidate that writes through `localStorage` rather than the injected
     * port is writing to the same place, and is observed the same way: the
     * operations are recorded and the fault plan applies here too.
     */
    webStorage(): Storage {
        const cells = this.cells;
        const note = (kind: PortOp["kind"], key: string) => {
            const seq = ++this.opSeq;
            const at = Date.now();
            const record: PortOp = { kind, key, seq, issuedAt: at, settledAt: at };
            this.ops.push(record);
            const fault = this.faultPlan({ kind, key, seq });
            if (fault !== null) {
                record.failed = true;
                throw new Error(fault);
            }
        };
        const api = {
            get length() {
                return cells.size;
            },
            key(index: number) {
                return [...cells.keys()][index] ?? null;
            },
            getItem(key: string) {
                note("read", String(key));
                return cells.has(String(key)) ? (cells.get(String(key)) as string) : null;
            },
            setItem(key: string, value: string) {
                note("write", String(key));
                cells.set(String(key), String(value));
            },
            removeItem(key: string) {
                note("remove", String(key));
                cells.delete(String(key));
            },
            clear() {
                note("remove", "*");
                cells.clear();
            },
        };
        return api as unknown as Storage;
    }
}
