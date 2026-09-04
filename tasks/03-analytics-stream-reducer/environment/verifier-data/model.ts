// Independent model of the specification.
//
// Written from instruction.md, not from the reference solution. It shares no
// code with the workspace: no React, no hooks, no imports from src/, no reuse
// of the app's formatting helpers. It is a plain left fold over a step log that
// produces, for each panel, the text a correct implementation must be showing.
//
// The grader drives the real component tree with the same step log and compares
// what the DOM says against what this predicts. If the two disagree, either the
// candidate is wrong or this model is — and that has to be resolved before the
// task ships.

import {
    DEFAULT_RANGE,
    PanelName,
    QUERY_TYPES,
    QueryType,
    Scenario,
    ScenarioRange,
    snapshotKey,
    Step,
} from "./scenarios";

const KNOWN_SECTIONS = [
    "charts",
    "revenue",
    "demographics",
    "financials",
    "scanStats",
    "scanTimeline",
    "retention",
    "purchasesByLocation",
    "purchasesByDevice",
    "interactionsByPlatform",
    "__complete__",
];

/**
 * A section is in exactly one of four conditions.
 *   waiting  - the stream has not spoken about it yet
 *   held     - a payload arrived and is what the panel shows
 *   refused  - the stream reported it cannot produce this section
 *   closed   - the stream ended without ever producing it
 */
type Condition = "waiting" | "held" | "refused" | "closed";

interface Cell {
    condition: Condition;
    payload: Record<string, any> | null;
    /** Canonical form of the held payload, used to recognise a repeat. */
    canonical: string | null;
    /** Revision of the held payload, when the frame that carried it had one. */
    revision: number | null;
}

/** What one event's key in the browser's storage is holding. */
interface Kept {
    /** The window the figures in it were aggregated over. */
    range: ScenarioRange;
    cells: Record<string, Cell>;
}

interface ModelState {
    /** Whether frames arriving on the current generation are consumed at all. */
    reading: boolean;
    ended: boolean;
    /** The event whose dashboard is on screen. */
    eventId: string;
    /** The window the figures on screen were aggregated over. */
    range: ScenarioRange;
    cells: Record<string, Cell>;
    /**
     * What the browser is holding for each event: the figures the dashboard was
     * showing, the window they cover, and nothing else. One record per event, so
     * a change of window rewrites it like any other change to the screen. A
     * correct client rewrites this whenever what is on screen changes, which is
     * why the model does the same after every step rather than only at the
     * points that read it back.
     */
    store: Record<string, Kept>;
}

function freshCells(): Record<string, Cell> {
    const out: Record<string, Cell> = {};
    for (const s of KNOWN_SECTIONS) {
        if (s === "__complete__") continue;
        out[s] = { condition: "waiting", payload: null, canonical: null, revision: null };
    }
    return out;
}

/** The part of a dashboard a stored record can carry: the figures it is showing. */
function heldOnly(cells: Record<string, Cell>): Record<string, Cell> {
    const out: Record<string, Cell> = {};
    for (const [key, cell] of Object.entries(cells)) {
        if (cell.condition !== "held" || cell.payload === null) continue;
        out[key] = { ...cell };
    }
    return out;
}

/**
 * Stand a dashboard back up from what was kept, if what was kept is a record of
 * this dashboard: the figures return, and only when they were aggregated over
 * the window on screen. The previous read's refusals and its ending do not
 * return either way, because a page that has just loaded has not reached them.
 */
function hydrate(kept: Kept | undefined, range: ScenarioRange): Record<string, Cell> {
    const cells = freshCells();
    if (!kept || kept.range !== range) return cells;
    for (const [key, cell] of Object.entries(kept.cells)) {
        if (cells[key] === undefined) continue;
        cells[key] = { ...cell };
    }
    return cells;
}

/**
 * Read one stored value the way a client that can read all three layouts would.
 * The layout this release writes keeps a revision beside each figure and names
 * the window they cover; the one before it keeps the revisions and names no
 * window, because when it was written there was one; the oldest has nowhere for
 * a revision to live either, so everything it restores is unversioned.
 */
function decodeStored(raw: string, eventId: string): Kept | null {
    let parsed: any;
    try {
        parsed = JSON.parse(raw);
    } catch {
        return null;
    }
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    if (typeof parsed.version !== "number" || parsed.eventId !== eventId) return null;

    const cells: Record<string, Cell> = {};
    const add = (section: string, data: unknown, revision: unknown) => {
        if (!KNOWN_SECTIONS.includes(section) || section === "__complete__") return;
        if (data === undefined || data === null) return;
        cells[section] = {
            condition: "held",
            payload: data as Record<string, any>,
            canonical: canonicalise(data),
            revision: typeof revision === "number" && Number.isFinite(revision) ? revision : null,
        };
    };

    let range: ScenarioRange = DEFAULT_RANGE;
    if (parsed.version === 3) {
        if (typeof parsed.range !== "string") return null;
        range = parsed.range as ScenarioRange;
    }

    if (parsed.version === 3 || parsed.version === 2) {
        for (const [section, cell] of Object.entries(parsed.sections ?? {})) {
            const entry = cell as { data?: unknown; revision?: unknown } | null;
            if (entry === null || typeof entry !== "object") continue;
            add(section, entry.data, entry.revision);
        }
    } else if (parsed.version === 1) {
        for (const [section, value] of Object.entries(parsed.data ?? {})) add(section, value, null);
    } else {
        return null;
    }

    return Object.keys(cells).length > 0 ? { range, cells } : null;
}

/** What the browser held before the page loaded, decoded per event. */
function seedStore(scenario: Scenario): Record<string, Kept> {
    const store: Record<string, Kept> = {};
    for (const entry of scenario.stored ?? []) {
        for (const eventId of [scenario.startEventId, ...navigatedEvents(scenario)]) {
            if (entry.key !== snapshotKey(eventId)) continue;
            const decoded = decodeStored(entry.value, eventId);
            if (decoded) store[eventId] = decoded;
        }
    }
    return store;
}

function navigatedEvents(scenario: Scenario): string[] {
    const out: string[] = [];
    for (const step of scenario.steps) {
        if (step.op === "navigate" && !out.includes(step.eventId)) out.push(step.eventId);
    }
    return out;
}

/**
 * Fill in, from the analytics query, every section this read has finished with
 * and has nothing to show for — and only the sections that query can answer for.
 * A figure that arrives this way carries no revision, because the query does not
 * version anything.
 */
function applyQuery(state: ModelState, scenario: Scenario): void {
    if (scenario.signedOut) return;
    for (const type of QUERY_TYPES) {
        const cell = state.cells[type as string];
        if (!cell || cell.condition === "waiting" || cell.condition === "held") continue;
        const answer = scenario.query?.[type as QueryType];
        if (!answer || !answer.eligible || answer.data === null || answer.data === undefined) continue;
        cell.condition = "held";
        cell.payload = answer.data as Record<string, any>;
        cell.canonical = canonicalise(answer.data);
        cell.revision = null;
    }
}

/** Order-insensitive canonical form, so a repeat is recognised by value. */
function canonicalise(value: unknown): string {
    if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "undefined";
    if (Array.isArray(value)) return "[" + value.map(canonicalise).join(",") + "]";
    const entries = Object.keys(value as Record<string, unknown>)
        .sort()
        .map((k) => JSON.stringify(k) + ":" + canonicalise((value as Record<string, unknown>)[k]));
    return "{" + entries.join(",") + "}";
}

function decodeFrame(step: { body?: unknown; raw?: string }): Record<string, any> | null {
    const text = step.raw !== undefined ? step.raw : JSON.stringify(step.body);
    try {
        const parsed = JSON.parse(text);
        if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return null;
        if (typeof parsed.section !== "string") return null;
        return parsed;
    } catch {
        return null;
    }
}

function applyFrame(state: ModelState, frame: Record<string, any>): void {
    const section = frame.section as string;
    if (!KNOWN_SECTIONS.includes(section)) return;

    if (section === "__complete__") {
        state.ended = true;
        closeOut(state);
        return;
    }

    const cell = state.cells[section];

    // Older news than the panel is showing. This is what a replay after a
    // resume looks like, and it must not be able to change anything at all -
    // not the value, not a failure, not the fact of having been delivered.
    if (typeof frame.revision === "number" && cell.revision !== null && frame.revision <= cell.revision) {
        return;
    }

    if (typeof frame.error === "string" && frame.error.length > 0) {
        // A refusal settles this section and nothing else. A section that
        // already has a value keeps showing it.
        if (cell.condition !== "held") cell.condition = "refused";
        return;
    }

    if (frame.data === undefined || frame.data === null) return;

    const canonical = canonicalise(frame.data);
    if (cell.condition === "held" && cell.canonical === canonical) return; // a repeat changes nothing
    cell.condition = "held";
    cell.payload = frame.data as Record<string, any>;
    cell.canonical = canonical;
    cell.revision = typeof frame.revision === "number" ? frame.revision : null;
}

/** Nothing more is coming: every section still in flight has to stop waiting. */
function closeOut(state: ModelState): void {
    for (const key of Object.keys(state.cells)) {
        if (state.cells[key].condition === "waiting") state.cells[key].condition = "closed";
    }
}

/**
 * Where a resumed read has to continue from: the newest revision on screen.
 * A section that is refused or still waiting has nothing worth keeping, so it
 * cannot raise the resume point.
 */
export function resumePoint(state: ModelState): number | null {
    let newest: number | null = null;
    for (const cell of Object.values(state.cells)) {
        if (cell.condition !== "held" || cell.revision === null) continue;
        if (newest === null || cell.revision > newest) newest = cell.revision;
    }
    return newest;
}

/** Fold the log up to and including step `upTo`. */
export function fold(scenario: Scenario, upTo: number): ModelState {
    const store = seedStore(scenario);
    const range = scenario.range ?? DEFAULT_RANGE;
    const state: ModelState = {
        reading: !scenario.signedOut,
        ended: false,
        eventId: scenario.startEventId,
        range,
        // A page that loads onto a dashboard the browser has a record for is not
        // showing skeletons: it is showing what the host saw last time. A page
        // with no token never gets that far.
        cells: scenario.signedOut ? freshCells() : hydrate(store[scenario.startEventId], range),
        store,
    };
    applyQuery(state, scenario);
    persist(state);

    for (let i = 0; i <= upTo; i++) {
        const step = scenario.steps[i] as Step;
        switch (step.op) {
            case "msg":
                if (state.reading) applyFrame(state, decodeFrame(step) ?? { section: "__ignored__" });
                break;
            case "staleMsg":
                // Superseded generation: never observable.
                break;
            case "reconnect":
                state.reading = true;
                state.ended = false;
                state.cells = freshCells();
                // Nothing is done to the stored copy here. `persist` runs after
                // every step and writes the held cells through, so a screen with
                // nothing on it leaves a record with nothing in it. That is the
                // record mirroring the screen rather than a rule about restarts.
                break;
            case "stop":
                state.reading = false;
                break;
            case "transportError":
                // The client is expected to recover without losing anything.
                state.reading = true;
                break;
            case "transportDies":
                // Reconnecting failed until there was nothing left to try. The
                // read is over, so no panel may still be waiting - but the
                // figures that did arrive are still the best answer there is.
                state.reading = false;
                state.ended = true;
                closeOut(state);
                break;
            case "assertOpen":
            case "assertQuery":
                break;
            case "navigate":
                state.reading = true;
                state.ended = false;
                state.eventId = step.eventId;
                state.cells = hydrate(state.store[step.eventId], state.range);
                break;
            case "range":
                // Another window over the same event is another dashboard: its
                // figures are different aggregates and its revisions belong to a
                // read that has not started yet. What the browser kept for this
                // event is only worth standing up if it is a record of the
                // window now being asked for.
                state.reading = true;
                state.ended = false;
                state.range = step.range;
                state.cells = hydrate(state.store[state.eventId], step.range);
                break;
            case "reload":
                // The tree is gone and built again. Storage is all that crosses
                // the gap, so the figures return and every conclusion the
                // previous read reached does not.
                state.reading = true;
                state.ended = false;
                state.cells = hydrate(state.store[state.eventId], state.range);
                break;
            case "assert":
                break;
        }
        applyQuery(state, scenario);
        persist(state);
    }
    return state;
}

/** Write the figures on screen, and the window they are about, to the copy. */
function persist(state: ModelState): void {
    state.store[state.eventId] = { range: state.range, cells: heldOnly(state.cells) };
}

// --- expected rendering -------------------------------------------------
// Re-derived from the panel contract, deliberately not importing the app's
// formatPrice / toFixed call sites.

function dollars(cents: number): string {
    const sign = cents < 0 ? "-" : "";
    const abs = Math.abs(cents);
    const whole = Math.floor(abs / 100);
    const frac = Math.round(abs - whole * 100);
    return `${sign}${whole}.${String(frac).padStart(2, "0")}`;
}

function oneDecimal(n: number): string {
    return n.toFixed(1);
}

function grouped(n: number): string {
    return n.toLocaleString("en-US");
}

export type PanelView =
    | { kind: "loading" }
    | { kind: "empty"; text: string }
    | { kind: "data"; values: Record<string, string> };

export function expectedPanel(state: ModelState, panel: PanelName): PanelView {
    switch (panel) {
        case "earnings": {
            const cell = state.cells.financials;
            // The earnings panel has no empty state: it shows its placeholder
            // whenever there is no financials payload, settled or not.
            if (cell.condition !== "held" || !cell.payload) return { kind: "loading" };
            return { kind: "data", values: { amount: "$" + dollars(Number(cell.payload.net) || 0) } };
        }
        case "checkin": {
            const cell = state.cells.scanStats;
            if (cell.condition !== "held" || !cell.payload) return { kind: "loading" };
            if (Number(cell.payload.scannedPeople) === 0) return { kind: "empty", text: "No check-ins yet" };
            return {
                kind: "data",
                values: { rate: oneDecimal(Number(cell.payload.scanRatePercent)) + "%" },
            };
        }
        case "retention": {
            const cell = state.cells.retention;
            if (cell.condition === "waiting") return { kind: "loading" };
            if (cell.condition !== "held" || !cell.payload)
                return { kind: "empty", text: "No retention data available" };
            const nu = Number(cell.payload.newUsersCount) || 0;
            const ru = Number(cell.payload.returningUsersCount) || 0;
            if (nu + ru === 0) return { kind: "empty", text: "No attendee data yet" };
            return {
                kind: "data",
                values: { fresh: `${grouped(nu)} guests`, returning: `${grouped(ru)} guests` },
            };
        }
        case "device": {
            const cell = state.cells.purchasesByDevice;
            if (cell.condition === "waiting") return { kind: "loading" };
            if (cell.condition !== "held" || !cell.payload) return { kind: "empty", text: "No device data available" };
            const ios = cell.payload.ios ?? {};
            const web = cell.payload.web ?? {};
            if ((Number(ios.count) || 0) + (Number(web.count) || 0) === 0)
                return { kind: "empty", text: "No purchase data yet" };
            return {
                kind: "data",
                values: {
                    iosRevenue: "$" + dollars(Number(ios.revenueCents) || 0),
                    webRevenue: "$" + dollars(Number(web.revenueCents) || 0),
                },
            };
        }
        case "demographics": {
            const cell = state.cells.demographics;
            if (cell.condition === "waiting") return { kind: "loading" };
            if (cell.condition !== "held" || !cell.payload)
                return { kind: "empty", text: "No demographics data available" };
            const g = cell.payload.gender ?? {};
            const male = Number(g.male) || 0;
            const female = Number(g.female) || 0;
            const other = Number(g.other) || 0;
            const nonBinary = Number(g.nonBinary) || 0;
            const total = male + female + other + nonBinary;
            if (total === 0) return { kind: "empty", text: "No demographics data available" };
            return {
                kind: "data",
                values: {
                    total: grouped(total),
                    male: `${grouped(male)} guests`,
                    female: `${grouped(female)} guests`,
                },
            };
        }
        case "timeline": {
            const cell = state.cells.scanTimeline;
            if (cell.condition === "waiting") return { kind: "loading" };
            const buckets: any[] = Array.isArray(cell.payload?.timeline) ? cell.payload!.timeline : [];
            const scanned = buckets.reduce((sum, b) => sum + (Number(b?.peopleScannedBucket) || 0), 0);
            if (cell.condition !== "held" || !cell.payload || buckets.length === 0 || scanned === 0)
                return { kind: "empty", text: "No check-ins yet" };
            const values: Record<string, string> = { total: String(scanned) };
            const averageMs = cell.payload.averageScanTimeMs;
            if (averageMs !== null && averageMs !== undefined) {
                values.average = `Average scan time: ${oneDecimal(Number(averageMs) / 1000)}s`;
            }
            return { kind: "data", values };
        }
        case "location": {
            const cell = state.cells.purchasesByLocation;
            if (cell.condition === "waiting") return { kind: "loading" };
            const rows: any[] = Array.isArray(cell.payload) ? (cell.payload as any[]) : [];
            if (cell.condition !== "held" || rows.length === 0)
                return { kind: "empty", text: "No location data available" };
            const ranked = [...rows]
                .sort((a, b) => (Number(b?.grossRevenueCents) || 0) - (Number(a?.grossRevenueCents) || 0))
                .slice(0, 8)
                .map((row) => "$" + grouped((Number(row?.grossRevenueCents) || 0) / 100));
            return { kind: "data", values: { top: ranked[0], second: ranked[1] ?? "-" } };
        }
        case "engagement": {
            const cell = state.cells.charts;
            // This panel has no empty state: with no charts payload it shows its
            // placeholder whether the section is still coming or was closed out.
            // A section the stream *refused* is the exception, because the panel
            // reads the per-section failure and says so — which also means a
            // figure recovered from elsewhere has to clear that failure, or the
            // panel goes on reporting a section it is holding.
            if (cell.condition === "refused") return { kind: "empty", text: "Failed to load engagement data" };
            if (cell.condition !== "held" || !cell.payload) return { kind: "loading" };
            const summary = cell.payload.summary ?? {};
            return {
                kind: "data",
                // Rendered straight into the card, so no grouping is applied.
                values: {
                    guests: String(Number(summary.numRsvps) || 0),
                    shares: String(Number(summary.numShares) || 0),
                },
            };
        }
        case "platform": {
            const cell = state.cells.interactionsByPlatform;
            if (cell.condition === "waiting") return { kind: "loading" };
            if (cell.condition !== "held" || !cell.payload)
                return { kind: "empty", text: "No engagement data available" };
            const p = cell.payload;
            const views =
                (Number(p.numViewsIOS) || 0) + (Number(p.numViewsWeb) || 0) + (Number(p.numViewsNoUser) || 0);
            const iosShares = Number(p.numSharesIOS) || 0;
            const webShares = Number(p.numSharesWeb) || 0;
            if (views === 0 && iosShares + webShares === 0) return { kind: "empty", text: "No engagement data yet" };
            return {
                kind: "data",
                values: { ios: `${grouped(iosShares)} shares`, web: `${grouped(webShares)} shares` },
            };
        }
    }
}
