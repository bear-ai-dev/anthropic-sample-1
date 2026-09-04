// Node >= 22 exposes a built-in `localStorage` global that shadows jsdom's and
// throws on getItem/setItem unless --localstorage-file is given. Any app code
// that touches Web Storage dies on module load or first call. Install a working
// in-memory implementation when the ambient one is unusable.
function installWebStorage(name: "localStorage" | "sessionStorage") {
    const existing = (globalThis as Record<string, unknown>)[name] as { getItem?: unknown } | undefined;
    if (existing && typeof existing.getItem === "function") return;

    const store = new Map<string, string>();
    const shim = {
        get length() {
            return store.size;
        },
        key: (i: number) => [...store.keys()][i] ?? null,
        getItem: (k: string) => (store.has(String(k)) ? store.get(String(k))! : null),
        setItem: (k: string, v: string) => void store.set(String(k), String(v)),
        removeItem: (k: string) => void store.delete(String(k)),
        clear: () => store.clear(),
    };

    Object.defineProperty(globalThis, name, { value: shim, configurable: true, writable: true });
    if (typeof window !== "undefined") {
        Object.defineProperty(window, name, { value: shim, configurable: true, writable: true });
    }
}

installWebStorage("localStorage");
installWebStorage("sessionStorage");

// jsdom implements neither, and framer-motion / embla reach for both.
if (typeof window !== "undefined") {
    if (!window.matchMedia) {
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
    if (!(globalThis as Record<string, unknown>).ResizeObserver) {
        (globalThis as Record<string, unknown>).ResizeObserver = class {
            observe() {}
            unobserve() {}
            disconnect() {}
        };
    }
    if (!(globalThis as Record<string, unknown>).IntersectionObserver) {
        (globalThis as Record<string, unknown>).IntersectionObserver = class {
            observe() {}
            unobserve() {}
            disconnect() {}
            takeRecords() {
                return [];
            }
        };
    }
}
