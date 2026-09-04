// Graded spec. Test names carry their own classification:
//   absent::*  the capability is simply not there -- a wrong answer, graded 0.0
//   seam::*    the harness could not drive the capability -- a harness failure
//   rule::*    a failure here is a wrong answer
// `run.mjs` reads the distinction out of the reporter output.
//
// The absent/seam split matters more than it looks. A submission that never
// opens a connection, or whose fold does nothing with a frame that arrives, has
// answered the question wrongly; it has not defeated the grader. Reporting that
// as a harness failure makes a genuine zero read as a broken verifier, which is
// the one result that cannot be told apart from a hard task from the outside.
// Only the control classification stays a harness failure, because that is the
// one place the harness has to guess at the candidate's shape.

import { writeFileSync } from "node:fs";
import { join } from "node:path";

import { act, cleanup } from "@testing-library/react";
import { unstable_createAdapterProvider } from "nuqs/adapters/custom";
import React from "react";
import { MemoryRouter, Route, Routes, useNavigate, useSearchParams } from "react-router-dom";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("@microsoft/fetch-event-source", async () => {
    const h = await import("./harness");
    return {
        fetchEventSource: (url: string, init: any) => h.mockFetchEventSource(url, init),
        EventStreamContentType: "text/event-stream",
    };
});

vi.mock("@data/hooks/user/useAuthToken", async () => {
    const h = await import("./harness");
    return { useAuthToken: () => h.mockUseAuthToken() };
});

vi.mock("@data/hooks/event/useEvent", async () => {
    const h = await import("./harness");
    return { useEvent: (eventId?: string) => h.mockUseEvent(eventId) };
});

// The app's axios instance is where the network is, so this is the same kind of
// seam as the SSE mock above: it replaces the transport, not any caller of it.
vi.mock("@data/sendRequest", async () => {
    const h = await import("./harness");
    return {
        sendRequest: h.mockSendRequest,
        isBackendError: (error: unknown) => h.mockIsBackendError(error),
    };
});

import * as CheckInStatsMod from "@pages/host/analytics-page/sections/CheckInStats";
import * as EngagementMod from "@pages/host/analytics-page/sections/Engagement";
import * as CheckInTimelineMod from "@pages/host/analytics-page/sections/CheckInTimeline";
import * as DemographicsMod from "@pages/host/analytics-page/sections/Demographics";
import * as DeviceBreakdownMod from "@pages/host/analytics-page/sections/DeviceBreakdown";
import * as EarningsMod from "@pages/host/analytics-page/sections/Earnings";
import * as LocationBreakdownMod from "@pages/host/analytics-page/sections/LocationBreakdown";
import * as PlatformEngagementMod from "@pages/host/analytics-page/sections/PlatformEngagement";
import * as RetentionMod from "@pages/host/analytics-page/sections/Retention";
import { AnalyticsContext, AnalyticsProvider } from "@pages/host/analytics-page/context/AnalyticsContext";

import {
    ambient,
    connections,
    deliver,
    discoverControls,
    exhaustTransport,
    failTransport,
    currentConnection,
    lastQueryCallFor,
    liveConnection,
    openPending,
    pickComponent,
    readPanel,
    registerEvent,
    render,
    resetConnections,
    resetStorage,
    setQueryScenario,
    settle,
    resumeAsked,
    supersededConnection,
    urlCarries,
} from "./harness";
import { expectedPanel, fold, resumePoint } from "./model";
import {
    DEFAULT_RANGE,
    EVENT_A,
    EVENT_B,
    FIN_A,
    FIN_B,
    PanelName,
    RANGE_BUCKETS,
    RANGES,
    SCENARIOS,
    Scenario,
    ScenarioRange,
    scenarioRevisions,
} from "./scenarios";

const Earnings = pickComponent(EarningsMod as any, "EarningsSection", "sections/Earnings");
const CheckIn = pickComponent(CheckInStatsMod as any, "CheckInStatsSection", "sections/CheckInStats");
const Retention = pickComponent(RetentionMod as any, "RetentionSection", "sections/Retention");
const Device = pickComponent(DeviceBreakdownMod as any, "DeviceBreakdownSection", "sections/DeviceBreakdown");
const Demographics = pickComponent(DemographicsMod as any, "GenderDistributionSection", "sections/Demographics");
const Timeline = pickComponent(CheckInTimelineMod as any, "CheckInTimelineSection", "sections/CheckInTimeline");
const Location = pickComponent(LocationBreakdownMod as any, "LocationBreakdownSection", "sections/LocationBreakdown");
const Platform = pickComponent(
    PlatformEngagementMod as any,
    "PlatformEngagementSection",
    "sections/PlatformEngagement"
);
const Engagement = pickComponent(EngagementMod as any, "EngagementSection", "sections/Engagement");

registerEvent(EVENT_A);
registerEvent(EVENT_B);

const ctxRef: { current: any } = { current: null };
const navRef: { current: ((to: string) => void) | null } = { current: null };

const Probe = () => {
    ctxRef.current = React.useContext(AnalyticsContext);
    navRef.current = useNavigate();
    return null;
};

const Panels = () => (
    <>
        <div data-vpanel="earnings">
            <Earnings />
        </div>
        <div data-vpanel="checkin">
            <CheckIn />
        </div>
        <div data-vpanel="retention">
            <Retention />
        </div>
        <div data-vpanel="device">
            <Device />
        </div>
        <div data-vpanel="demographics">
            <Demographics />
        </div>
        <div data-vpanel="timeline">
            <Timeline />
        </div>
        <div data-vpanel="location">
            <Location />
        </div>
        <div data-vpanel="platform">
            <Platform />
        </div>
        <div data-vpanel="engagement">
            <Engagement />
        </div>
    </>
);

// Every mount is a page load, and the third seam is the one that says so.
//
// `useEndpoint` -- the workspace's own fetch hook, and what `useEventAnalytics`
// is built out of -- caches through SWR, and SWR's cache is module state. It
// therefore outlives a render, outlives `cleanup()`, and outlives a scenario, in
// exactly the way `localStorage` and the connection list would if `resetStorage`
// and `resetConnections` did not exist above.
//
// Left alone it fails correct work in a very specific shape: a submission that
// reaches the analytics query through the app's own hook asks the transport once
// per (event, section) for the whole run -- six requests across fifty-odd
// scenarios -- and every scenario after the first is served the first one's
// answer, which is whatever that scenario's table happened to say. The submission
// is right and the grader disagrees, which is the one failure this file exists
// not to have. Measured against the rule set as it stood: the same reference
// fold, with the backfill routed through `useEventAnalytics` instead of
// `sendRequest`, went from 54 of 54 to 49 of 54 on the cache alone, and the five
// were G26, G27 and G29 -- the whole of the second source.
//
// A fresh provider per mount gives SWR the cache a real browser gives it, which
// is an empty one. It is not a concession: it makes the harness match the thing
// it is modelling.
// One cache per mount, and the identity is stable so that a re-render inside a
// page load is not mistaken for another one and handed a fresh cache.
const swrProvider = () => new Map();

/**
 * nuqs, reading the router the tree is mounted in.
 *
 * The workspace reads the query string two ways -- react-router's own
 * `useSearchParams` and nuqs' `useQueryState`, both already in use in this tree
 * -- and a solver may reach for either. nuqs' own adapters read
 * `window.location` directly, which a `MemoryRouter` never touches, and its
 * testing adapter takes a fixed string that a navigation does not move. Either
 * would fail a correct client for the library it picked, so nuqs is given the
 * router as its source instead: both readings then answer from one location, and
 * one navigation moves both.
 */
const NuqsAdapter = unstable_createAdapterProvider(() => {
    const [searchParams, setSearchParams] = useSearchParams();
    return {
        searchParams,
        updateUrl: (search: URLSearchParams) => setSearchParams(search, { replace: true }),
    };
});

/**
 * The query string a page load carries. A window the page is not being asked
 * about is simply absent, which is the state every scenario that predates the
 * window loads in.
 */
function searchFor(range: ScenarioRange): string {
    return range === DEFAULT_RANGE ? "" : `?range=${range}`;
}

function Tree({ eventId, search }: { eventId: string; search: string }) {
    return (
        <SWRConfig value={{ provider: swrProvider }}>
            <MemoryRouter initialEntries={[`/host/${eventId}/analytics${search}`]}>
                {/* The tree reads the query string two ways -- react-router's own
                    `useSearchParams` and nuqs' `useQueryState`, both of which are
                    already in use in the workspace -- so nuqs is mounted on the
                    router rather than on a fixture of its own. Both then answer
                    from one location, and a navigation moves both. A solver is
                    not graded on which of the two libraries it reached for. */}
                <NuqsAdapter>
                    <Routes>
                        <Route
                            path="/host/:eventId/analytics"
                            element={
                                <AnalyticsProvider>
                                    <Probe />
                                    <Panels />
                                </AnalyticsProvider>
                            }
                        />
                    </Routes>
                </NuqsAdapter>
            </MemoryRouter>
        </SWRConfig>
    );
}

async function mount(eventId: string, range: ScenarioRange = DEFAULT_RANGE) {
    let result: ReturnType<typeof render> | undefined;
    await act(async () => {
        result = render(<Tree eventId={eventId} search={searchFor(range)} />);
    });
    await settle();
    await openPending();
    return {
        ctxRef,
        unmount: () => result?.unmount(),
    };
}

// `globals: false` means testing-library never registers its own auto-cleanup,
// so trees would stack up in the document and panel probes would read a stale
// render. Clean explicitly.
beforeEach(() => {
    cleanup();
    ambient.token = "verifier-token";
    ctxRef.current = null;
    navRef.current = null;
    resetConnections();
    // Storage outlives a render, so a record a previous test's candidate wrote
    // would stand this one's dashboard up before its first frame.
    resetStorage();
    setQueryScenario({ id: "", rule: "", startEventId: EVENT_A, steps: [] }, EVENT_A);
    vi.useFakeTimers({
        toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date", "performance"],
    });
    vi.setSystemTime(new Date("2026-03-04T09:00:00.000Z"));
});

afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

// --- reachability -------------------------------------------------------

describe("reachability", () => {
    test("absent::the tree opens a stream once an event and a token are present", async () => {
        const m = await mount(EVENT_A);
        expect(connections.length, "no connection was opened after mount").toBeGreaterThan(0);
        expect(ctxRef.current, "the analytics context is not populated").toBeTruthy();
        m.unmount();
    });

    test("absent::messages delivered on the open connection reach a panel", async () => {
        await mount(EVENT_A);
        await deliver(liveConnection(), { body: { section: "financials", data: FIN_A } });
        const view = readPanel("earnings");
        expect(view, "delivering a financials frame changed nothing in the DOM").toEqual({
            kind: "data",
            values: { amount: "$4075.00" },
        });
    });

    test("seam::the context exposes callable controls", async () => {
        const controls = await resolveControls();
        console.log("CONTROLS " + JSON.stringify(controls));
        expect(Object.keys(controls.classified).length, "the context exposes no callable controls").toBeGreaterThan(0);
    });
});

// Controls are classified once and reused. Discovery mounts and unmounts its own
// throwaway trees, so it must run before a scenario's own mount.
let controlCache: Awaited<ReturnType<typeof discoverControls>> | null = null;

async function resolveControls() {
    if (controlCache) return controlCache;
    const previousToken = ambient.token;
    ambient.token = "verifier-token";
    controlCache = await discoverControls(
        async () => {
            // Each probe is its own page load: nothing a previous probe kept may
            // be on screen before its first frame.
            resetStorage();
            const m = await mount(EVENT_A);
            return { ctxRef: m.ctxRef, unmount: () => { m.unmount(); cleanup(); } };
        },
        { first: { section: "financials", data: FIN_A }, second: { section: "financials", data: FIN_B } },
        () => {
            const v = readPanel("earnings");
            return v.kind === "data" ? v.values.amount : undefined;
        }
    );
    cleanup();
    resetConnections();
    resetStorage();
    ambient.token = previousToken;
    return controlCache;
}

// --- graded rules -------------------------------------------------------

async function runScenario(sc: Scenario) {
    const needsControls = sc.steps.some((s) => s.op === "reconnect" || s.op === "stop");
    // Discovery mounts and drives throwaway trees of its own, so it has to run
    // before this scenario's storage is seeded: whatever those trees kept would
    // otherwise still be there.
    const controls = needsControls ? await resolveControls() : undefined;

    ambient.token = sc.signedOut ? undefined : "verifier-token";
    cleanup();
    resetConnections();
    resetStorage(sc.stored);
    let viewing = sc.startEventId;
    let showing: ScenarioRange = sc.range ?? DEFAULT_RANGE;
    setQueryScenario(sc, viewing);
    let tree = await mount(sc.startEventId, showing);

    for (let i = 0; i < sc.steps.length; i++) {
        const step = sc.steps[i];
        switch (step.op) {
            case "msg":
                await deliver(currentConnection(), step);
                await openPending();
                break;
            case "staleMsg":
                await deliver(supersededConnection(), step);
                break;
            case "reconnect": {
                const name = controls?.reconnect;
                expect(name, "no control on the analytics context re-opens the stream").toBeTruthy();
                await act(async () => {
                    ctxRef.current?.[name!]?.();
                });
                await settle();
                await openPending();
                break;
            }
            case "stop": {
                const name = controls?.halt;
                expect(name, "no control on the analytics context stops the stream").toBeTruthy();
                await act(async () => {
                    ctxRef.current?.[name!]?.();
                });
                await settle();
                break;
            }
            case "transportError":
                await failTransport();
                await openPending();
                break;
            case "transportDies": {
                const outcome = await exhaustTransport();
                expect(
                    outcome.dead,
                    `${sc.id} step ${i}: the client is still trying to read after ${outcome.rounds} failed re-opens`
                ).toBe(true);
                break;
            }
            case "assertOpen": {
                const conn = currentConnection();
                expect(conn, `${sc.id} step ${i}: no connection to inspect`).toBeTruthy();
                const asked = conn?.url ?? "";
                const state = fold(sc, i);
                // Whatever else this read is asking for, it is not asking about a
                // window that is not on screen. Stated as a negative on purpose:
                // the bucket counts are the dashboard's own, and a client that
                // brings its own table is not wrong, so what is graded is that
                // the request is not another window's -- which is what a client
                // that rebuilt nothing when the window moved would send.
                for (const other of RANGES) {
                    if (other === state.range) continue;
                    expect(
                        urlCarries(asked, String(RANGE_BUCKETS[other])),
                        `${sc.id} step ${i} ${step.note}: found the ${other} window's ` +
                            `${RANGE_BUCKETS[other]} buckets in ${asked}`
                    ).toBe(false);
                }
                if (step.asks === "continues") {
                    const point = resumePoint(state);
                    expect(point, `${sc.id} step ${i}: nothing on screen to resume from`).not.toBeNull();
                    // "The newest revision you hold" and "the first revision you
                    // do not hold" are the same request written two ways, and
                    // which one an endpoint wants is a convention the prompt
                    // does not state. Accept both: what is graded is that the
                    // point comes from the displayed state, not an off-by-one.
                    expect(
                        urlCarries(asked, String(point)) || urlCarries(asked, String((point as number) + 1)),
                        `${sc.id} step ${i} ${step.note}: expected revision ${point} in ${asked}`
                    ).toBe(true);
                } else {
                    // A read with nothing to continue from asks for nothing.
                    // Both halves matter: a client may invent a revision the
                    // scenario never names (a migrated record given a made-up
                    // number), or carry one it has been given and disowned.
                    expect(
                        resumeAsked(asked),
                        `${sc.id} step ${i} ${step.note}: asked to continue after a revision in ${asked}`
                    ).toBeNull();
                    for (const revision of scenarioRevisions(sc)) {
                        for (const value of [revision, revision + 1]) {
                            expect(
                                urlCarries(asked, String(value)),
                                `${sc.id} step ${i} ${step.note}: found revision ${value} in ${asked}`
                            ).toBe(false);
                        }
                    }
                }
                break;
            }
            case "assertQuery": {
                const state = fold(sc, i);
                const call = lastQueryCallFor(step.section);
                expect(
                    call,
                    `${sc.id} step ${i} ${step.note}: the analytics query was never asked about ${step.section}`
                ).toBeTruthy();
                const values = call?.values ?? [];
                // The question the second source was asked has to be the
                // question the stream is being asked: same event, same window.
                // Checked against the candidate's *own* open request rather than
                // against the dashboard's bucket table, so a client that brings
                // its own idea of how finely a week is cut is not wrong — what
                // is graded is that both endpoints were asked the same thing.
                // A call that carries nothing but the event and the section is
                // a call with no window on it, which the endpoint answers about
                // the whole event.
                const askedOfStream = new Set(
                    Array.from(new URLSearchParams((currentConnection()?.url ?? "").split("?")[1] ?? "").values())
                );
                askedOfStream.delete(viewing);
                const shared = values.filter((value) => value !== step.section && askedOfStream.has(value));
                expect(
                    shared.length > 0,
                    `${sc.id} step ${i} ${step.note}: the query was asked about ${step.section} ` +
                        `with none of the window the stream was asked for — ` +
                        `${JSON.stringify(values)} against ${JSON.stringify([...askedOfStream])}`
                ).toBe(true);
                for (const other of RANGES) {
                    if (other === state.range) continue;
                    expect(
                        values.includes(String(RANGE_BUCKETS[other])),
                        `${sc.id} step ${i} ${step.note}: found the ${other} window's ` +
                            `${RANGE_BUCKETS[other]} buckets among ${JSON.stringify(values)}`
                    ).toBe(false);
                }
                break;
            }
            case "navigate":
                viewing = step.eventId;
                setQueryScenario(sc, viewing);
                await act(async () => {
                    navRef.current?.(`/host/${step.eventId}/analytics${searchFor(showing)}`);
                });
                await settle();
                await openPending();
                break;
            case "range":
                // The host picks another window. This is a navigation on the
                // same page: nothing is torn down, and what the browser has
                // kept is left exactly as the client wrote it.
                showing = step.range;
                await act(async () => {
                    navRef.current?.(`/host/${viewing}/analytics${searchFor(showing)}`);
                });
                await settle();
                await openPending();
                break;
            case "reload": {
                // Everything in the process goes; the browser's storage stays
                // exactly as the candidate left it. This is a page load, not a
                // re-render, so the connection list starts over too.
                tree.unmount();
                cleanup();
                resetConnections();
                ctxRef.current = null;
                navRef.current = null;
                tree = await mount(viewing, showing);
                break;
            }
            case "assert": {
                const state = fold(sc, i);
                for (const panel of step.panels as PanelName[]) {
                    expect(readPanel(panel), `${sc.id} step ${i} [${panel}] ${step.note}`).toEqual(
                        expectedPanel(state, panel)
                    );
                }
                break;
            }
        }
    }
}

// Graded tests that are written out by hand rather than driven from SCENARIOS.
// Keep this equal to the number of `rule::` tests below the scenario loop.
const HANDWRITTEN_RULES = 1;

// The census of what this suite intends to grade, written before a single test
// runs and before any candidate module is touched. run.mjs compares it to what
// the reporter actually accounted for and calls any shortfall a harness failure.
// Without it, a suite that registered nine of its scenarios and passed them all
// would report a clean 1.0 -- a fake pass being far worse than a fake failure,
// since it certifies a wrong answer instead of merely wasting a rollout.
writeFileSync(
    join(process.env.VERIFY_OUT_DIR ?? "/tmp/verify-out", "expected-rules.json"),
    JSON.stringify({ expected_rules: SCENARIOS.length + HANDWRITTEN_RULES }) + "\n"
);

describe("rules", () => {
    for (const sc of SCENARIOS) {
        test(`rule::${sc.rule}::${sc.id}`, async () => {
            await runScenario(sc);
        });
    }

    test("rule::G13::no connection is opened without a token", async () => {
        ambient.token = undefined;
        await mount(EVENT_A);
        expect(connections.length, "a connection was opened with no auth token").toBe(0);
    });
});
