// Analytics Stream Types
// Matches backend Go structs for GET /events/hosts/analytics-stream SSE endpoint

import { sameStreamPayload } from "../hooks/event/analyticsSectionMerge";
import {
    EventAnalyticsCharts,
    EventAnalyticsDemographics,
    EventAnalyticsRevenue,
} from "../hooks/event/useEventAnalytics";

// === Request Type ===
export interface AnalyticsStreamRequest {
    eventId: string; // UUID
    startTime: number; // Unix seconds
    endTime: number; // Unix seconds
    buckets: number; // 2-100
    /**
     * `since` on the wire. A revision the caller already has: the backend
     * replays from just past it instead of producing the whole stream again.
     * Absent on a request that is not continuing anything; `analyticsResume.ts`
     * is where this client decides what to put in it.
     */
    since?: number;
}

// === SSE Event Types (Discriminated Union) ===
export const ANALYTICS_STREAM_SECTIONS = [
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
] as const;

export type AnalyticsStreamSection = (typeof ANALYTICS_STREAM_SECTIONS)[number];

// Type guard function
export function isValidSection(section: string): section is AnalyticsStreamSection {
    return ANALYTICS_STREAM_SECTIONS.includes(section as AnalyticsStreamSection);
}

// === Section Data Types (1:1 with backend Go structs) ===

// ScanStats represents scanning statistics for an event
export interface ScanStats {
    scannedPeople: number;
    expectedAttendees: number;
    scanRatePercent: number;
    repeatScansCount?: number; // omitempty in Go
    invalidScansCount?: number; // omitempty in Go
    expiredScansCount?: number; // omitempty in Go
}

// ScanAnalytics represents scan timeline analytics with buckets
export interface ScanAnalytics {
    timeline: ScanAnalyticsBucket[];
    averageScanTimeMs: number | null;
}

// ScanAnalyticsBucket represents a time bucket for scan analytics
export interface ScanAnalyticsBucket {
    startTime: number;
    endTime: number;
    midpoint: number;
    peopleScannedBucket: number;
    peopleScannedCumulative: number;
}

// RetentionStats represents customer retention analytics
export interface RetentionStats {
    newUsersCount: number;
    returningUsersCount: number;
    returningUsersPercent: number;
    returningByEvent?: RetentionStatsByEvent[]; // omitempty in Go
}

// RetentionStatsByEvent represents returning users breakdown by source event
export interface RetentionStatsByEvent {
    eventId: string;
    eventName: string;
    count: number;
}

// PurchasesByLocation represents purchase breakdown by buyer location
export interface PurchasesByLocation {
    locationKey: string;
    numOrders: number;
    numUniqueBuyers: number;
    grossRevenueCents: number;
}

// PurchasesByDevice represents purchase breakdown by device platform
export interface PurchasesByDevice {
    ios: PurchasesByDevicePlatform;
    web: PurchasesByDevicePlatform;
}

// PurchasesByDevicePlatform represents platform-specific purchase stats
export interface PurchasesByDevicePlatform {
    count: number;
    percentage: number;
    revenueCents: number;
}

// InteractionsByPlatform represents views and shares broken down by platform
export interface InteractionsByPlatform {
    numViewsIOS: number;
    numViewsWeb: number;
    numViewsNoUser: number; // Views where user is nil (anonymous)
    numSharesIOS: number;
    numSharesWeb: number;
}

// FinancialsData represents financial summary from the stream
export interface FinancialsData {
    net: number;
    payment: {
        pending: number;
        available: number;
        linked: number;
    };
    refunded: number;
    revenueBySource: RevenueBySourceItem[];
}

// RevenueBySourceItem represents revenue breakdown by source
export interface RevenueBySourceItem {
    source: string;
    sum: number;
    count: number;
}

// === Section Data Map (for type-safe access) ===
export interface AnalyticsStreamDataMap {
    charts: EventAnalyticsCharts;
    revenue: EventAnalyticsRevenue;
    demographics: EventAnalyticsDemographics;
    financials: FinancialsData;
    scanStats: ScanStats;
    scanTimeline: ScanAnalytics;
    retention: RetentionStats;
    purchasesByLocation: PurchasesByLocation[];
    purchasesByDevice: PurchasesByDevice;
    interactionsByPlatform: InteractionsByPlatform;
    __complete__: undefined;
}

// === SSE Event Type (Generic) ===
export interface AnalyticsStreamEvent<T extends AnalyticsStreamSection = AnalyticsStreamSection> {
    section: T;
    data: T extends "__complete__" ? undefined : AnalyticsStreamDataMap[T];
    error?: string;
    revision?: number;
}

// Raw event from SSE (before type narrowing)
export interface RawAnalyticsStreamEvent {
    section: string;
    data?: unknown;
    error?: string;
    /**
     * Version of this section's value, counted up by the backend across the
     * whole stream. Two frames for the same section are ordered by it, which is
     * what makes a replay after a resume distinguishable from an update.
     * Omitted on frames the backend cannot version.
     */
    revision?: number;
}

/** Every section that carries a payload, i.e. everything but the sentinel. */
export const ANALYTICS_DATA_SECTIONS = ANALYTICS_STREAM_SECTIONS.filter(
    (section): section is AnalyticsDataSection => section !== "__complete__"
);

export type AnalyticsDataSection = Exclude<AnalyticsStreamSection, "__complete__">;

// === State Type for the Hook ===
export interface AnalyticsStreamState {
    // Section data (null = not received yet)
    charts: EventAnalyticsCharts | null;
    revenue: EventAnalyticsRevenue | null;
    demographics: EventAnalyticsDemographics | null;
    financials: FinancialsData | null;
    scanStats: ScanStats | null;
    scanTimeline: ScanAnalytics | null;
    retention: RetentionStats | null;
    purchasesByLocation: PurchasesByLocation[] | null;
    purchasesByDevice: PurchasesByDevice | null;
    interactionsByPlatform: InteractionsByPlatform | null;

    // Meta state
    loading: boolean;
    error: Error | null;
    isComplete: boolean;

    // Track received sections
    receivedSections: Set<AnalyticsStreamSection>;

    /**
     * Sections the stream will not produce: it said so explicitly, or it ended
     * without them. A settled section has stopped loading even though it has no
     * data, which is what lets one panel report failure while its neighbours
     * are still waiting.
     */
    settledSections: Set<AnalyticsStreamSection>;

    /** Why a section failed, keyed by section. Never promoted to `error`. */
    sectionErrors: Partial<Record<AnalyticsDataSection, string>>;

    /**
     * The revision of the value each section is currently showing.
     *
     * This is what makes a replay distinguishable from an update. After a
     * resume the backend re-sends sections it has already produced, and those
     * frames carry the revision they were produced at; a frame at or below the
     * revision on screen is a replay of something already applied and must not
     * displace a newer value that arrived in between.
     */
    revisions: Partial<Record<AnalyticsDataSection, number>>;
}

/**
 * Whether a panel should still be showing its loading placeholder.
 *
 * A section is in flight until the stream either delivers it or tells us it is
 * not coming. `loading` on its own cannot answer this: it describes the stream,
 * not the section, and the whole point is that sections finish independently.
 */
export function isSectionPending(
    state: Pick<AnalyticsStreamState, "receivedSections" | "settledSections">,
    section: AnalyticsDataSection
): boolean {
    return !state.receivedSections.has(section) && !state.settledSections.has(section);
}

/** The failure the stream reported for a section, if any. */
export function sectionFailure(
    state: Pick<AnalyticsStreamState, "sectionErrors">,
    section: AnalyticsDataSection
): string | undefined {
    return state.sectionErrors[section];
}

/**
 * Whether a frame is older news than what the section already shows.
 *
 * Only a frame that carries a revision can be judged, and it is only stale
 * against a section that is showing a revision of its own. Everything else has
 * to be treated as current: refusing an unversioned frame would silently drop
 * sections the backend cannot version.
 */
export function isReplayedFrame(
    state: Pick<AnalyticsStreamState, "revisions">,
    section: AnalyticsDataSection,
    revision: number | undefined
): boolean {
    if (typeof revision !== "number" || !Number.isFinite(revision)) return false;
    const shown = state.revisions[section];
    if (typeof shown !== "number") return false;
    return revision <= shown;
}

// Initial state factory
export function createInitialAnalyticsStreamState(): AnalyticsStreamState {
    return {
        charts: null,
        revenue: null,
        demographics: null,
        financials: null,
        scanStats: null,
        scanTimeline: null,
        retention: null,
        purchasesByLocation: null,
        purchasesByDevice: null,
        interactionsByPlatform: null,
        loading: true,
        error: null,
        isComplete: false,
        receivedSections: new Set(),
        settledSections: new Set(),
        sectionErrors: {},
        revisions: {},
    };
}

// Type-safe state update function
//
// Folds one decoded stream frame into the panel state. Pure, so the hook can
// call it from inside a state updater and re-run it safely.
export function updateStateForSection(
    state: AnalyticsStreamState,
    event: RawAnalyticsStreamEvent
): AnalyticsStreamState {
    const { section, data, error, revision } = event;

    // A section name we do not know about is not a reason to disturb anything
    // that is already on screen. The backend is free to add sections ahead of
    // the client learning about them.
    if (!isValidSection(section)) {
        console.warn(`Unknown analytics stream section: ${section}`);
        return state;
    }

    // The terminal frame ends the stream. Sections that never arrived are not
    // going to; mark them settled so their panels stop waiting, and leave
    // everything that did arrive exactly as it is.
    if (section === "__complete__") {
        const settledSections = new Set(state.settledSections);
        for (const candidate of ANALYTICS_DATA_SECTIONS) {
            if (!state.receivedSections.has(candidate)) settledSections.add(candidate);
        }
        return {
            ...state,
            loading: false,
            isComplete: true,
            settledSections,
        };
    }

    // A replay of a revision the section has already moved past says nothing new
    // about it. This is checked before everything else that follows, because a
    // replay must not be able to raise a failure, reset a value, or count as a
    // fresh delivery: after a resume the backend re-sends what it had, and what
    // it had may be older than what arrived on the connection in between.
    if (isReplayedFrame(state, section, revision)) return state;

    // A section-level failure is confined to that section. Promoting it to
    // `error` would blank every panel that reads the top-level failure, which is
    // exactly the behaviour this endpoint exists to avoid: one slow query should
    // not take the dashboard with it.
    if (error) {
        console.error(`Analytics stream error for section ${section}:`, error);
        const settledSections = new Set(state.settledSections);
        settledSections.add(section);
        return {
            ...state,
            settledSections,
            sectionErrors: { ...state.sectionErrors, [section]: error },
        };
    }

    if (data === undefined || data === null) return state;

    // A redelivery of the value we already hold must not produce a new state
    // object: downstream memoisation keys off identity, and re-emitting the same
    // figures makes panels recompute and, where they aggregate, double count.
    // Comparing by section name instead of by value would go too far the other
    // way and discard a genuine correction.
    if (state.receivedSections.has(section) && sameStreamPayload(state[section], data)) {
        return state;
    }

    const receivedSections = new Set(state.receivedSections);
    receivedSections.add(section);

    // A section that arrives after a failure supersedes the failure. The panel
    // was told this section was not coming; it came, so the refusal is history.
    const settledSections = new Set(state.settledSections);
    settledSections.delete(section);
    const sectionErrors = { ...state.sectionErrors };
    delete sectionErrors[section];

    // Record what the panel is now showing, so a later replay can be recognised
    // and so a resume knows where to continue from.
    const revisions = { ...state.revisions };
    if (typeof revision === "number" && Number.isFinite(revision)) {
        revisions[section] = revision;
    } else {
        delete revisions[section];
    }

    return {
        ...state,
        [section]: data as AnalyticsStreamDataMap[typeof section],
        receivedSections,
        settledSections,
        sectionErrors,
        revisions,
    };
}
