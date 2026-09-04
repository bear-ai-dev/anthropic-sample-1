// Scripted stream inputs. These are *data*: both the DOM harness and the
// independent model consume them, and neither shares any logic with the other.

export const EVENT_A = "9f1c0d2a-1111-4aaa-8000-000000000001";
export const EVENT_B = "9f1c0d2a-2222-4bbb-8000-000000000002";

/**
 * The event the analytics aggregator last computed for, and therefore whose
 * document comes back when it is asked about an event that has none of its own.
 * No dashboard in this table is ever pointed at it; it exists so that an
 * ineligible answer's `analytics.id` is a foreign id, which is how the wire
 * capture in the workspace records the same case.
 */
export const EVENT_UNRELATED = "9f1c0d2a-3333-4ccc-8000-000000000003";

export const FIN_A = {
    net: 407500,
    payment: { pending: 12000, available: 395500, linked: 1 },
    refunded: 0,
    revenueBySource: [
        { source: "feed", sum: 195500, count: 121 },
        { source: "profile", sum: 3500, count: 2 },
        { source: "deepLink", sum: 26000, count: 16 },
        { source: "unknown", sum: 182500, count: 129 },
    ],
};

export const FIN_B = {
    net: 511000,
    payment: { pending: 0, available: 511000, linked: 1 },
    refunded: 2500,
    revenueBySource: [{ source: "feed", sum: 511000, count: 200 }],
};

export const FIN_POISON = {
    net: 999900,
    payment: { pending: 0, available: 999900, linked: 1 },
    refunded: 0,
    revenueBySource: [],
};

export const SCAN_A = {
    scannedPeople: 178,
    expectedAttendees: 210,
    scanRatePercent: 84.76,
    repeatScansCount: 12,
    invalidScansCount: 3,
    expiredScansCount: 1,
};

export const SCAN_B = {
    scannedPeople: 190,
    expectedAttendees: 210,
    scanRatePercent: 90.476,
};

export const SCAN_ZERO = { scannedPeople: 0, expectedAttendees: 210, scanRatePercent: 0 };

export const RET_A = {
    newUsersCount: 141,
    returningUsersCount: 68,
    returningUsersPercent: 32.53,
};

export const RET_POISON = {
    newUsersCount: 9021,
    returningUsersCount: 4010,
    returningUsersPercent: 30.79,
};

export const DEV_A = {
    ios: { count: 186, percentage: 69, revenueCents: 285500 },
    web: { count: 82, percentage: 31, revenueCents: 122000 },
};

export const DEMO_A = {
    gender: { male: 104, female: 102, other: 3, nonBinary: 0 },
    age: {
        age18_20: 83,
        age21_23: 54,
        age24_26: 5,
        age27_30: 1,
        age31_35: 2,
        age36_40: 0,
        age40_50: 0,
        age50_plus: 0,
    },
};

export const TL_A = {
    timeline: [
        { startTime: 1735689600, endTime: 1735693200, midpoint: 1735691400, peopleScannedBucket: 41, peopleScannedCumulative: 41 },
        { startTime: 1735693200, endTime: 1735696800, midpoint: 1735695000, peopleScannedBucket: 96, peopleScannedCumulative: 137 },
        { startTime: 1735696800, endTime: 1735700400, midpoint: 1735698600, peopleScannedBucket: 41, peopleScannedCumulative: 178 },
    ],
    averageScanTimeMs: 3400,
};

export const LOC_A = [
    { locationKey: "New York, NY", numOrders: 121, numUniqueBuyers: 118, grossRevenueCents: 285500 },
    { locationKey: "Boston, MA", numOrders: 44, numUniqueBuyers: 41, grossRevenueCents: 122000 },
    { locationKey: "Austin, TX", numOrders: 12, numUniqueBuyers: 12, grossRevenueCents: 33000 },
];

export const PLAT_A = {
    numViewsIOS: 1840,
    numViewsWeb: 920,
    numViewsNoUser: 310,
    numSharesIOS: 74,
    numSharesWeb: 31,
};

const buckets = (values: number[]) =>
    values.map((value, i) => ({
        startTime: 1735689600 + i * 3600,
        endTime: 1735693200 + i * 3600,
        midpoint: 1735691400 + i * 3600,
        value,
        aggregatedValue: values.slice(0, i + 1).reduce((a, b) => a + b, 0),
    }));

const chartsPayload = (rsvps: number, shares: number) => ({
    summary: {
        numRsvps: rsvps,
        numUniqueViews: 9042,
        numShares: shares,
        numViews: 13990,
        numLikes: 602,
        percentConversions: 4.21,
    },
    rsvps: buckets([12, 140, rsvps - 152]),
    views: buckets([400, 6000, 7590]),
    uniqueViews: buckets([300, 4000, 4742]),
    likes: buckets([20, 300, 282]),
    shares: buckets([2, 30, shares - 32]),
    conversions: buckets([1.1, 2.2, 0.91]),
});

/** Off the stream. */
export const CHARTS_A = chartsPayload(381, 57);
/** Off the analytics query, and deliberately nothing like the stream's. */
export const CHARTS_Q = chartsPayload(206, 41);

export const DEMO_Q = {
    gender: { male: 61, female: 58, other: 1, nonBinary: 0 },
    age: { age18_20: 40, age21_23: 60, age24_26: 15, age27_30: 5, age31_35: 0, age36_40: 0, age40_50: 0, age50_plus: 0 },
};

export const REV_Q = {
    tickets: [{ startTime: 1735689600, endTime: 1735693200, midpoint: 1735691400, aggregatedAmount: 90000, aggregatedNumber: 30, amount: 90000, number: 30 }],
    ticketsType: {},
};

/** Which panel a section feeds. Used only to name assertion targets. */
export type PanelName =
    | "earnings"
    | "checkin"
    | "retention"
    | "device"
    | "demographics"
    | "timeline"
    | "location"
    | "platform"
    | "engagement";

export const ALL_PANELS: PanelName[] = [
    "earnings",
    "checkin",
    "retention",
    "device",
    "demographics",
    "timeline",
    "location",
    "platform",
    "engagement",
];

/**
 * The panels that have a placeholder and an empty state that read differently,
 * which is what makes "still waiting" distinguishable from "not coming". Eight
 * panels feeding eight sections is also what makes a partial job visible: a
 * per-section decision applied to some panels and not others fails here.
 */
export const SETTLING_PANELS: PanelName[] = [
    "retention",
    "device",
    "demographics",
    "timeline",
    "location",
    "platform",
];

/**
 * The aggregation windows the dashboard offers, named as the query string names
 * them. A window is part of what a figure *is*: both endpoints aggregate over
 * the one the request asks for.
 */
export type ScenarioRange = "event" | "week" | "day";

export const RANGES: ScenarioRange[] = ["event", "week", "day"];

/** What the page shows when the query string says nothing about a window. */
export const DEFAULT_RANGE: ScenarioRange = "event";

/**
 * How many buckets each window is cut into. This is the one number that tells
 * two windows apart in a request, and it is asserted by value: a request is
 * over this window if it carries this count as the value of any parameter.
 *
 * The table is duplicated from the dashboard's own, and `route-audit.py`'s
 * DRIFT check reads the two against each other — a grader that asserted a
 * bucket count the workspace does not use would be grading a convention no
 * solver could read.
 */
export const RANGE_BUCKETS: Record<ScenarioRange, number> = { event: 10, week: 84, day: 96 };

export type Step =
    /** A stream frame arriving on the current connection. `raw` sends the string verbatim. */
    | { op: "msg"; body?: unknown; raw?: string }
    /** A stream frame arriving late on a connection that has already been superseded. */
    | { op: "staleMsg"; body?: unknown; raw?: string }
    /** Ask the client to re-open the stream. Establishes a new generation. */
    | { op: "reconnect" }
    /** Ask the client to stop consuming. */
    | { op: "stop" }
    /** The transport fails; the client is expected to recover and keep reading. */
    | { op: "transportError" }
    /** The transport fails and stays broken until the client stops trying. */
    | { op: "transportDies" }
    /**
     * Check what the connection the client most recently opened asked for.
     *   continues - it must carry the newest revision on screen
     *   fresh     - it must carry no revision at all
     */
    | { op: "assertOpen"; asks: "continues" | "fresh"; note: string }
    /**
     * Check what the most recent request to the ordinary analytics query for
     * this section asked for. Graded on values: the window on screen has to be
     * in there and no other window may be.
     */
    | { op: "assertQuery"; section: QueryType; note: string }
    /** The viewed event changes. */
    | { op: "navigate"; eventId: string }
    /** The host asks for another aggregation window, on the same event. */
    | { op: "range"; range: ScenarioRange; note: string }
    /**
     * The page is closed and opened again on the same event: the tree is torn
     * down and built back up with the browser's storage left exactly as the
     * client wrote it.
     */
    | { op: "reload"; note: string }
    /** Compare the listed panels against the model's prediction. */
    | { op: "assert"; panels: PanelName[]; note: string };

/** The sections the ordinary analytics query can answer for. */
export type QueryType = "charts" | "revenue" | "demographics";

export const QUERY_TYPES: QueryType[] = ["charts", "revenue", "demographics"];

/** What the analytics query answers with for one section. */
export interface QueryAnswer {
    /**
     * Whether the event has analytics at all. When false the harness answers
     * with `data` anyway, under another event's id and with `ready`/`updated`
     * false, because that is what the endpoint does and what the workspace
     * capture records; a client may notice by any of those.
     */
    eligible: boolean;
    /** The section value the query holds, or null when it has not computed one. */
    data: unknown | null;
}

/** One entry the browser already had in local storage before the page loaded. */
export interface StoredEntry {
    key: string;
    value: string;
}

export const snapshotKey = (eventId: string) => `ExampleCo.analytics.snapshot:${eventId}`;

/**
 * A record of the layout this release writes: revisions beside the figures, and
 * the window they were aggregated over.
 */
export const storedStamped = (
    eventId: string,
    range: ScenarioRange,
    savedAt: number,
    sections: Record<string, { revision: number | null; data: unknown }>
): StoredEntry => ({
    key: snapshotKey(eventId),
    value: JSON.stringify({ version: 3, eventId, range, savedAt, sections }),
});

/**
 * The layout before it: the same figures and revisions, and nowhere to say which
 * window they cover, because when it was written there was only one.
 */
export const storedUnstamped = (
    eventId: string,
    savedAt: number,
    sections: Record<string, { revision: number | null; data: unknown }>
): StoredEntry => ({
    key: snapshotKey(eventId),
    value: JSON.stringify({ version: 2, eventId, savedAt, sections }),
});

export const storedPrevious = (eventId: string, updatedAt: number, data: Record<string, unknown>): StoredEntry => ({
    key: snapshotKey(eventId),
    value: JSON.stringify({ version: 1, eventId, updatedAt, data }),
});

export const storedRaw = (key: string, value: string): StoredEntry => ({ key, value });

/**
 * Every revision this scenario ever names, on the wire or in storage. A read
 * that must ask for the stream from the beginning may carry none of them.
 */
export function scenarioRevisions(scenario: Scenario): number[] {
    const found: number[] = [];
    const note = (revision: unknown) => {
        if (typeof revision === "number" && !found.includes(revision)) found.push(revision);
    };
    for (const step of scenario.steps) {
        if (step.op !== "msg" && step.op !== "staleMsg") continue;
        note((step.body as { revision?: unknown } | undefined)?.revision);
    }
    for (const entry of scenario.stored ?? []) {
        let parsed: any;
        try {
            parsed = JSON.parse(entry.value);
        } catch {
            continue;
        }
        for (const cell of Object.values(parsed?.sections ?? {})) {
            note((cell as { revision?: unknown } | null)?.revision);
        }
    }
    return found;
}

export interface Scenario {
    id: string;
    rule: string;
    /** When set, the tree is rendered with no auth token. */
    signedOut?: boolean;
    startEventId: string;
    /**
     * The window the page loads on, as the query string would carry it. Left
     * out, the page loads with nothing said about a window, which is the whole
     * event.
     */
    range?: ScenarioRange;
    /** What local storage held before the page loaded. */
    stored?: StoredEntry[];
    /**
     * What the analytics query answers with, per section. A section left out is
     * answered `eligible` with nothing computed, which is what the endpoint says
     * about an event whose analytics have not been built yet.
     */
    query?: Partial<Record<QueryType, QueryAnswer>>;
    steps: Step[];
}

// Frames carry a revision when the scenario cares about ordering across a
// resume, and omit it otherwise: both shapes occur on the wire.
const frame = (section: string, data: unknown, revision?: number) => ({
    op: "msg" as const,
    body: revision === undefined ? { section, data } : { section, data, revision },
});
const fin = (data: unknown, revision?: number) => frame("financials", data, revision);
const scan = (data: unknown, revision?: number) => frame("scanStats", data, revision);
const demo = (data: unknown, revision?: number) => frame("demographics", data, revision);
const ret = (data: unknown, revision?: number) => frame("retention", data, revision);
const dev = (data: unknown, revision?: number) => frame("purchasesByDevice", data, revision);
const timeline = (data: unknown, revision?: number) => frame("scanTimeline", data, revision);
const location = (data: unknown, revision?: number) => frame("purchasesByLocation", data, revision);
const platform = (data: unknown, revision?: number) => frame("interactionsByPlatform", data, revision);
const charts = (data: unknown, revision?: number) => frame("charts", data, revision);
const complete = { op: "msg" as const, body: { section: "__complete__" } };
const check = (panels: PanelName[], note: string) => ({ op: "assert" as const, panels, note });

// Scenario design note: rules are kept off each other's observables where that
// is possible, so that a candidate breaking one rule fails one test. The
// check-in panel is used only by G1, earnings only by G5..G12, and the
// retention/device pair carries the independent-settling rules.
//
// That separation holds for the scenarios up to S20 and is deliberately given
// up by the cross-product block at the bottom: "still waiting" is the observable
// that distinguishes a dropped frame from an applied one, so a scenario about
// which connection may speak has to assert it. An implementation that settles
// sections too eagerly therefore fails several tests rather than one. The trade
// is deliberate: attribution is a debugging convenience, while breadth of
// situation is what the reward is measuring.
export const SCENARIOS: Scenario[] = [
    {
        id: "S1",
        rule: "G1",
        startEventId: EVENT_A,
        steps: [
            check(ALL_PANELS, "nothing delivered yet: every panel is still loading"),
            fin(FIN_A, 21),
            check(["earnings"], "earnings renders as soon as its own section lands"),
            scan(SCAN_A, 22),
            check(["earnings", "checkin"], "check-in renders without waiting for the stream to end"),
            timeline(TL_A, 23),
            location(LOC_A, 24),
            platform(PLAT_A, 25),
            check(
                ["earnings", "checkin", "timeline", "location", "platform"],
                "every panel renders off its own section while the rest are still in flight"
            ),
        ],
    },
    {
        id: "S15",
        rule: "G1",
        startEventId: EVENT_A,
        steps: [scan(SCAN_ZERO), check(["checkin"], "a zero-scan payload is data, not absence")],
    },
    {
        id: "S2",
        rule: "G2",
        startEventId: EVENT_A,
        steps: [
            fin(FIN_A, 21),
            ret(RET_A, 22),
            check(
                ["device", "demographics", "timeline", "location", "platform"],
                "every section still in flight keeps its own loading state"
            ),
        ],
    },
    {
        id: "S3",
        rule: "G3",
        startEventId: EVENT_A,
        steps: [
            fin(FIN_A),
            demo(DEMO_A),
            { op: "msg", body: { section: "retention", error: "upstream timeout" } },
            check(
                ["retention", "demographics", "earnings"],
                "a failed section settles on its own and leaves every other panel alone"
            ),
        ],
    },
    {
        id: "S14",
        rule: "G3",
        startEventId: EVENT_A,
        steps: [
            ret(RET_A),
            dev(DEV_A),
            { op: "msg", body: { section: "demographics", error: "section unavailable" } },
            check(
                ["retention", "device", "demographics"],
                "a failed section does not blank the panels that already have data"
            ),
        ],
    },
    {
        id: "S4",
        rule: "G4",
        startEventId: EVENT_A,
        steps: [
            fin(FIN_A, 21),
            demo(DEMO_A, 22),
            complete,
            check(
                ["earnings", "demographics", ...SETTLING_PANELS.filter((p) => p !== "demographics")],
                "completion keeps what arrived and settles every panel that never heard anything"
            ),
        ],
    },
    {
        id: "S5",
        rule: "G5",
        startEventId: EVENT_A,
        steps: [
            fin(FIN_A),
            demo(DEMO_A),
            { op: "msg", raw: "{ this is not json" },
            check(["earnings", "demographics"], "a malformed frame changes nothing"),
            ret(RET_A),
            check(["earnings", "retention"], "the stream still works after a malformed frame"),
        ],
    },
    {
        id: "S6",
        rule: "G6",
        startEventId: EVENT_A,
        steps: [
            fin(FIN_A),
            demo(DEMO_A),
            { op: "msg", body: { section: "notARealSection", data: { net: 1 } } },
            check(["earnings", "demographics"], "an unknown section changes nothing"),
            ret(RET_A),
            check(["earnings", "retention"], "the stream still works after an unknown section"),
        ],
    },
    {
        id: "S7",
        rule: "G7",
        startEventId: EVENT_A,
        // Asserted after every delivery, not only at the end: an implementation
        // that folds a repeat into a running total and then corrects itself on
        // the next repeat would slip past a single assertion at the end.
        steps: [
            fin(FIN_A),
            check(["earnings"], "first delivery"),
            fin(FIN_A),
            check(["earnings"], "a second delivery of the same payload reads as one delivery"),
            fin(FIN_A),
            check(["earnings"], "and a third"),
        ],
    },
    {
        id: "S8",
        rule: "G8",
        startEventId: EVENT_A,
        steps: [
            fin(FIN_A),
            check(["earnings"], "first delivery"),
            fin(FIN_B),
            check(["earnings"], "a fresh payload for a section already received must win"),
        ],
    },
    {
        id: "S9",
        rule: "G9",
        startEventId: EVENT_A,
        steps: [
            fin(FIN_A),
            { op: "reconnect" },
            fin(FIN_B),
            check(["earnings"], "the new generation is what is displayed"),
            { op: "staleMsg", body: { section: "financials", data: FIN_POISON } },
            check(["earnings"], "a late frame from the superseded generation is dropped"),
        ],
    },
    {
        id: "S10",
        rule: "G10",
        startEventId: EVENT_A,
        steps: [
            fin(FIN_A),
            ret(RET_A),
            { op: "stop" },
            { op: "msg", body: { section: "financials", data: FIN_POISON } },
            { op: "msg", body: { section: "retention", data: RET_POISON } },
            check(["earnings", "retention"], "nothing lands after the consumer is stopped"),
        ],
    },
    {
        id: "S11",
        rule: "G11",
        startEventId: EVENT_A,
        steps: [
            fin(FIN_A),
            complete,
            { op: "navigate", eventId: EVENT_B },
            check(["earnings"], "the previous event's values are gone"),
            fin(FIN_B),
            check(["earnings"], "the new event's values render"),
            { op: "staleMsg", body: { section: "financials", data: FIN_POISON } },
            check(["earnings"], "a late frame for the previous event is dropped"),
        ],
    },
    {
        id: "S12",
        rule: "G12",
        startEventId: EVENT_A,
        steps: [
            fin(FIN_A),
            { op: "transportError" },
            check(["earnings"], "a transport failure does not discard what arrived"),
            ret(RET_A),
            check(["earnings", "retention"], "reading resumes after the reconnect"),
        ],
    },
    {
        id: "S16",
        rule: "G14",
        startEventId: EVENT_A,
        // A resume replays what the backend already produced. Those frames are
        // old news and must lose to what the panel is showing, whatever figures
        // they carry.
        //
        // Deliberately no "a newer frame wins" assertion here: that is G8's
        // observable, and keeping it out of this scenario is what lets a
        // candidate that never updates a section fail G8 alone.
        steps: [
            fin(FIN_B, 34),
            check(["earnings"], "first delivery"),
            fin(FIN_A, 21),
            check(["earnings"], "a replay of a revision already passed does not displace it"),
            fin(FIN_A, 34),
            check(["earnings"], "and neither does a replay at the revision on screen"),
            fin(FIN_A, 33),
            check(["earnings"], "nor one just behind it"),
        ],
    },
    {
        id: "S20",
        rule: "G14",
        startEventId: EVENT_A,
        // Revisions count across the whole stream, but they are only comparable
        // per section: a section holding nothing is behind on everything, so a
        // replay for it is news however low its number is.
        steps: [
            fin(FIN_A, 47),
            { op: "transportError" },
            demo(DEMO_A, 30),
            check(
                ["earnings", "demographics"],
                "a section this panel never had is applied, even below the newest revision seen"
            ),
        ],
    },
    {
        id: "S17",
        rule: "G15",
        startEventId: EVENT_A,
        // Reconnecting keeps failing. Whatever arrived stays, and no panel is
        // left waiting for something that is never coming.
        steps: [
            fin(FIN_A, 21),
            ret(RET_A, 22),
            { op: "transportDies" },
            check(["earnings", "retention"], "what arrived before the stream died is still shown"),
            check(SETTLING_PANELS.filter((p) => p !== "retention"), "nothing is left waiting once the read is over"),
        ],
    },
    {
        id: "S18",
        rule: "G16",
        startEventId: EVENT_A,
        // A dropped connection is picked up where it left off; a restart is a
        // new read and must ask for the stream from the beginning.
        steps: [
            fin(FIN_A, 21),
            ret(RET_A, 47),
            { op: "transportError" },
            { op: "assertOpen", asks: "continues", note: "the reconnect resumes from the newest revision held" },
            check(["earnings", "retention"], "and nothing on screen was disturbed by it"),
            { op: "reconnect" },
            { op: "assertOpen", asks: "fresh", note: "a restart asks for the stream from the beginning" },
        ],
    },
    {
        id: "S19",
        rule: "G17",
        startEventId: EVENT_A,
        // A refusal is about one attempt, not about the section forever: after a
        // resume the backend may well produce what it could not produce before.
        steps: [
            { op: "msg", body: { section: "demographics", error: "upstream timeout" } },
            check(["demographics"], "the refused section settles"),
            demo(DEMO_A, 22),
            check(["demographics"], "and a later delivery of that section replaces the refusal"),
        ],
    },
    // --- scenarios where two rules have to hold at once ------------------
    //
    // Everything above can be read as one requirement per scenario. These
    // cannot: each one is a situation where the obvious way to satisfy one rule
    // breaks another, so the candidate needs a design that answers both rather
    // than two independent pieces of code.
    {
        id: "S21",
        rule: "G9",
        startEventId: EVENT_A,
        // The end of the stream is a frame like any other, so a retired
        // connection cannot announce it. A client that treats completion as a
        // fact about itself rather than about the read in progress settles
        // panels that the current read has not finished with.
        steps: [
            fin(FIN_A, 21),
            ret(RET_A, 22),
            { op: "reconnect" },
            fin(FIN_B, 31),
            { op: "staleMsg", body: { section: "__complete__" } },
            check(
                ["earnings", "retention", "device", "demographics"],
                "a terminal frame read on a retired connection settles nothing"
            ),
        ],
    },
    {
        id: "S22",
        rule: "G4",
        startEventId: EVENT_A,
        // Completion belongs to one read. Asking for a fresh one afterwards has
        // to put back the panels that were closed out, or the second read can
        // never fill in what the first one missed.
        steps: [
            fin(FIN_A, 21),
            complete,
            check(["earnings", "retention"], "the read ended: earnings holds, retention was closed out"),
            { op: "reconnect" },
            check(ALL_PANELS, "a fresh read holds nothing, so every panel is waiting again"),
            fin(FIN_B, 31),
            check(["earnings", "retention"], "and the new read's frames are applied"),
        ],
    },
    {
        id: "S23",
        rule: "G16",
        startEventId: EVENT_A,
        // Where a resume continues from is a fact about the dashboard, not
        // about the wire. A frame read on a retired connection never reached a
        // panel, so it is not a place the client can resume from — and a client
        // that notes the revision before it checks the connection asks the
        // backend to skip everything in between.
        steps: [
            fin(FIN_A, 21),
            { op: "reconnect" },
            fin(FIN_B, 31),
            { op: "staleMsg", body: { section: "financials", data: FIN_POISON, revision: 99 } },
            check(["earnings"], "the late frame from the retired connection changed nothing"),
            { op: "transportError" },
            { op: "assertOpen", asks: "continues", note: "the resume continues from the revision on screen" },
            check(["earnings"], "and the reconnect disturbed nothing"),
        ],
    },
    {
        id: "S24",
        rule: "G16",
        startEventId: EVENT_A,
        // Same rule from the other side: a frame that carried nothing to show
        // was not applied either, whatever revision it announced, so it cannot
        // move the resume point.
        //
        // The frame names a section this client knows and carries a revision
        // well ahead of anything on screen, and no payload and no error. There
        // is nothing in it for a panel, so there is nothing in it to resume
        // from — a client that notes the number as it decodes the frame and
        // decides what to do with the frame afterwards asks the backend to skip
        // every section between.
        steps: [
            fin(FIN_A, 21),
            { op: "msg", body: { section: "retention", revision: 88 } },
            { op: "transportError" },
            { op: "assertOpen", asks: "continues", note: "an empty frame does not move the resume point" },
            check(["earnings"], "and nothing on screen moved"),
        ],
    },
    {
        id: "S53",
        rule: "G16",
        startEventId: EVENT_A,
        // And the third frame that announces a revision without leaving anything
        // behind: a refusal. The backend got as far as this section and says so,
        // which makes the number tempting — but the panel has nothing, and the
        // whole reason for re-opening is to get another chance at it. Resuming
        // past it asks the backend never to send it again.
        //
        // The section is one the analytics query cannot answer for, so nothing
        // else can quietly fill the hole and hide the mistake.
        steps: [
            fin(FIN_A, 21),
            { op: "msg", body: { section: "retention", error: "gel: context deadline exceeded", revision: 88 } },
            check(["retention"], "the refused section settles with nothing to show"),
            { op: "transportError" },
            { op: "assertOpen", asks: "continues", note: "a refusal is not a place to resume from" },
            check(["earnings"], "and nothing on screen moved"),
        ],
    },
    {
        id: "S25",
        rule: "G17",
        startEventId: EVENT_A,
        // A refusal is one attempt's answer, and the resumed read is the next
        // attempt. It will deliver the section at whatever revision the backend
        // produced it at, which has nothing to do with how far the rest of the
        // stream has got.
        steps: [
            fin(FIN_A, 47),
            { op: "msg", body: { section: "demographics", error: "upstream timeout" } },
            check(["demographics", "earnings"], "the refused section settles and earnings is untouched"),
            // Deliberately no assertion about the resume point here: S18, S23
            // and S24 own that observable, and keeping it out of this scenario
            // is what lets a candidate with no resume point at all fail G16
            // alone rather than reading as a failure of this rule too.
            { op: "transportError" },
            demo(DEMO_A, 12),
            check(["demographics", "earnings"], "the section refused before the drop arrives after it"),
        ],
    },
    {
        id: "S26",
        rule: "G14",
        startEventId: EVENT_A,
        // The two halves of the revision rule, on one connection, at the same
        // two numbers: a section that holds a newer value refuses both, and a
        // section that holds nothing accepts either. A single stream-wide
        // watermark cannot produce both answers.
        steps: [
            fin(FIN_A, 47),
            { op: "transportError" },
            fin(FIN_B, 30),
            demo(DEMO_A, 12),
            check(
                ["earnings", "demographics"],
                "a replay loses to the value held, and the same revisions win where nothing is held"
            ),
        ],
    },
    // --- the cross product ------------------------------------------------
    //
    // The scenarios above name a situation each. These take the product of the
    // dimensions instead of the list of them: what kind of frame it is (payload,
    // refusal, terminal, unreadable, empty) crossed with which connection read
    // it (current, retired, stopped, another event's) crossed with what the
    // section it names already holds (nothing, a value, a refusal) crossed with
    // how its revision compares to what is on screen.
    //
    // Most of the cells are situations a solver would not think to test but the
    // prompt still decides, and each is a place where a design that handles one
        // dimension per code path gives the wrong answer. Reward is all-or-nothing,
        // so breadth here costs nothing and adds difficulty, provided every cell
        // is derivable, which is the note attached to each.
    {
        id: "S27",
        rule: "G9",
        startEventId: EVENT_A,
        // Refusal crossed with a retired connection. "A frame read on a retired
        // connection must never reach a panel" does not exempt the frames that
        // are not payloads; a client that settles sections from its error path
        // before it asks which connection spoke refuses a section on the word of
        // a read that is over.
        steps: [
            fin(FIN_A, 21),
            { op: "reconnect" },
            fin(FIN_B, 31),
            { op: "staleMsg", body: { section: "retention", error: "upstream timeout" } },
            check(
                ["earnings", "retention"],
                "a refusal read on a retired connection settles nothing"
            ),
        ],
    },
    {
        id: "S28",
        rule: "G10",
        startEventId: EVENT_A,
        // Terminal frame crossed with a stopped read. "Stopping means nothing
        // further lands" — including the one frame that would otherwise stop
        // every remaining panel from waiting.
        steps: [
            fin(FIN_A, 21),
            { op: "stop" },
            complete,
            check(
                ["earnings", "retention", "device", "demographics"],
                "the terminal frame arrives after a stop and settles nothing"
            ),
        ],
    },
    {
        id: "S29",
        rule: "G11",
        startEventId: EVENT_A,
        // Revision ordering crossed with a change of event. Revisions are the
        // backend's count within one read; the new event's first frame is news
        // however low its number, because "changing event clears the old
        // figures" leaves nothing for it to be older than. A client that keeps
        // one watermark across the change ignores the whole new dashboard.
        steps: [
            fin(FIN_A, 47),
            ret(RET_A, 48),
            { op: "navigate", eventId: EVENT_B },
            check(["earnings", "retention"], "the previous event's figures are gone"),
            fin(FIN_B, 12),
            check(
                ["earnings", "retention"],
                "the new event's first frame is applied however low its revision"
            ),
        ],
    },
    {
        id: "S30",
        rule: "G15",
        startEventId: EVENT_A,
        // Giving up crossed with a section that was already refused. Ending the
        // read has to stop the waiting without rewriting what the read already
        // established: the refusal was an answer, and a give-up path that
        // rebuilds the settled set from scratch loses it.
        steps: [
            fin(FIN_A, 21),
            { op: "msg", body: { section: "demographics", error: "upstream timeout" } },
            { op: "transportDies" },
            check(["earnings", "demographics"], "what arrived stays and the refusal stays refused"),
            check(
                SETTLING_PANELS.filter((p) => p !== "demographics"),
                "and no panel is left waiting for a read that is over"
            ),
        ],
    },
    {
        id: "S31",
        rule: "G9",
        startEventId: EVENT_A,
        // An unreadable frame crossed with a retired connection: two reasons to
        // drop one frame, and neither may take the live read down with it. A
        // client that decodes before it checks the connection throws in the
        // wrong generation's callback.
        steps: [
            fin(FIN_A, 21),
            { op: "reconnect" },
            fin(FIN_B, 31),
            { op: "staleMsg", raw: "{ this will not parse" },
            check(["earnings"], "an unreadable frame on a retired connection changes nothing"),
            ret(RET_A, 32),
            check(["earnings", "retention"], "and the live read is still working"),
        ],
    },
    {
        id: "S32",
        rule: "G17",
        startEventId: EVENT_A,
        // A refusal crossed with completion crossed with a restart. The refusal
        // survives the end of the read, and then stops existing at the start of
        // the next one: "a restart holds nothing" is about everything the
        // dashboard was told, not only the figures it was given.
        steps: [
            { op: "msg", body: { section: "demographics", error: "upstream timeout" } },
            fin(FIN_A, 21),
            complete,
            check(["demographics", "earnings"], "the read ended with demographics refused"),
            { op: "reconnect" },
            check(ALL_PANELS, "a fresh read holds neither the figures nor the refusal"),
            demo(DEMO_A, 12),
            check(["demographics"], "and the new read delivers the section that was refused"),
        ],
    },
    {
        id: "S33",
        rule: "G14",
        startEventId: EVENT_A,
        // Redelivery crossed with revision ordering, on the resumed read that
        // produces both. The same revision arrives twice carrying two different
        // payloads: the first is the frame already applied, the second is not
        // newer either. Recognising a replay by comparing payloads answers the
        // first and gets the second wrong.
        steps: [
            fin(FIN_A, 21),
            { op: "transportError" },
            fin(FIN_A, 21),
            check(["earnings"], "the resume replays the frame on screen and nothing changes"),
            fin(FIN_B, 21),
            check(["earnings"], "a different payload at the revision on screen is not newer either"),
            fin(FIN_B, 22),
            check(["earnings"], "and the first frame past it wins"),
        ],
    },
    {
        id: "S34",
        rule: "G16",
        startEventId: EVENT_A,
        // A resume point crossed with a stop. A restart asks from the beginning
        // because it holds nothing, and a stop before it does not change that:
        // a client that remembers the revisions of a read it has already thrown
        // away asks the backend to skip the sections it just discarded.
        steps: [
            fin(FIN_A, 21),
            ret(RET_A, 22),
            { op: "stop" },
            { op: "reconnect" },
            check(ALL_PANELS, "a restart after a stop holds nothing"),
            { op: "assertOpen", asks: "fresh", note: "so it asks for the stream from the beginning" },
        ],
    },
    {
        id: "S35",
        rule: "G9",
        startEventId: EVENT_A,
        // The retired connection crossed with a section the new read has not
        // reached. This is the cell that catches the guard everyone writes
        // instead of the one the prompt asks for: dropping a late frame because
        // the panel already holds something newer answers S9 and fails here,
        // where the panel holds nothing at all and the late frame announces the
        // highest revision in the scenario. What makes it droppable is which
        // connection read it, and nothing else.
        steps: [
            fin(FIN_A, 21),
            ret(RET_A, 22),
            { op: "reconnect" },
            fin(FIN_B, 31),
            { op: "staleMsg", body: { section: "retention", data: RET_POISON, revision: 99 } },
            check(
                ["earnings", "retention"],
                "a late frame for a section the new read has not reached is still dropped"
            ),
        ],
    },
    {
        id: "S13",
        rule: "G13",
        signedOut: true,
        startEventId: EVENT_A,
        steps: [check(ALL_PANELS, "signed out: no connection, no crash")],
    },
    // --- what the browser kept ---------------------------------------------
    //
    // A dashboard the host has already looked at is kept per event, and picked
    // up on the way in. That single capability reaches into everything above it:
    // where the first connection starts, what a change of event puts on screen,
    // what a restart throws away, and which of a read's conclusions are facts
    // about the figures rather than about the read.
    {
        id: "S36",
        rule: "G18",
        startEventId: EVENT_A,
        stored: [
            storedUnstamped(EVENT_A, 1772000000, {
                financials: { revision: 21, data: FIN_A },
                retention: { revision: 22, data: RET_A },
            }),
        ],
        steps: [
            check(["earnings", "retention"], "the kept figures are on screen before the stream has said anything"),
            check(["device", "demographics"], "and the sections it does not hold are waiting on the stream"),
            fin(FIN_B, 23),
            check(["earnings"], "a newer frame replaces a kept figure"),
        ],
    },
    {
        id: "S37",
        rule: "G19",
        startEventId: EVENT_A,
        // Where a connection starts is a fact about what the dashboard is
        // showing. That was true of a reconnect and it is no less true of the
        // first connection of all, which is the case a client written around
        // "reconnects resume, first reads do not" gets wrong.
        stored: [
            storedUnstamped(EVENT_A, 1772000000, {
                financials: { revision: 21, data: FIN_A },
                retention: { revision: 47, data: RET_A },
            }),
        ],
        steps: [
            { op: "assertOpen", asks: "continues", note: "the first connection continues from the kept figures" },
            check(["earnings", "retention"], "which are what is on screen"),
        ],
    },
    {
        id: "S38",
        rule: "G20",
        startEventId: EVENT_A,
        // A record written by the release before this one. Its figures are as
        // good as they ever were; its revisions do not exist, and no revision
        // can be invented for it, because a resume point names a place in the
        // backend's own numbering.
        stored: [storedPrevious(EVENT_A, 1768520411, { financials: FIN_A, retention: RET_A })],
        steps: [
            check(["earnings", "retention"], "the older record's figures are restored"),
            check(["device", "demographics"], "and it says nothing about the sections it does not hold"),
            { op: "assertOpen", asks: "fresh", note: "a record with no revisions is not a place to resume from" },
            fin(FIN_B, 3),
            check(["earnings"], "a restored figure with no revision is replaced by any frame for it"),
        ],
    },
    {
        id: "S45",
        rule: "G20",
        startEventId: EVENT_A,
        // The same distinction inside one record that carries revisions: the
        // stream cannot version every section, so an entry may hold a figure
        // and no revision. The resume point comes from the entries that have
        // one, and the entry that does not accepts anything.
        stored: [
            storedUnstamped(EVENT_A, 1772000000, {
                financials: { revision: null, data: FIN_A },
                retention: { revision: 22, data: RET_A },
            }),
        ],
        steps: [
            check(["earnings", "retention"], "both entries are restored"),
            { op: "assertOpen", asks: "continues", note: "the resume point comes from the entry that has one" },
            fin(FIN_B, 4),
            check(["earnings"], "and the entry without one accepts a frame at any revision"),
        ],
    },
    {
        id: "S39",
        rule: "G21",
        startEventId: EVENT_A,
        // A write that ran out of quota half way. Storage is not a place where
        // an exception is an acceptable outcome: the host asked for a dashboard.
        stored: [
            storedRaw(
                snapshotKey(EVENT_A),
                '{"version":2,"eventId":"' +
                    EVENT_A +
                    '","savedAt":1770333190,"sections":{"financials":{"revision":12,"data":{"net":48200,"payment"'
            ),
        ],
        steps: [
            check(ALL_PANELS, "an unreadable record is ignored and the page still loads"),
            { op: "assertOpen", asks: "fresh", note: "with nothing restored, there is nothing to resume from" },
            fin(FIN_A, 21),
            check(["earnings"], "and the stream fills the dashboard normally"),
        ],
    },
    {
        id: "S40",
        rule: "G22",
        startEventId: EVENT_A,
        // One record per event, and this one is not this event's.
        stored: [storedUnstamped(EVENT_B, 1772000000, { financials: { revision: 21, data: FIN_B } })],
        steps: [
            check(ALL_PANELS, "a record kept for another event is not this dashboard's"),
            { op: "assertOpen", asks: "fresh", note: "and is not a place this read can resume from" },
        ],
    },
    {
        id: "S41",
        rule: "G22",
        startEventId: EVENT_A,
        // Changing event crossed with what the browser kept. "Nothing from the
        // previous dashboard stays on screen" is not the same requirement as
        // "the new dashboard starts empty", and a client that clears its state
        // on the way into an event never finds out.
        stored: [
            storedUnstamped(EVENT_B, 1772000000, {
                financials: { revision: 31, data: FIN_B },
                demographics: { revision: 32, data: DEMO_A },
            }),
        ],
        steps: [
            fin(FIN_A, 21),
            check(["earnings", "demographics"], "this event's figures come off the wire"),
            { op: "navigate", eventId: EVENT_B },
            check(["earnings", "demographics"], "and the other event's come out of storage"),
            { op: "assertOpen", asks: "continues", note: "the new event's connection continues from its own record" },
        ],
    },
    {
        id: "S42",
        rule: "G23",
        startEventId: EVENT_A,
        // The writing half. Nothing was seeded here: what comes back after the
        // reload is whatever the client kept while it was reading.
        steps: [
            fin(FIN_A, 21),
            ret(RET_A, 47),
            { op: "reload", note: "the host closes the page and comes back" },
            check(["earnings", "retention"], "a reload comes back to the figures the read had"),
            check(["device", "demographics"], "and the sections it never got are waiting again"),
            { op: "assertOpen", asks: "continues", note: "and the read picks up from what came back" },
        ],
    },
    {
        id: "S43",
        rule: "G24",
        startEventId: EVENT_A,
        // What is worth keeping and what is not. A refusal is one attempt's
        // answer and the end of the stream is one read's conclusion; a reload is
        // a new read, and neither conclusion is its.
        steps: [
            fin(FIN_A, 21),
            { op: "msg", body: { section: "demographics", error: "upstream timeout" } },
            complete,
            check(["earnings", "demographics", "retention"], "the read ended with demographics refused"),
            { op: "reload", note: "the host closes the page and comes back" },
            check(["earnings"], "the figures come back"),
            check(["demographics", "retention", "device"], "the refusal and the ending do not"),
        ],
    },
    // S44 (G25, "a restart discards the stored record") was removed. It was
    // never a rule of its own: the record mirrors what is on screen (G23), a
    // restart clears the screen, so a client that gets G23 right clears the
    // record without being told to. The only implementation the scenario could
    // separate was one that mirrors the screen everywhere except a restart, and
    // nothing in the prompt, the surviving tree or the recordings distinguishes
    // that case, so the rule was removed rather than graded. Deleting a rule
    // beats defending an undiscoverable one.
    // --- the second source -------------------------------------------------
    //
    // The stream computes ten sections and the ordinary analytics query
    // computes three. A panel whose section the read has finished with, and has
    // nothing to show for, is worth a second attempt where a second attempt
    // exists — and is not worth one anywhere else.
    {
        id: "S46",
        rule: "G26",
        startEventId: EVENT_A,
        query: {
            charts: { eligible: true, data: CHARTS_Q },
            demographics: { eligible: true, data: DEMO_Q },
        },
        steps: [
            fin(FIN_A, 21),
            { op: "msg", body: { section: "charts", error: "charts timed out" } },
            check(["engagement"], "a section the stream refused is filled from the analytics query"),
            check(["demographics"], "a section still in flight is left to the stream"),
            check(["earnings"], "and nothing else moved"),
        ],
    },
    {
        id: "S47",
        rule: "G27",
        startEventId: EVENT_A,
        // The asymmetry. Which sections have a second source is not a property
        // of the stream, of the panel or of the section's importance: it is the
        // list of things the query can be asked for.
        query: {
            charts: { eligible: true, data: CHARTS_Q },
            demographics: { eligible: true, data: DEMO_Q },
            revenue: { eligible: true, data: REV_Q },
        },
        steps: [
            fin(FIN_A, 21),
            complete,
            check(["engagement", "demographics"], "the sections the query can answer for are filled in"),
            check(
                ["retention", "device", "timeline", "location", "platform"],
                "the sections it cannot are left exactly as the read left them"
            ),
        ],
    },
    {
        id: "S48",
        rule: "G28",
        startEventId: EVENT_A,
        // The trigger is the read finishing with a section, not the page
        // loading. Standing a queried figure in front of a host while the stream
        // is still computing a fresher one is the flicker this endpoint exists
        // to avoid.
        query: {
            charts: { eligible: true, data: CHARTS_Q },
            demographics: { eligible: true, data: DEMO_Q },
        },
        steps: [
            fin(FIN_A, 21),
            check(["engagement", "demographics"], "the query does not stand in for a section still coming"),
            demo(DEMO_A, 22),
            check(["demographics"], "which the stream then delivers"),
            check(["engagement"], "while charts is still the stream's to produce"),
        ],
    },
    {
        id: "S49",
        rule: "G26",
        startEventId: EVENT_A,
        // Running out of attempts finishes with every section at once, so it
        // reaches the query by the same route a refusal does.
        query: {
            charts: { eligible: true, data: CHARTS_Q },
            demographics: { eligible: true, data: DEMO_Q },
        },
        steps: [
            fin(FIN_A, 21),
            ret(RET_A, 22),
            { op: "transportDies" },
            check(["engagement", "demographics"], "a read that ran out of attempts is a read that is finished"),
            check(["earnings", "retention"], "and what arrived is still shown"),
            check(["device", "timeline"], "and the sections with no second source stop waiting"),
        ],
    },
    {
        id: "S50",
        rule: "G27",
        startEventId: EVENT_A,
        // The query answers, and its answer is that this event has no analytics.
        // A dashboard that shows the figures anyway is showing another event's --
        // which the harness makes true rather than asserting: the document comes
        // back under `EVENT_UNRELATED`'s id, unready and unupdated. That claim
        // used to live only here, and the workspace capture pointed the other
        // way by pairing `eligible:false` with the requested event's own charts.
        query: { charts: { eligible: false, data: CHARTS_Q } },
        steps: [
            fin(FIN_A, 21),
            { op: "msg", body: { section: "charts", error: "charts timed out" } },
            check(["engagement"], "an event with no analytics keeps the failure the stream reported"),
            check(["earnings"], "and nothing else moved"),
        ],
    },
    {
        id: "S51",
        rule: "G29",
        startEventId: EVENT_A,
        // A queried figure crossed with a resume. The query does not version
        // anything, so a figure that came from it names no place in the stream's
        // numbering and cannot move where the next connection starts.
        query: { charts: { eligible: true, data: CHARTS_Q } },
        steps: [
            fin(FIN_A, 21),
            { op: "msg", body: { section: "charts", error: "charts timed out", revision: 88 } },
            check(["engagement"], "the query fills the refused section"),
            { op: "transportError" },
            {
                op: "assertOpen",
                asks: "continues",
                note: "a figure the query supplied is not a place the stream can resume from",
            },
            check(["engagement", "earnings"], "and nothing on screen moved"),
        ],
    },
    {
        id: "S52",
        rule: "G29",
        startEventId: EVENT_A,
        // The other consequence of the same fact: a section showing a figure
        // with no revision beside it is behind on everything, so the stream's own
        // value replaces it however low its number.
        query: { charts: { eligible: true, data: CHARTS_Q } },
        steps: [
            fin(FIN_A, 47),
            { op: "msg", body: { section: "charts", error: "charts timed out" } },
            check(["engagement"], "the query fills it"),
            { op: "transportError" },
            charts(CHARTS_A, 5),
            check(["engagement"], "and the stream's own value replaces it, however it is numbered"),
        ],
    },
    // --- the window the figures are about ----------------------------------
    //
    // Everything above is one event over one window, so the window never had to
    // be said out loud. It is on the query string, both endpoints aggregate over
    // it, and the record the browser keeps names it — which makes it the second
    // half of what identifies a dashboard, beside the event.
    //
    // Three subsystems have to agree about it and they fail separately: what is
    // on screen and what the stream is asked for, what a kept record is a record
    // *of*, and what question the second source is asked.
    {
        id: "S54",
        rule: "G30",
        startEventId: EVENT_A,
        // A window is not a filter over figures already in hand: the figures
        // themselves are aggregates over it. So the previous window's numbers
        // are not this dashboard's, its revisions were counted in a read that is
        // over, and the connection that was carrying them is retired like any
        // other.
        steps: [
            fin(FIN_A, 21),
            ret(RET_A, 22),
            check(["earnings", "retention"], "the whole event's figures are on screen"),
            { op: "range", range: "week", note: "the host asks for the last seven days" },
            check(ALL_PANELS, "the previous window's figures are gone and nothing is settled"),
            { op: "assertOpen", asks: "fresh", note: "and the new window is read from the beginning" },
            fin(FIN_B, 12),
            check(["earnings"], "the new window's first frame is applied however low its revision"),
            { op: "staleMsg", body: { section: "financials", data: FIN_POISON } },
            check(["earnings"], "a late frame from the previous window's connection is dropped"),
        ],
    },
    {
        id: "S55",
        rule: "G31",
        startEventId: EVENT_A,
        // The record follows the screen across the change like it follows it
        // everywhere else, so what it is a record *of* moves too: what comes
        // back on the next page load is the window the host was last looking at,
        // and the read picks up from there as it does after any other load.
        steps: [
            fin(FIN_A, 21),
            { op: "range", range: "day", note: "the host asks for the last twenty-four hours" },
            fin(FIN_B, 31),
            check(["earnings"], "the new window's figure is on screen"),
            { op: "reload", note: "the host closes the page and comes back" },
            check(["earnings"], "and a reload comes back to it"),
            { op: "assertOpen", asks: "continues", note: "continuing from what came back" },
        ],
    },
    {
        id: "S61",
        rule: "G30",
        startEventId: EVENT_A,
        // The previous window's read had finished. That is a conclusion about a
        // question nobody is asking any more: this window has not been read at
        // all yet, so nothing here is settled and nothing here has ended.
        steps: [
            fin(FIN_A, 21),
            complete,
            check(ALL_PANELS, "the whole event's read ended with one figure and the rest given up on"),
            { op: "range", range: "day", note: "the host asks for the last twenty-four hours" },
            check(ALL_PANELS, "the new window is waiting on a read of its own, not finished without one"),
            { op: "assertOpen", asks: "fresh", note: "and that read starts from the beginning" },
            fin(FIN_B, 12),
            check(["earnings"], "and it is this window's figures that fill the panels"),
        ],
    },
    {
        id: "S56",
        rule: "G31",
        startEventId: EVENT_A,
        range: "week",
        // One record per event, and this one holds the whole event's figures
        // while the page is showing seven days of it. The revisions in it are as
        // useless as the figures: they name places in a read that was asking a
        // different question.
        stored: [
            storedStamped(EVENT_A, "event", 1772000000, {
                financials: { revision: 21, data: FIN_A },
                retention: { revision: 22, data: RET_A },
            }),
        ],
        steps: [
            check(ALL_PANELS, "a record kept for another window is not this dashboard's"),
            { op: "assertOpen", asks: "fresh", note: "and is not a place this read can resume from" },
            fin(FIN_B, 12),
            check(["earnings"], "this window's figures come off the stream"),
        ],
    },
    {
        id: "S57",
        rule: "G31",
        startEventId: EVENT_A,
        range: "day",
        // The other side of the same lookup, and the reason it cannot be done by
        // refusing every record that names a window: one that names this one is
        // exactly what a returning host is owed.
        stored: [
            storedStamped(EVENT_A, "day", 1772000000, {
                financials: { revision: 31, data: FIN_A },
                retention: { revision: 47, data: RET_A },
            }),
        ],
        steps: [
            check(["earnings", "retention"], "the record kept for this window is on screen before the stream speaks"),
            check(["device", "demographics"], "and the sections it does not hold are waiting on the stream"),
            { op: "assertOpen", asks: "continues", note: "and this read continues from what it holds" },
        ],
    },
    {
        id: "S58",
        rule: "G32",
        startEventId: EVENT_A,
        range: "week",
        // A record from before the dashboard had a choice of window. It names
        // none, which is not the same as fitting any: every request that wrote
        // it covered the whole event.
        stored: [
            storedUnstamped(EVENT_A, 1772000000, {
                financials: { revision: 21, data: FIN_A },
                retention: { revision: 22, data: RET_A },
            }),
        ],
        steps: [
            check(ALL_PANELS, "a record that names no window is the whole event's, not this one's"),
            { op: "assertOpen", asks: "fresh", note: "so there is nothing here to resume from either" },
            fin(FIN_B, 12),
            check(["earnings"], "and this window's figures come off the stream"),
        ],
    },
    {
        id: "S59",
        rule: "G33",
        startEventId: EVENT_A,
        range: "week",
        // The second source is asked a question, and half of that question is
        // the window. An answer aggregated over the whole event would be a
        // number of a different size standing between figures that are all
        // seven days old.
        query: { charts: { eligible: true, data: CHARTS_Q } },
        steps: [
            fin(FIN_A, 21),
            { op: "msg", body: { section: "charts", error: "charts timed out" } },
            check(["engagement"], "the refused section is filled from the analytics query"),
            { op: "assertQuery", section: "charts", note: "which was asked over the window on screen" },
        ],
    },
    {
        id: "S60",
        rule: "G33",
        startEventId: EVENT_A,
        // The same section, given up on twice, over two windows. Whatever the
        // client remembers about having asked already is a fact about a
        // dashboard, and the second one is not the same dashboard.
        query: { demographics: { eligible: true, data: DEMO_Q } },
        steps: [
            { op: "msg", body: { section: "demographics", error: "upstream timeout" } },
            check(["demographics"], "the query fills the section the stream refused"),
            { op: "assertQuery", section: "demographics", note: "over the whole event, which is what is on screen" },
            { op: "range", range: "day", note: "the host asks for the last twenty-four hours" },
            check(["demographics"], "the previous window's answer goes with the rest"),
            { op: "msg", body: { section: "demographics", error: "upstream timeout" } },
            check(["demographics"], "and this window's read gives up on the section too"),
            { op: "assertQuery", section: "demographics", note: "so it is asked again, over the new window" },
        ],
    },
];
