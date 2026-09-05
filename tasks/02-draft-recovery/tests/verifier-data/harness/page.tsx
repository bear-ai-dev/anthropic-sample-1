/**
 * A page load, and what it takes to end one.
 *
 * `openPage` builds a router over the candidate's own route components and
 * renders it. `reload` is the load-bearing part of the task: it delivers the
 * browser's teardown signals, unmounts the React tree, drops every module the
 * candidate loaded, and removes anything the candidate hung off `window`. The
 * only thing that crosses a reload is the durable medium. If a candidate keeps
 * the draft anywhere else — a module singleton, component state, a global — it
 * is gone, which is the whole point.
 */
import { act, cleanup, render, type RenderResult } from "@testing-library/react";
import React from "react";
import { vi } from "vitest";
import { localMedium, PORT_GLOBAL, reseedEntropy, sessionMedium, windowBaseline } from "./env";
import { EVENTS, USERS, type UserKey } from "./fixtures";
import { installMocks, resetTransport, transport } from "./mocks";

export type Mode = "create" | "edit" | "duplicate";

export interface PageOptions {
    mode: Mode;
    user?: UserKey;
    /** Which fixture event to edit, or to duplicate from. */
    eventId?: string;
    /** Where inside the create flow to land: the form, the ticket editor, the location editor. */
    route?: "form" | "ticket" | "location";
    ticketId?: string;
    /** Query string appended to the route, e.g. "advanced=true". */
    query?: string;
    /** Leave the page mid-flight so the caller can interact before it settles. */
    settleAfterMount?: boolean;
}

export interface Page {
    result: RenderResult;
    options: PageOptions;
}

let current: Page | null = null;

/** How much virtual time a page gets after the teardown signals. */
export const TEARDOWN_GRACE_MS = 8;

/** Names present before the page was opened, so only its own are scrubbed. */
let pageBaseline = new Set<string>();

/**
 * Take away anything the page hung off `window`, so a candidate cannot use it
 * as a place for the draft to hide.
 *
 * In this environment `window` and the module global are the same object, so
 * the sweep is deliberately narrow: only names the page itself introduced, only
 * plain data, and never anything the runtime put there.
 */
function scrubWindow(): void {
    // Without a baseline there is no way to tell the page's names from the
    // runtime's, and removing the wrong one takes the whole worker with it.
    if (pageBaseline.size === 0 || windowBaseline.size === 0) return;
    for (const key of Object.getOwnPropertyNames(window)) {
        if (pageBaseline.has(key) || windowBaseline.has(key)) continue;
        const descriptor = Object.getOwnPropertyDescriptor(window, key);
        if (!descriptor?.configurable || typeof descriptor.get === "function") continue;
        const value = descriptor.value;
        if (typeof value === "function") continue;
        if (value !== null && typeof value === "object" && !isPlainData(value)) continue;
        try {
            delete (window as unknown as Record<string, unknown>)[key];
        } catch {
            /* non-configurable jsdom internals */
        }
    }
}

/** True for the kinds of value a draft could actually be stashed as. */
function isPlainData(value: object): boolean {
    if (Array.isArray(value)) return true;
    if (value instanceof Map || value instanceof Set) return true;
    const proto = Object.getPrototypeOf(value);
    return proto === Object.prototype || proto === null;
}

export function currentPage(): Page {
    if (!current) throw new Error("no page is open");
    return current;
}

/* ------------------------------------------------------------------ tabs */

export interface Tab {
    name: string;
    container: HTMLElement;
    result: RenderResult;
    options: PageOptions;
}

const tabs = new Map<string, Tab>();
let activeTab: Tab | null = null;

/** What the drive helpers query through. */
export interface QueryScope {
    querySelector<E extends Element>(selector: string): E | null;
    querySelectorAll<E extends Element>(selector: string): E[];
}

/**
 * Where the drive helpers should look for the app.
 *
 * With one page open this is the whole document, which is what it has always
 * been. With two tabs open it is the tab being driven — both trees are mounted
 * into the same document, so an unscoped query finds two of every input and
 * picks the wrong one half the time.
 *
 * The tab's own container is not quite enough. This form's modals go up through
 * `createPortal(..., document.body)`, so the questions editor and the gallery
 * are siblings of the containers rather than descendants of one. They are
 * reachable here because the scope also covers body children that are not a
 * tab, and the other tab is excluded because its container is marked.
 */
export function activeScope(): QueryScope {
    if (!activeTab) return document;
    const roots: ParentNode[] = [activeTab.container];
    for (const child of [...document.body.children]) {
        if (child !== activeTab.container && !child.hasAttribute("data-tab")) roots.push(child);
    }
    return {
        querySelector<E extends Element>(selector: string): E | null {
            for (const scope of roots) {
                const found = scope.querySelector<E>(selector);
                if (found) return found;
            }
            return null;
        },
        querySelectorAll<E extends Element>(selector: string): E[] {
            const found: E[] = [];
            for (const scope of roots) found.push(...scope.querySelectorAll<E>(selector));
            return found;
        },
    };
}

/**
 * Open another tab on the same durable medium.
 *
 * Two things make this a second *tab* rather than a second copy of the same
 * page. Its module graph is its own: `vi.resetModules()` before the imports
 * means this tree gets fresh instances of everything the candidate wrote, so a
 * module-level variable cannot carry a draft between tabs any more than it
 * could between browser windows. And its DOM is its own container, so the two
 * forms do not see each other's inputs.
 *
 * What they do share is the medium, which is the point: storage is the only
 * channel between two tabs, and it is the channel the rules are about.
 */
export async function openTab(name: string, options: PageOptions): Promise<Tab> {
    if (tabs.has(name)) throw new Error(`tab ${name} is already open`);
    // A fresh registry for the tree about to mount. Trees already mounted hold
    // their own references and are unaffected.
    vi.resetModules();
    const container = document.createElement("div");
    container.setAttribute("data-tab", name);
    document.body.appendChild(container);
    const result = await renderFlow(options, container);
    const tab: Tab = { name, container, result, options };
    tabs.set(name, tab);
    activeTab = tab;
    if (options.settleAfterMount !== false) await settle();
    return tab;
}

/**
 * Drive this tab from here on.
 *
 * The scenario runner works through a flat list of actions rather than nested
 * callbacks, so switching tabs has to be a step of its own.
 */
export function enterTab(name: string): void {
    const tab = tabs.get(name);
    if (!tab) throw new Error(`no tab ${name}`);
    activeTab = tab;
}

/** Act inside a tab. Everything the callback drives happens in that tree. */
export async function inTab<T>(name: string, body: () => Promise<T>): Promise<T> {
    const tab = tabs.get(name);
    if (!tab) throw new Error(`no tab ${name}`);
    const previous = activeTab;
    activeTab = tab;
    try {
        return await body();
    } finally {
        activeTab = previous;
    }
}

/**
 * Close one tab and leave the others alone.
 *
 * The teardown signals are dispatched on `window`, which both trees share, so
 * every live tab hears them. That is a limit of one jsdom rather than a claim
 * about browsers, and it is why no graded scenario closes one tab while
 * another is still being driven: a scenario that did would be measuring the
 * harness. Scenarios open their tabs, drive them, and end them all together.
 */
export async function endTab(name: string): Promise<void> {
    const tab = tabs.get(name);
    if (!tab) return;
    await act(async () => {
        tab.result.unmount();
    });
    tab.container.remove();
    tabs.delete(name);
    if (activeTab === tab) activeTab = null;
}

/** Close every tab, the way a browser going away does. */
export async function endAllTabs(): Promise<void> {
    if (tabs.size === 0) return;
    await act(async () => {
        Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
        window.dispatchEvent(new Event("pagehide"));
        window.dispatchEvent(new Event("beforeunload"));
        document.dispatchEvent(new Event("visibilitychange"));
    });
    await act(async () => {
        await vi.advanceTimersByTimeAsync(TEARDOWN_GRACE_MS);
    });
    for (const name of [...tabs.keys()]) await endTab(name);
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
    });
}

function pathFor(options: PageOptions): { pathname: string; search?: string; state?: unknown } {
    const { mode, route = "form", ticketId } = options;
    const suffix = route === "form" ? "" : route === "location" ? "/location" : ticketId ? `/ticket/${ticketId}` : "/ticket";
    const search = options.query ? `?${options.query}` : undefined;
    if (mode === "edit") {
        return { pathname: `/app/event/${options.eventId ?? "event-solstice"}/edit${suffix}`, search };
    }
    if (mode === "duplicate") {
        return {
            pathname: `/app/create${suffix}`,
            search,
            state: { isDuplicate: true, duplicateEvent: EVENTS[options.eventId ?? "event-solstice"] },
        };
    }
    return { pathname: `/app/create${suffix}`, search };
}

/** Marker pages for the destinations the submit handler navigates to. */
const Landed = ({ what }: { what: string }) => <div data-testid={`landed-${what}`} />;

export async function openPage(options: PageOptions): Promise<Page> {
    pageBaseline = new Set(Object.getOwnPropertyNames(window));
    const result = await renderFlow(options);
    current = { result, options };
    if (options.settleAfterMount !== false) await settle();
    return current;
}

/**
 * Mount the candidate's own route components over a memory router.
 *
 * Shared by `openPage` and `openTab`: the difference between a page and a tab
 * is what happens around the render, not the render itself.
 */
async function renderFlow(options: PageOptions, container?: HTMLElement): Promise<RenderResult> {
    installMocks();
    transport.currentUser = options.user ?? "ada";

    const [
        { createMemoryRouter, Outlet, RouterProvider },
        { NuqsAdapter },
        { SWRConfig },
        { AuthTokenProvider },
        layoutModule,
        formModule,
        ticketModule,
        locationModule,
    ] = await Promise.all([
        import("react-router-dom"),
        import("nuqs/adapters/react-router/v6"),
        import("swr"),
        import("@workspace/data/context/AuthTokenProvider"),
        import("@workspace/pages/create/CreateEventLayout"),
        import("@workspace/pages/create/create-event/CreateEventFormContent"),
        import("@workspace/pages/create/create-ticket/TicketEditorPage"),
        import("@workspace/pages/create/edit-location/LocationEditorPage"),
    ]);

    const CreateEventLayout = layoutModule.default;
    const CreateEventFormContent = formModule.default;
    const TicketEditorPage = ticketModule.default;
    const LocationEditorPage = locationModule.default;

    const flowChildren = [
        { index: true, element: <CreateEventFormContent /> },
        { path: "ticket", element: <TicketEditorPage /> },
        { path: "ticket/:ticketId", element: <TicketEditorPage /> },
        { path: "location", element: <LocationEditorPage /> },
    ];

    const routes = [
        {
            element: (
                <NuqsAdapter>
                    <Outlet />
                </NuqsAdapter>
            ),
            children: [
                { path: "/app/create/confirmation/:eventId", element: <Landed what="confirmation" /> },
                { path: "/app/create", element: <CreateEventLayout edit={false} />, children: flowChildren },
                { path: "/app/event/:eventId/edit", element: <CreateEventLayout edit={true} />, children: flowChildren },
                { path: "/app/event/:eventId", element: <Landed what="event" /> },
                { path: "/app", element: <Landed what="feed" /> },
                { path: "*", element: <Landed what="elsewhere" /> },
            ],
        },
    ];

    const entry = pathFor(options);
    const router = createMemoryRouter(routes, { initialEntries: [entry] });

    let result!: RenderResult;
    await act(async () => {
        result = render(
            <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, revalidateOnFocus: false }}>
                <AuthTokenProvider>
                    <RouterProvider router={router} />
                </AuthTokenProvider>
            </SWRConfig>,
            container ? { container } : undefined
        );
    });
    return result;
}

/**
 * End the page. Everything a real reload destroys is destroyed here.
 */
export async function endPage(): Promise<void> {
    await act(async () => {
        Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
        window.dispatchEvent(new Event("pagehide"));
        window.dispatchEvent(new Event("beforeunload"));
        document.dispatchEvent(new Event("visibilitychange"));
    });
    // A store finishes a write it has already been given even though the page
    // that gave it is going. This window is far too short for any debounce
    // worth the name: it buys an already-issued write, not a scheduled one.
    await act(async () => {
        await vi.advanceTimersByTimeAsync(TEARDOWN_GRACE_MS);
    });
    cleanup();
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
    });
    vi.resetModules();

    scrubWindow();
    // Re-install the port: the scrub above may have taken it, and a fresh view
    // over the same medium is what a fresh page would get.
    Object.defineProperty(window, PORT_GLOBAL, {
        configurable: true,
        writable: true,
        value: localMedium.port(),
    });
    document.body.innerHTML = "";
    document.head.querySelectorAll("style[data-harness-keep='false']").forEach((n) => n.remove());
    current = null;
}

/** End the current page and open a new one over the same durable medium. */
export async function reload(options: PageOptions): Promise<Page> {
    await endPage();
    return openPage(options);
}

/** Start a scenario: nothing durable, nothing recorded, entropy back to seed. */
export function startScenario(user: UserKey = "ada"): void {
    resetTransport(user);
    reseedEntropy();
}

/** Advance virtual time by exactly this much, quiescent or not. */
export async function nudge(ms: number): Promise<void> {
    await act(async () => {
        await vi.advanceTimersByTimeAsync(ms);
    });
}

function signature(): string {
    const inputs = [...document.querySelectorAll("input, textarea")]
        .map((n) => (n as HTMLInputElement).value)
        .join("\u0001");
    return JSON.stringify([
        [...localMedium.cells.entries()],
        [...sessionMedium.cells.entries()],
        document.body.textContent?.length ?? 0,
        inputs,
    ]);
}

/**
 * Advance virtual time until nothing is moving: no pending port operation, no
 * change to the durable medium or the rendered form across several rounds, and
 * no timers left. No sleeps and no wall clock anywhere.
 *
 * The ceiling matters as much as the condition. Sections of this form leave an
 * animation frame rescheduling itself for as long as the page lives, so the
 * timer count reaches zero only on the simplest pages, and every other wait
 * runs to the ceiling. Six quiet rounds is a second and a half of the app's
 * time with nothing written, nothing rendered and nothing in flight — and a
 * candidate that groups its writes over a longer window than that still has
 * the page's last writes to get out of the door when the page goes, which the
 * rules require of it anyway.
 */
export async function settle(maxRounds = 260, step = 250): Promise<void> {
    let stable = 0;
    let previous = signature();
    for (let round = 0; round < maxRounds; round++) {
        await act(async () => {
            await vi.advanceTimersByTimeAsync(step);
        });
        const now = signature();
        const quiet = now === previous && localMedium.inflight === 0 && sessionMedium.inflight === 0;
        stable = quiet ? stable + 1 : 0;
        previous = now;
        if (stable >= 3 && vi.getTimerCount() === 0) return;
        if (stable >= 6) return;
    }
}

export { USERS };
