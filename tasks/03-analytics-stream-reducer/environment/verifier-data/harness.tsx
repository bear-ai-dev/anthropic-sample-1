// Verifier harness. Drives the candidate's real component tree through the real
// SSE transport seam and reads panels out of the DOM.
//
// Two rules govern everything here:
//   1. No sleeps and no wall clock. Time only moves because we move it.
//   2. Never resolve the candidate's entry point by name. Controls are found by
//      calling them and watching what happens to the transport and the DOM.

import { act, render } from "@testing-library/react";
import React from "react";
import { expect, vi } from "vitest";
import { EVENT_UNRELATED, QUERY_TYPES, type PanelName, type QueryType, type Scenario } from "./scenarios";
import type { PanelView } from "./model";

// --- transport double ---------------------------------------------------

export interface Connection {
    index: number;
    url: string;
    init: any;
    aborted: boolean;
    /** Set when the candidate's onerror threw, i.e. it gave up on this stream. */
    abandoned: boolean;
    /** Whether the harness has already handed this connection its open event. */
    opened: boolean;
    /**
     * Settles the promise `fetchEventSource` returned. The library rejects it
     * when a callback throws, and candidates rely on that to notice that a read
     * is over, so the double has to do the same.
     */
    finish: { resolve: () => void; reject: (error: unknown) => void };
}

export const connections: Connection[] = [];

export function mockFetchEventSource(url: string, init: any): Promise<void> {
    const conn: Connection = {
        index: connections.length,
        url,
        init,
        aborted: false,
        abandoned: false,
        opened: false,
        finish: { resolve: () => {}, reject: () => {} },
    };
    // The real function settles only when the stream ends.
    const promise = new Promise<void>((resolve, reject) => {
        conn.finish = { resolve, reject };
    });
    connections.push(conn);
    try {
        init?.signal?.addEventListener?.("abort", () => {
            conn.aborted = true;
        });
    } catch {
        /* a candidate may pass no signal */
    }
    // Keep an unhandled rejection from a candidate that ignores the promise out
    // of the report; the candidate's own handler, if it has one, still runs.
    promise.catch(() => {});
    return promise;
}

/**
 * The connection the candidate most recently opened. Deliberately indifferent to
 * whether its signal has been aborted: after a stop, this is the connection a
 * late frame would arrive on, and dropping it is the candidate's job, not ours.
 */
export function currentConnection(): Connection | undefined {
    for (let i = connections.length - 1; i >= 0; i--) {
        if (!connections[i].abandoned) return connections[i];
    }
    return undefined;
}

/** A connection that has since been replaced by a newer one. */
export function supersededConnection(): Connection | undefined {
    const current = currentConnection();
    for (let i = connections.length - 1; i >= 0; i--) {
        if (connections[i] !== current && !connections[i].abandoned) return connections[i];
    }
    return undefined;
}

/** The connection that is genuinely still readable. */
export function liveConnection(): Connection | undefined {
    for (let i = connections.length - 1; i >= 0; i--) {
        if (!connections[i].aborted && !connections[i].abandoned) return connections[i];
    }
    return undefined;
}

// --- ambient state the module mocks read --------------------------------

export const ambient: { token: string | undefined } = { token: "verifier-token" };

export const EVENT_FIXTURES: Record<string, Record<string, unknown>> = {};

export function registerEvent(id: string) {
    EVENT_FIXTURES[id] = {
        id,
        name: `Event ${id.slice(0, 8)}`,
        numAttendees: 214,
        dateCreated: 1735689600,
        dateEnd: 4102444800,
        description: "",
        visibility: { showToPublic: true, showToFriends: true, showToCampus: null },
    };
}

export function mockUseAuthToken() {
    return {
        authToken: ambient.token,
        authTokenLoading: false,
        authTokenError: undefined,
        uid: ambient.token ? "verifier-uid" : undefined,
        refreshAuthToken: async () => {},
    };
}

export function mockUseEvent(eventId?: string) {
    return {
        event: eventId ? EVENT_FIXTURES[eventId] : undefined,
        loading: false,
        error: undefined,
        refetch: () => {},
    };
}

// --- the browser's own storage ------------------------------------------

/**
 * Wipe every key and put back exactly what this scenario says the browser was
 * holding. Called between scenarios as well as before them: records the previous
 * scenario's candidate wrote would otherwise stand its next dashboard up.
 */
export function resetStorage(entries: { key: string; value: string }[] = []): void {
    try {
        window.localStorage.clear();
    } catch {
        /* an implementation that cannot be cleared cannot be seeded either */
    }
    for (const entry of entries) {
        try {
            window.localStorage.setItem(entry.key, entry.value);
        } catch {
            /* nothing further to try */
        }
    }
}

// --- the analytics query double -----------------------------------------

export interface QueryCall {
    url: string;
    /** Every parameter value the request carried, whatever the parameter names. */
    values: string[];
}

export const queryCalls: QueryCall[] = [];

/**
 * What the query answers with, and for which event. Set per scenario. A request
 * naming any other event is answered the way the backend answers for an event
 * the caller has no analytics for.
 */
export const queryAmbient: { eventId: string; answers: Partial<Record<QueryType, { eligible: boolean; data: unknown }>> } =
    { eventId: "", answers: {} };

export function setQueryScenario(scenario: Scenario, eventId: string) {
    queryAmbient.eventId = eventId;
    queryAmbient.answers = { ...(scenario.query ?? {}) };
    queryCalls.length = 0;
}

function paramValues(config: any): string[] {
    const out: string[] = [];
    const params = config?.params;
    if (params && typeof params === "object") {
        for (const value of Object.values(params)) {
            if (value === null || value === undefined) continue;
            out.push(String(value));
        }
    }
    const query = String(config?.url ?? "").split("?")[1] ?? "";
    for (const value of new URLSearchParams(query).values()) out.push(value);
    return out;
}

/**
 * Stand in for the app's axios instance, which is where the network is. The
 * interceptor on the real one unwraps the envelope before any caller sees it, so
 * this resolves the payload directly, exactly as callers in the tree expect.
 *
 * Graded on values, never on parameter names: a request is for a section if it
 * carries that section's name as the value of any parameter, and it is for this
 * event if it carries this event's id the same way.
 */
export async function mockSendRequest(config: any): Promise<unknown> {
    const url = String(config?.url ?? "");
    const values = paramValues(config);
    queryCalls.push({ url, values });

    const wanted = QUERY_TYPES.find((type) => values.includes(type));
    if (wanted === undefined) {
        // Some other endpoint entirely. Nothing in the graded tree needs one.
        return undefined;
    }

    const forThisEvent = values.includes(queryAmbient.eventId);
    const answer = forThisEvent ? queryAmbient.answers[wanted] : undefined;
    const eligible = answer?.eligible ?? true;
    // A document comes back whether or not the event is entitled to one, and
    // that is the whole difficulty of the case: the figures are populated and
    // they are not this event's. Every field of the answer says so and says it
    // the same way the workspace capture does — `analytics.id` names the event
    // the aggregator last computed for, and the three flags are all false — so
    // a client that reads any one of them reaches the same place. Nothing here
    // requires the exact field the reference happens to check.
    const data = answer ? answer.data : null;

    return {
        analytics: {
            id: eligible ? queryAmbient.eventId : EVENT_UNRELATED,
            dateUpdated: eligible ? 1772000000 : 1764126000,
            ...(data === null || data === undefined ? {} : { [wanted]: data }),
        },
        eligible,
        ready: eligible,
        updated: eligible,
    };
}

export function mockIsBackendError(error: unknown): boolean {
    return typeof error === "object" && error !== null && typeof (error as any).display === "string";
}

// The real export is an axios instance, so a caller may reach for its verb
// helpers instead of calling it. Both routes land here.
(mockSendRequest as any).get = (url: string, config: any) => mockSendRequest({ ...config, url });
(mockSendRequest as any).post = (url: string, data: any, config: any) => mockSendRequest({ ...config, url, data });
(mockSendRequest as any).interceptors = {
    request: { use: () => 0, eject: () => {} },
    response: { use: () => 0, eject: () => {} },
};
(mockSendRequest as any).defaults = { headers: { common: {} } };

// --- deterministic quiescence -------------------------------------------

function domSignature(): string {
    return `${connections.length}|${document.body.textContent ?? ""}`;
}

/**
 * Move virtual time forward and flush React until neither the transport nor the
 * DOM changes and no timers remain. Never touches the real clock.
 */
export async function settle(opts: { rounds?: number; stepMs?: number } = {}): Promise<void> {
    const rounds = opts.rounds ?? 24;
    const stepMs = opts.stepMs ?? 250;
    let previous = "";
    for (let i = 0; i < rounds; i++) {
        previous = domSignature();
        await act(async () => {
            await vi.advanceTimersByTimeAsync(stepMs);
        });
        if (vi.getTimerCount() === 0 && domSignature() === previous) return;
    }
}

export async function deliver(conn: Connection | undefined, frame: { body?: unknown; raw?: string }) {
    if (!conn) return;
    const data = frame.raw !== undefined ? frame.raw : JSON.stringify(frame.body);
    let thrown: unknown;
    let threw = false;
    await act(async () => {
        try {
            conn.init?.onmessage?.({ data, id: "", event: "", retry: undefined });
        } catch (error) {
            // An exception out of onmessage propagates through the library's read
            // loop and ends the stream, so model that: this connection is done.
            threw = true;
            thrown = error;
        }
    });
    if (threw) {
        conn.abandoned = true;
        await act(async () => {
            conn.finish.reject(thrown);
            await Promise.resolve();
        });
    }
    await settle();
}

function okResponse() {
    return {
        ok: true,
        status: 200,
        statusText: "OK",
        headers: new Headers({ "content-type": "text/event-stream" }),
    } as unknown as Response;
}

/**
 * Move virtual time forward until the candidate opens another connection, or
 * until there is nothing left scheduled. Bounded, and driven entirely by the
 * fake clock: a candidate that backs off is waited for, a candidate that has
 * stopped trying is not waited on at all.
 */
async function advanceUntilReconnect(limitMs = 30000, stepMs = 250): Promise<boolean> {
    const before = connections.length;
    for (let waited = 0; waited < limitMs; waited += stepMs) {
        await act(async () => {
            await vi.advanceTimersByTimeAsync(stepMs);
        });
        if (connections.length > before) return true;
        if (vi.getTimerCount() === 0) return false;
    }
    return connections.length > before;
}

export interface FailureOutcome {
    /** The read is still going: either a new connection or a retried one. */
    reopened: boolean;
    /** Nothing is reading any more. */
    dead: boolean;
}

/**
 * Break the transport under the candidate and see what it does about it.
 *
 * Two shapes are accepted, because both are legitimate: the candidate can ask
 * `fetch-event-source` to retry by returning a delay from onerror, or it can
 * take the reconnect over itself and open a new connection. Either way the
 * harness only moves virtual time.
 *
 * With `open: false` the replacement connection is left un-opened, which is what
 * a backend that is still down looks like — that is the path to exhaustion.
 */
export async function failTransport(opts: { open?: boolean } = {}): Promise<FailureOutcome> {
    const open = opts.open ?? true;
    const conn = liveConnection();
    if (!conn) return { reopened: false, dead: true };

    const before = connections.length;
    let delay: unknown;
    let thrown: unknown;
    let threw = false;
    await act(async () => {
        try {
            delay = conn.init?.onerror?.(new Error("stream interrupted"));
        } catch (error) {
            threw = true;
            thrown = error;
        }
    });
    if (threw) {
        // Throwing out of onerror is how a client tells the library to stop
        // retrying, and the library answers by rejecting the call it is inside.
        conn.abandoned = true;
        await act(async () => {
            conn.finish.reject(thrown);
            await Promise.resolve();
        });
    }
    await settle();

    let reopened = connections.length > before;

    if (!reopened && threw) {
        // It stopped the library's retry loop. If it means to carry on, it will
        // open a connection of its own; if not, nothing is scheduled and this
        // returns immediately.
        reopened = await advanceUntilReconnect();
    }

    if (!reopened && !threw) {
        // The library owns the retry: the same invocation waits and tries again.
        const waitMs = typeof delay === "number" && delay >= 0 ? delay : 1000;
        await act(async () => {
            await vi.advanceTimersByTimeAsync(waitMs);
        });
        if (connections.length > before) {
            reopened = true;
        } else {
            if (open) {
                await act(async () => {
                    try {
                        await conn.init?.onopen?.(okResponse());
                    } catch {
                        conn.abandoned = true;
                    }
                });
                await settle();
            }
            return { reopened: true, dead: false };
        }
    }

    if (reopened && open) await openPending();
    await settle();
    return { reopened, dead: !reopened && liveConnection() === undefined };
}

/**
 * Keep the transport broken until the candidate stops trying. Bounded so a
 * candidate that retries forever fails an assertion instead of hanging; the
 * bound is far above any plausible ceiling, so the ceiling itself is not graded.
 */
export async function exhaustTransport(maxRounds = 12): Promise<{ rounds: number; dead: boolean }> {
    for (let round = 1; round <= maxRounds; round++) {
        const outcome = await failTransport({ open: false });
        if (outcome.dead || !outcome.reopened) return { rounds: round, dead: true };
    }
    return { rounds: maxRounds, dead: liveConnection() === undefined };
}

/**
 * The resume point this URL asks the backend to continue after, or null when it
 * asks for nothing. The parameter's name is the endpoint's, not a candidate's
 * choice: `AnalyticsStreamRequest` names it and the recorded session shows it.
 * An empty value counts as absent — that is a request that carries no revision,
 * which is what is being asked about here.
 */
export function resumeAsked(url: string): string | null {
    const query = url.split("?")[1] ?? "";
    const found = new URLSearchParams(query).get("since");
    return found === null || found === "" ? null : found;
}

/**
 * The most recent request to the analytics query that was about this section, or
 * undefined when it was never asked. Recognised by value, like every other read
 * of a request here: a call is about a section if it carries the section's name
 * as the value of any parameter.
 */
export function lastQueryCallFor(section: string): QueryCall | undefined {
    for (let i = queryCalls.length - 1; i >= 0; i--) {
        if (queryCalls[i].values.includes(section)) return queryCalls[i];
    }
    return undefined;
}

/** Whether any query parameter of this URL carries exactly this value. */
export function urlCarries(url: string, value: string): boolean {
    const query = url.split("?")[1] ?? "";
    for (const found of new URLSearchParams(query).values()) {
        if (found === value) return true;
    }
    return false;
}

/** Hand the open event to any connection that has not received one yet. */
export async function openPending(): Promise<void> {
    for (const conn of connections) {
        if (conn.opened || conn.aborted || conn.abandoned) continue;
        conn.opened = true;
        await act(async () => {
            try {
                await conn.init?.onopen?.(okResponse());
            } catch {
                /* a candidate may reject a response it does not like */
            }
        });
        await settle();
    }
}

// --- DOM probes ---------------------------------------------------------

function textsIn(root: HTMLElement): string[] {
    const out: string[] = [];
    root.querySelectorAll("*").forEach((node) => {
        const t = node.textContent;
        if (t === null) return;
        const trimmed = t.replace(/\s+/g, " ").trim();
        if (trimmed.length > 0 && trimmed.length < 200) out.push(trimmed);
    });
    return out;
}

function firstMatch(texts: string[], re: RegExp): string | undefined {
    for (const t of texts) if (re.test(t)) return t;
    return undefined;
}

function distinctMatches(texts: string[], re: RegExp): string[] {
    const seen: string[] = [];
    for (const t of texts) if (re.test(t) && !seen.includes(t)) seen.push(t);
    return seen;
}

const MONEY = /^\$[\d,]+\.\d{2}$/;
const RATE = /^[\d,]+\.\d%$/;
const GUESTS = /^[\d,]+ guests$/;
const PLAIN_NUMBER = /^[\d,]+$/;
const SHARES = /^[\d,]+ shares$/;
/** The bar chart writes whole-dollar revenue; the money regex above wants cents. */
const DOLLARS = /^\$[\d,]+$/;
const CHECKINS = /^([\d,]+)\s*total check-ins$/;

/**
 * The figure a labelled card is showing. The engagement cards draw a chart with
 * numeric axis labels of its own, so this pairs the heading with the element
 * beside it rather than scanning the panel for numbers.
 */
function labelledValue(host: HTMLElement, label: string): string | undefined {
    for (const node of Array.from(host.querySelectorAll("h1,h2,h3,h4,h5,h6"))) {
        if ((node.textContent ?? "").replace(/\s+/g, " ").trim() !== label) continue;
        const value = (node.nextElementSibling?.textContent ?? "").replace(/\s+/g, " ").trim();
        if (value.length > 0) return value;
    }
    return undefined;
}

export function readPanel(panel: PanelName): PanelView {
    const host = document.querySelector(`[data-vpanel="${panel}"]`) as HTMLElement | null;
    if (!host) return { kind: "loading" };
    const texts = textsIn(host);
    const has = (s: string) => texts.includes(s);

    switch (panel) {
        case "earnings": {
            if (!has("TOTAL EARNINGS")) return { kind: "loading" };
            const amount = firstMatch(texts, MONEY);
            if (!amount) return { kind: "loading" };
            return { kind: "data", values: { amount } };
        }
        case "checkin": {
            if (has("No check-ins yet")) return { kind: "empty", text: "No check-ins yet" };
            if (!has("Check-in Rate")) return { kind: "loading" };
            const rate = firstMatch(texts, RATE);
            if (!rate) return { kind: "loading" };
            return { kind: "data", values: { rate } };
        }
        case "retention": {
            if (has("No retention data available")) return { kind: "empty", text: "No retention data available" };
            if (has("No attendee data yet")) return { kind: "empty", text: "No attendee data yet" };
            const guests = distinctMatches(texts, GUESTS);
            if (guests.length < 2) return { kind: "loading" };
            return { kind: "data", values: { fresh: guests[0], returning: guests[1] } };
        }
        case "device": {
            if (has("No device data available")) return { kind: "empty", text: "No device data available" };
            if (has("No purchase data yet")) return { kind: "empty", text: "No purchase data yet" };
            const money = distinctMatches(texts, MONEY);
            if (money.length < 2) return { kind: "loading" };
            return { kind: "data", values: { iosRevenue: money[0], webRevenue: money[1] } };
        }
        case "demographics": {
            if (has("No demographics data available"))
                return { kind: "empty", text: "No demographics data available" };
            if (texts.some((t) => t.includes("at least 10 attendees")))
                return { kind: "empty", text: "locked" };
            const totals = distinctMatches(texts, PLAIN_NUMBER);
            const guests = distinctMatches(texts, GUESTS);
            if (!has("Male") || totals.length < 1 || guests.length < 2) return { kind: "loading" };
            return { kind: "data", values: { total: totals[0], male: guests[0], female: guests[1] } };
        }
        case "timeline": {
            if (has("No check-ins yet")) return { kind: "empty", text: "No check-ins yet" };
            const scanned = firstMatch(texts, CHECKINS);
            if (!scanned) return { kind: "loading" };
            const total = (CHECKINS.exec(scanned) ?? [])[1];
            if (total === undefined) return { kind: "loading" };
            const average = firstMatch(texts, /^Average scan time: [\d.]+s$/);
            return { kind: "data", values: average ? { total, average } : { total } };
        }
        case "location": {
            if (has("No location data available")) return { kind: "empty", text: "No location data available" };
            const revenues = distinctMatches(texts, DOLLARS);
            if (revenues.length < 1) return { kind: "loading" };
            return { kind: "data", values: { top: revenues[0], second: revenues[1] ?? "-" } };
        }
        case "engagement": {
            if (texts.some((t) => t.includes("Failed to load engagement data")))
                return { kind: "empty", text: "Failed to load engagement data" };
            const guests = labelledValue(host, "Total Guests");
            const shares = labelledValue(host, "Total Shares");
            if (guests === undefined || shares === undefined) return { kind: "loading" };
            return { kind: "data", values: { guests, shares } };
        }
        case "platform": {
            if (has("No engagement data available")) return { kind: "empty", text: "No engagement data available" };
            if (has("No engagement data yet")) return { kind: "empty", text: "No engagement data yet" };
            const shares = distinctMatches(texts, SHARES);
            if (shares.length < 2) return { kind: "loading" };
            return { kind: "data", values: { ios: shares[0], web: shares[1] } };
        }
    }
}

// --- module resolution --------------------------------------------------

export class SeamError extends Error {}

/**
 * Pick a component out of a module. Prefers the documented export, but falls
 * back to any exported function so a rename does not become a fake zero.
 */
export function pickComponent(mod: Record<string, unknown>, preferred: string, where: string): React.FC<any> {
    const direct = mod[preferred];
    if (typeof direct === "function") return direct as React.FC<any>;
    const fallback = Object.values(mod).find((v) => typeof v === "function");
    if (typeof fallback === "function") return fallback as React.FC<any>;
    throw new SeamError(`no component exported from ${where}`);
}

// --- control discovery --------------------------------------------------

export type ControlKind = "reconnect" | "halt" | "inert";

export interface DiscoveredControls {
    reconnect?: string;
    halt?: string;
    classified: Record<string, ControlKind>;
}

/**
 * Classify every function on the analytics context by exercising it:
 *   - a control that makes the client open another connection is a reconnect;
 *   - a control after which frames on the still-open connection stop landing
 *     is a halt;
 *   - anything else is inert.
 * No name is consulted except to break a tie between confirmed candidates.
 */
export async function discoverControls(
    mountScenario: () => Promise<{ ctxRef: { current: any }; unmount: () => void }>,
    probeFrames: { first: unknown; second: unknown },
    readAmount: () => string | undefined
): Promise<DiscoveredControls> {
    const first = await mountScenario();
    const names = Object.entries(first.ctxRef.current ?? {})
        .filter(([, v]) => typeof v === "function")
        .map(([k]) => k);
    first.unmount();
    resetConnections();

    const classified: Record<string, ControlKind> = {};

    for (const name of names) {
        const trial = await mountScenario();
        try {
            const conn = liveConnection();
            if (!conn) {
                classified[name] = "inert";
                continue;
            }
            await deliver(conn, { body: probeFrames.first });
            const before = readAmount();
            const connCountBefore = connections.length;

            await act(async () => {
                try {
                    trial.ctxRef.current?.[name]?.();
                } catch {
                    /* a control that throws when called bare is not our seam */
                }
            });
            await settle();

            if (connections.length > connCountBefore) {
                classified[name] = "reconnect";
                continue;
            }
            await deliver(conn, { body: probeFrames.second });
            const after = readAmount();
            classified[name] = after !== undefined && after !== before ? "inert" : "halt";
            if (before === undefined) classified[name] = "inert";
        } finally {
            trial.unmount();
            resetConnections();
        }
    }

    const pick = (kind: ControlKind, preferred: string[]) => {
        const hits = names.filter((n) => classified[n] === kind);
        for (const p of preferred) if (hits.includes(p)) return p;
        return hits[0];
    };

    return {
        reconnect: pick("reconnect", ["restart", "reconnect", "start"]),
        halt: pick("halt", ["stop", "halt", "close"]),
        classified,
    };
}

export function resetConnections() {
    connections.length = 0;
}

export function expectView(actual: PanelView, expected: PanelView, label: string) {
    expect(actual, label).toEqual(expected);
}

export { render };
