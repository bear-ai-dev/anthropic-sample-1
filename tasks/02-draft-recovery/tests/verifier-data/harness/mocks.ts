/**
 * The network boundary. Everything above it — SWR, the endpoint helpers, the
 * hooks, the form — runs for real; only the transport and the Firebase SDK are
 * replaced. Registered with `vi.doMock` rather than `vi.mock` because the
 * workspace tree is imported dynamically after every module-registry reset.
 */
import { vi } from "vitest";
import { EVENTS, USERS, type UserKey } from "./fixtures";

export interface RequestRecord {
    url: string;
    method: string;
    data?: unknown;
    params?: unknown;
}

export interface Transport {
    requests: RequestRecord[];
    /** Everything the app tried to tell the user. */
    notices: string[];
    /** Set to make the next create/edit submission fail. */
    submitFails: boolean;
    currentUser: UserKey;
}

export const transport: Transport = { requests: [], notices: [], submitFails: false, currentUser: "ada" };

export function resetTransport(user: UserKey = "ada"): void {
    transport.requests.length = 0;
    transport.notices.length = 0;
    transport.submitFails = false;
    transport.currentUser = user;
}

let createdEventSeq = 0;

async function respond(config: Record<string, any>): Promise<any> {
    const url: string = config.url ?? "";
    const method: string = String(config.method ?? "get").toLowerCase();
    transport.requests.push({ url, method, data: config.data, params: config.params });

    if (url === "/users/" && method === "get") {
        const id = config.params?.userId;
        const user = Object.values(USERS).find((u) => u.id === id) ?? USERS[transport.currentUser];
        return { user };
    }
    if (url === "/events/" && method === "get") {
        const event = EVENTS[config.params?.eventId];
        if (!event) throw new Error(`no fixture event ${config.params?.eventId}`);
        return { event, userEventMapping: { privilege: "host", status: "going" } };
    }
    if (url === "/events/organizers") {
        return { personas: [] };
    }
    if (url === "/events/" && (method === "post" || method === "patch")) {
        if (transport.submitFails) throw new Error("submission rejected");
        const isEdit = method === "patch";
        const id = isEdit ? String(config.data?.eventId ?? "event-solstice") : `event-new-${++createdEventSeq}`;
        return { event: { ...EVENTS["event-solstice"], id, name: config.data?.name ?? "" } };
    }
    if (url === "/images/") {
        return { storageItem: { id: "uploaded", type: "eventGalleryImage", urls: { small: "u", large: "u" } } };
    }
    if (url === "/events/waiver") return { waiver: { url: "uploaded.pdf" } };
    if (url === "/search") return { results: [], users: [], organizations: [], events: [] };
    if (url === "/users/friends") return { friends: [] };
    if (url === "/organizations/") return { organizations: [] };
    if (url === "/events/guests") return { guests: [], total: 0 };
    if (url === "/events/questionnaire/answer") return {};
    if (url === "/events/invitations") return {};
    return {};
}

export function installMocks(): void {
    vi.doMock("firebase/app", () => ({ initializeApp: () => ({ name: "test" }) }));
    vi.doMock("firebase/analytics", () => ({ getAnalytics: () => ({}), setUserId: () => {} }));
    vi.doMock("firebase/auth", () => {
        const authUser = {
            uid: USERS[transport.currentUser].id,
            getIdToken: async () => "test-token",
        };
        const auth = { currentUser: authUser };
        const subscribe = (_auth: unknown, next: any) => {
            const cb = typeof next === "function" ? next : next?.next;
            if (cb) cb(authUser);
            return () => {};
        };
        return {
            getAuth: () => auth,
            onAuthStateChanged: subscribe,
            onIdTokenChanged: subscribe,
            signOut: async () => {},
        };
    });
    // react-firebase-hooks is CommonJS and pulls firebase/auth through Node's
    // own resolver, so the mock above never reaches it.
    vi.doMock("react-firebase-hooks/auth", () => ({
        useAuthState: () => [
            { uid: USERS[transport.currentUser].id, getIdToken: async () => "test-token" },
            false,
            undefined,
        ],
    }));
    // The flyer picker reaches straight past the app's transport to a stock
    // image service. Answer with nothing rather than refusing: a rejection
    // here surfaces as an unhandled error and has nothing to do with drafts.
    vi.doMock("axios", async () => {
        const actual = await vi.importActual<Record<string, any>>("axios");
        const empty = async () => ({ data: { results: [], total: 0, total_pages: 0 } });
        const wrapped = new Proxy(actual.default, {
            apply: empty,
            get(target, prop, receiver) {
                if (prop === "get" || prop === "post" || prop === "put" || prop === "patch" || prop === "delete") {
                    return empty;
                }
                return Reflect.get(target, prop, receiver);
            },
        });
        return { ...actual, default: wrapped };
    });
    // Toasts are the app's way of saying it refused to do something. Recording
    // them turns a silent early return into something the harness can report.
    vi.doMock("react-hot-toast", () => {
        const record = (kind: string) => (message: unknown) => {
            transport.notices.push(`${kind}: ${String(message)}`);
            return "toast-id";
        };
        const toast: any = record("info");
        toast.error = record("error");
        toast.success = record("success");
        toast.loading = record("loading");
        toast.dismiss = () => {};
        toast.custom = record("custom");
        toast.promise = async (promise: Promise<unknown>) => promise;
        return { default: toast, toast, Toaster: () => null, useToaster: () => ({ toasts: [] }) };
    });
    // Picks a colour out of the flyer by loading it into an <img> and waiting
    // for it to decode, which never happens here: submitting would hang.
    vi.doMock("fast-average-color", () => ({
        FastAverageColor: class {
            async getColorAsync() {
                return { hex: "#2f6f4f", rgb: "rgb(47,111,79)", isDark: true, value: [47, 111, 79, 255] };
            }
            destroy() {}
        },
    }));
    vi.doMock("@giphy/js-fetch-api", () => ({
        GiphyFetch: class {
            async trending() {
                return { data: [], pagination: { total_count: 0, count: 0, offset: 0 } };
            }
            async search() {
                return { data: [], pagination: { total_count: 0, count: 0, offset: 0 } };
            }
        },
    }));
    vi.doMock("@data/sendRequest", () => {
        const sendRequest: any = (config: Record<string, any>) => respond(config);
        sendRequest.defaults = { baseURL: "http://api.invalid" };
        sendRequest.interceptors = {
            request: { use: () => {} },
            response: { use: () => {} },
        };
        return {
            sendRequest,
            isBackendError: (e: unknown) =>
                !!e && typeof e === "object" && typeof (e as Record<string, unknown>).display === "string",
        };
    });
}
