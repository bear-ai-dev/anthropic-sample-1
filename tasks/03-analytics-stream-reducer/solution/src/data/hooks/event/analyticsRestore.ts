// Turning a kept record back into a dashboard.
//
// The restored state is deliberately not "the state we had last time". It is the
// figures we had last time and nothing else, in a read that has only just
// started:
//
//   * every section holding a value counts as received, so its panel shows the
//     figure immediately instead of a skeleton;
//   * every other section is waiting, not settled — the previous read's refusals
//     and its ending are that read's conclusions, and this is a new read that
//     has not reached any;
//   * the revisions come back with the values, because the revision is the only
//     thing that lets the next connection say how far this dashboard got, and a
//     value restored without one can only be replaced, never resumed after.
//
// `loading` is true and `error` is null for the same reason: a fresh read is
// under way. A restored dashboard that reported itself finished would leave the
// host looking at figures from last week with nothing on its way to correct them.

import {
    AnalyticsStreamState,
    createInitialAnalyticsStreamState,
} from "@data/types/analyticsStream.types";
import { RestoredSection } from "./analyticsSnapshotCodec";

export function stateFromRestoredSections(restored: RestoredSection[] | null): AnalyticsStreamState {
    const state = createInitialAnalyticsStreamState();
    if (!restored || restored.length === 0) return state;

    const receivedSections = new Set(state.receivedSections);
    const revisions = { ...state.revisions };
    const next = { ...state } as Record<string, unknown>;

    for (const entry of restored) {
        next[entry.section] = entry.data;
        receivedSections.add(entry.section);
        if (entry.revision !== null) revisions[entry.section] = entry.revision;
    }

    return {
        ...(next as unknown as AnalyticsStreamState),
        receivedSections,
        revisions,
    };
}
