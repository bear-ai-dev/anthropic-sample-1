/**
 * Runs once per worker, before any workspace module is imported.
 *
 * Node 22 installs its own `localStorage` global that shadows the one jsdom
 * provides and throws from `getItem` unless the process was started with
 * `--localstorage-file`. Any module that touches Web Storage at load time then
 * dies with an error that points nowhere near the cause, so the shim goes in
 * first and is applied whenever the ambient object has no callable `getItem`.
 */
import { afterEach, beforeEach, vi } from "vitest";
import { fillRandom, localMedium, objectUrls, PORT_GLOBAL, resetMediums, sessionMedium, windowBaseline } from "./env";
// Imported here, once, on purpose. A dynamic import after a module-registry
// reset would hand back a fresh copy of the harness with none of its state.
import { endAllTabs, endPage } from "./page";

function hasWorkingStorage(candidate: unknown): boolean {
    if (!candidate || typeof candidate !== "object") return false;
    const getItem = (candidate as { getItem?: unknown }).getItem;
    if (typeof getItem !== "function") return false;
    try {
        (candidate as Storage).getItem("__probe__");
        return true;
    } catch {
        return false;
    }
}

function installStorage(name: "localStorage" | "sessionStorage", value: Storage): void {
    const ambient = (globalThis as Record<string, unknown>)[name];
    if (hasWorkingStorage(ambient)) {
        // jsdom's own implementation works; still replace it so the harness owns
        // the medium and can carry it across a simulated reload.
    }
    Object.defineProperty(globalThis, name, {
        configurable: true,
        writable: true,
        value,
    });
    if (typeof window !== "undefined" && (window as unknown) !== (globalThis as unknown)) {
        Object.defineProperty(window, name, { configurable: true, writable: true, value });
    }
}

installStorage("localStorage", localMedium.webStorage());
installStorage("sessionStorage", sessionMedium.webStorage());

// framer-motion, embla and the responsive hooks reach for these at module load.
if (typeof window.matchMedia !== "function") {
    Object.defineProperty(window, "matchMedia", {
        configurable: true,
        writable: true,
        value: (query: string) => ({
            matches: false,
            media: query,
            onchange: null,
            addListener: () => {},
            removeListener: () => {},
            addEventListener: () => {},
            removeEventListener: () => {},
            dispatchEvent: () => false,
        }),
    });
}

class StubObserver {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
    takeRecords(): unknown[] {
        return [];
    }
}
for (const name of ["ResizeObserver", "IntersectionObserver"] as const) {
    if (typeof (globalThis as Record<string, unknown>)[name] !== "function") {
        Object.defineProperty(globalThis, name, { configurable: true, writable: true, value: StubObserver });
        Object.defineProperty(window, name, { configurable: true, writable: true, value: StubObserver });
    }
}

// jsdom implements neither of these, and the flyer and gallery previews use both.
let objectUrlSeq = 0;
Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    writable: true,
    value: (blob: unknown) => {
        const url = `blob:http://localhost/object-${++objectUrlSeq}`;
        objectUrls.set(url, blob);
        return url;
    },
});
Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    writable: true,
    value: (url: string) => {
        objectUrls.delete(url);
    },
});

// lottie-web probes a 2d context at module load and dereferences the result.
Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
    configurable: true,
    writable: true,
    value: () =>
        new Proxy(
            {},
            {
                get: (target: Record<string, unknown>, prop: string) => {
                    if (prop in target) return target[prop];
                    if (prop === "canvas") return undefined;
                    if (prop === "measureText") return () => ({ width: 0 });
                    if (prop === "getImageData") return () => ({ data: new Uint8ClampedArray(4) });
                    if (prop === "createImageData") return () => ({ data: new Uint8ClampedArray(4) });
                    return () => undefined;
                },
                set: (target: Record<string, unknown>, prop: string, value: unknown) => {
                    target[prop] = value;
                    return true;
                },
            }
        ),
});

Object.defineProperty(window, "scrollTo", { configurable: true, writable: true, value: () => {} });
Object.defineProperty(Element.prototype, "scrollIntoView", {
    configurable: true,
    writable: true,
    value: () => {},
});

// The router builds a `Request` when it navigates after a submission, and
// Node's own refuses the abort signal jsdom hands it. Nothing reads the result.
Object.defineProperty(globalThis, "Request", {
    configurable: true,
    writable: true,
    value: class HarnessRequest {
        readonly url: string;
        readonly method: string;
        constructor(url: string, init?: { method?: string }) {
            this.url = String(url);
            this.method = init?.method ?? "GET";
        }
    },
});

// Nothing may reach the network. Theme.tsx fetches a lottie file on mount.
Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    writable: true,
    value: async () => {
        throw new Error("network disabled in the grading environment");
    },
});

// Determinism: the create form picks a random default flyer at module load and
// several components mint uuids. Both must be reproducible across a reload.
Math.random = () => 0.42;
Object.defineProperty(globalThis.crypto, "getRandomValues", {
    configurable: true,
    writable: true,
    value: <T extends ArrayBufferView>(array: T): T => {
        fillRandom(new Uint8Array(array.buffer, array.byteOffset, array.byteLength));
        return array;
    },
});

Object.defineProperty(window, PORT_GLOBAL, {
    configurable: true,
    writable: true,
    value: localMedium.port(),
});

for (const key of Object.getOwnPropertyNames(window)) windowBaseline.add(key);

/**
 * Every scenario runs on virtual time from the same instant. Nothing in the
 * grader sleeps or reads a wall clock: time only moves when the harness moves
 * it, inside `act`, which is what makes a debounce and two competing writes
 * reproducible.
 */
const FIXED_NOW = Date.UTC(2031, 4, 17, 9, 30, 0);

vi.useFakeTimers({
    now: FIXED_NOW,
    toFake: [
        "setTimeout",
        "clearTimeout",
        "setInterval",
        "clearInterval",
        "setImmediate",
        "clearImmediate",
        "Date",
        "performance",
    ],
});

beforeEach(() => {
    vi.clearAllTimers();
    vi.setSystemTime(FIXED_NOW);
    resetMediums();
});

// `globals: false` turns off Testing Library's automatic cleanup, so a tree
// left mounted by one test is still in the document during the next one and
// every probe reads the wrong render. Tabs go first: a scenario that opened
// them may have ended without closing them, and one left mounted would be
// found by the next test's queries.
afterEach(async () => {
    await endAllTabs();
    await endPage();
    vi.clearAllTimers();
});
