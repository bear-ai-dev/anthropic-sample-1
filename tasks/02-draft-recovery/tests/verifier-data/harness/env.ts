/**
 * Process-wide harness state. Imported statically by both the setup file and
 * the specs, so there is exactly one instance for the lifetime of the worker.
 */
import { DurableMedium } from "./page-storage";

/** Backs `localStorage` and the injected asynchronous draft port. */
export const localMedium = new DurableMedium();
/** Backs `sessionStorage`. Also survives a reload, as it does in a browser. */
export const sessionMedium = new DurableMedium();

/** Own properties of `window` observed before the first page load. */
export const windowBaseline = new Set<string>();

export const PORT_GLOBAL = "__ExampleCo_DRAFT_STORAGE__";

/** Object URLs handed out by the shim, so the harness can tell them apart. */
export const objectUrls = new Map<string, unknown>();

/**
 * Deterministic entropy. Several components mint uuids and the create form
 * picks a random default flyer at module load; both have to be reproducible
 * across a reload for the comparison against the model to mean anything.
 */
const SEED = 0x9e3779b9;
let entropy = SEED;

export function reseedEntropy(): void {
    entropy = SEED;
}

export function fillRandom(view: Uint8Array): void {
    for (let i = 0; i < view.length; i++) {
        entropy ^= entropy << 13;
        entropy ^= entropy >>> 17;
        entropy ^= entropy << 5;
        view[i] = entropy & 0xff;
    }
}

export function resetMediums(): void {
    for (const medium of [localMedium, sessionMedium]) {
        medium.cells.clear();
        medium.ops.length = 0;
        medium.inflight = 0;
        medium.planDelays(null);
        medium.planFaults(null);
    }
    objectUrls.clear();
}

/** Everything durable, from both mediums, as one flat record. */
export function durableSnapshot(): Record<string, string> {
    return { ...sessionMedium.snapshot(), ...localMedium.snapshot() };
}
