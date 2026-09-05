/**
 * What each flow shows with nothing stored.
 *
 * Measured from the candidate's own pages rather than written down here, so the
 * model never has to know what the create flow picks for a default picture or
 * what an event fixture is called. Measured once, before any scenario runs, on
 * an empty medium — a page that cannot open on an empty store is a harness
 * failure, not a wrong answer.
 */
import { documentSeen, galleryUrls, flyerPreview, questionTexts, readTitle } from "../harness/drive";
import { resetMediums } from "../harness/env";
import { endPage, openPage, startScenario, type Mode } from "../harness/page";
import type { UserKey } from "../harness/fixtures";
import type { Baseline } from "./draftModel";

const cache = new Map<string, Baseline>();

const id = (mode: string, user: string, event: string) => `${mode}|${user}|${event}`;

export interface Flow {
    mode: Mode;
    user?: UserKey;
    eventId?: string;
    /**
     * Also read what the questions section holds. It costs two modal opens,
     * each of which waits for a page that never stops moving, so it is measured
     * only for the flows whose rules ask about questions. A rule that asks
     * about a flow measured without this says so rather than comparing against
     * a value nobody took.
     */
    questions?: boolean;
    /** Also read which document the flow shows on its own. As above. */
    doc?: boolean;
}

export async function primeBaselines(flows: Flow[]): Promise<void> {
    for (const flow of flows) {
        const user = flow.user ?? "ada";
        const key = id(flow.mode, user, flow.eventId ?? "");
        if (cache.has(key)) continue;
        resetMediums();
        startScenario(user);
        await openPage({ mode: flow.mode, user, eventId: flow.eventId });
        const title = readTitle();
        const flyer = flyerPreview();
        const doc = flow.doc ? await documentSeen() : null;
        const questions = flow.questions ? await questionTexts() : null;
        // The gallery reading is last: it leaves its own modal open behind it.
        const gallery = await galleryUrls();
        cache.set(key, { title, flyer, questions, doc, gallery });
        await endPage();
    }
    resetMediums();
}

export function measureBaseline(mode: string, user: string, event: string): Baseline {
    const found = cache.get(id(mode, user, event));
    if (!found) throw new Error(`no baseline was measured for ${id(mode, user, event)}`);
    return found;
}
