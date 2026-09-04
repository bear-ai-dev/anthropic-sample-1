/**
 * A scenario as a list of actions.
 *
 * The same list is given to two things: this runner, which performs it against
 * the candidate through the app's own controls, and the model, which predicts
 * what the last page should show. Neither knows anything about the other.
 */
import {
    addGalleryFile,
    addQuestion,
    byText,
    documentSeen,
    flyerPreview,
    galleryUrls,
    makeFile,
    pickLibraryFlyer,
    questionTexts,
    readTitle,
    removeDocument,
    removeGalleryImage,
    removeQuestion,
    requireByText,
    transientUrlsOnPage,
    typeTitle,
    uploadDocument,
    uploadFlyer,
    click,
} from "./drive";
import { localMedium } from "./env";
import {
    endAllTabs,
    endPage,
    enterTab,
    nudge,
    openPage,
    openTab,
    reload,
    settle,
    startScenario,
    type Mode,
    type PageOptions,
} from "./page";
import { USERS, type UserKey } from "./fixtures";

export const LEGACY_PREFIX = "ExampleCo:draft:";

/** Virtual time between one keystroke and the next in a typing run. */
export const KEYSTROKE_GAP_MS = 40;

/** Where the previous release kept a draft: account and flow, and no more. */
export const legacyKey = (userId: string, mode: Mode): string => `${LEGACY_PREFIX}event:${userId}:${mode}`;

/**
 * Actions that change the form take an optional `now`, which performs the same
 * interaction without letting the page come to rest afterwards. Whatever the
 * candidate does about grouping its writes has not happened yet when the next
 * action arrives, so a page that goes away at that moment has to get the work
 * out of the door itself.
 */
export type Action =
    | { do: "open"; mode: Mode; user?: UserKey; eventId?: string }
    | { do: "reload" }
    /**
     * Open another tab on the same flow, alongside whatever is already open.
     *
     * Its module graph and its DOM are its own, so the only thing it shares
     * with the other tabs is the store — which is all two tabs of a browser
     * share, and the whole of what these scenarios are about.
     */
    | { do: "openTab"; tab: string; mode: Mode; user?: UserKey; eventId?: string }
    /** Drive this tab from here on. */
    | { do: "inTab"; tab: string }
    /** Close every open tab, delivering the teardown signals once. */
    | { do: "closeTabs" }
    | { do: "type"; value: string }
    /** Type and move on without waiting: whatever this starts is still in flight. */
    | { do: "typeAndMoveOn"; value: string }
    /** Type one value after another at the pace of a person, and do not wait after. */
    | { do: "typeRun"; values: string[] }
    | { do: "pickFlyer"; index: number; now?: boolean }
    | { do: "uploadFlyer"; now?: boolean }
    | { do: "addPhoto"; now?: boolean }
    | { do: "removePhoto"; index: number; now?: boolean }
    /** Write a question through the section that owns the list. */
    | { do: "addQuestion"; text: string; now?: boolean }
    /** Take a question off through the section that owns the list. */
    | { do: "removeQuestion"; index: number; now?: boolean }
    /** Put a document on the form from disk: nothing a later page could fetch. */
    | { do: "uploadDoc"; now?: boolean }
    /** Take the document off the form. */
    | { do: "removeDoc"; now?: boolean }
    | { do: "discard" }
    | { do: "submit" }
    /** Write a pre-versioning record straight into the medium. */
    | { do: "seedLegacy"; user: UserKey; mode: Mode; fields: Record<string, unknown> }
    /** Write arbitrary text into the medium, as another release or another tab might. */
    | { do: "seedRaw"; key: string; text: string }
    /** Hold the next page's reads open for this long. */
    | { do: "slowReads"; ms: number }
    /** Make the first write of the page take this long, so a later one can overtake it. */
    | { do: "slowFirstWrite"; ms: number }
    /** Refuse the next write, the way a full store does. */
    | { do: "failNextWrite" }
    /**
     * Refuse every draft write past this many, for the rest of the scenario.
     *
     * A shared store does not take an unlimited number of writes from one page,
     * and the budget here is generous: any design that treats typing as one
     * piece of work stays well inside it, and one that writes for every
     * keystroke does not, and loses the keystrokes it wrote past the end.
     */
    | { do: "storeBudget"; writes: number };

export interface Observation {
    title: string;
    flyer: string;
    gallery: string[];
    /** Addresses on the page that only the page that made them could resolve. */
    transient: string[];
    /** The address shown for each picture chosen from the flyer library. */
    picked: string[];
    /** The questions the form holds, when asked for. */
    questions?: string[];
    /** The address of the document the form holds, when asked for. */
    doc?: string;
}

export interface RunOptions {
    /** Read the gallery as well, which costs a modal open. */
    withGallery?: boolean;
    /** Read the questions as well. */
    withQuestions?: boolean;
    /** Read the document as well. */
    withDoc?: boolean;
    user?: UserKey;
}

let openOptions: PageOptions | null = null;

/**
 * Actions after which the harness waits for everything to stop moving.
 * Seeding touches only the medium, opening a page under a slow store is
 * deliberately left mid-flight, and typing-and-moving-on is the whole point of
 * that action.
 */
const SETTLES = new Set<Action["do"]>([
    "type",
    "pickFlyer",
    "uploadFlyer",
    "addPhoto",
    "removePhoto",
    "addQuestion",
    "removeQuestion",
    "uploadDoc",
    "removeDoc",
    "discard",
    "submit",
]);

function pageOptions(action: Extract<Action, { do: "open" | "openTab" }>): PageOptions {
    return { mode: action.mode, user: action.user ?? "ada", eventId: action.eventId };
}

const isDraftKey = (key: string) => key.startsWith(LEGACY_PREFIX);

interface Plans {
    reads?: number;
    firstWrite?: number;
    failWrite?: boolean;
    budget?: number;
}

async function applyPlans(plans: Plans): Promise<void> {
    const { reads, firstWrite, failWrite, budget } = plans;
    let writesSeen = 0;
    let failuresLeft = failWrite ? 1 : 0;
    let draftWritesTaken = 0;
    localMedium.planDelays((op) => {
        if (op.kind === "read" && reads) return reads;
        if (op.kind === "write" && firstWrite) {
            writesSeen += 1;
            return writesSeen === 1 ? firstWrite : 1;
        }
        return 1;
    });
    localMedium.planFaults((op) => {
        if (op.kind !== "write") return null;
        if (failuresLeft > 0) {
            failuresLeft -= 1;
            return "the store is full";
        }
        if (budget !== undefined && isDraftKey(op.key)) {
            draftWritesTaken += 1;
            if (draftWritesTaken > budget) return "the store will not take another write from this page";
        }
        return null;
    });
}

/** Perform a scenario. Returns what the final page shows. */
export async function perform(actions: Action[], options: RunOptions = {}): Promise<Observation> {
    startScenario(options.user ?? "ada");
    const plans: Plans = {};
    const picked: string[] = [];

    for (const action of actions) {
        const now = "now" in action ? action.now === true : false;
        switch (action.do) {
            case "open": {
                // Opening a flow is leaving whatever page was there before.
                await endPage();
                openOptions = { ...pageOptions(action), settleAfterMount: !plans.reads };
                await applyPlans(plans);
                await openPage(openOptions);
                plans.reads = undefined;
                break;
            }
            case "reload": {
                if (!openOptions) throw new Error("reload before open");
                openOptions = { ...openOptions, settleAfterMount: !plans.reads };
                await applyPlans(plans);
                await reload(openOptions);
                plans.reads = undefined;
                break;
            }
            case "openTab": {
                await applyPlans(plans);
                await openTab(action.tab, { ...pageOptions(action), settleAfterMount: !plans.reads });
                plans.reads = undefined;
                break;
            }
            case "inTab":
                enterTab(action.tab);
                break;
            case "closeTabs":
                await endAllTabs();
                break;
            case "type":
                await typeTitle(action.value);
                break;
            case "typeAndMoveOn":
                await typeTitle(action.value);
                // Long enough for a save to be issued, nowhere near long
                // enough for a slow one to finish.
                await nudge(1200);
                break;
            case "typeRun":
                for (const value of action.values) {
                    await typeTitle(value);
                    await nudge(KEYSTROKE_GAP_MS);
                }
                break;
            case "pickFlyer":
                await pickLibraryFlyer(action.index, now);
                picked.push(flyerPreview());
                break;
            case "uploadFlyer":
                await uploadFlyer(makeFile("from-disk.jpg"), now);
                break;
            case "addPhoto":
                await addGalleryFile(makeFile("photo.jpg"), now);
                break;
            case "removePhoto":
                await removeGalleryImage(action.index, now);
                break;
            case "addQuestion":
                await addQuestion(action.text, now);
                break;
            case "removeQuestion":
                await removeQuestion(action.index, now);
                break;
            case "uploadDoc":
                await uploadDocument(makeFile("terms.pdf"), now);
                break;
            case "removeDoc":
                await removeDocument(now);
                break;
            case "discard":
                await click(requireByText("Discard draft"));
                break;
            case "submit":
                await click(byText("Update Event") ?? requireByText("Create Event"));
                break;
            case "seedLegacy":
                localMedium.cells.set(legacyKey(USERS[action.user].id, action.mode), JSON.stringify(action.fields));
                break;
            case "seedRaw":
                localMedium.cells.set(action.key, action.text);
                break;
            case "slowReads":
                // Reads only matter as a page opens, so this one waits.
                plans.reads = action.ms;
                break;
            case "slowFirstWrite":
                plans.firstWrite = action.ms;
                await applyPlans(plans);
                break;
            case "failNextWrite":
                plans.failWrite = true;
                await applyPlans(plans);
                break;
            case "storeBudget":
                plans.budget = action.writes;
                await applyPlans(plans);
                break;
        }
        if (SETTLES.has(action.do) && !now) await settle();
    }

    await settle();
    return observe(options, picked);
}

/** How many times a draft key has been written, however the candidate got there. */
export function draftWrites(): number {
    return localMedium.ops.filter((op) => op.kind === "write" && isDraftKey(op.key)).length;
}

/**
 * Read the last page. The order matters: the readings that open a modal of
 * their own come before the gallery, whose own modal is left open behind it.
 */
export async function observe(options: RunOptions = {}, picked: string[] = []): Promise<Observation> {
    const title = readTitle();
    const flyer = flyerPreview();
    const doc = options.withDoc ? await documentSeen() : undefined;
    const questions = options.withQuestions ? await questionTexts() : undefined;
    const gallery = options.withGallery ? await galleryUrls() : [];
    return {
        title,
        flyer,
        gallery,
        transient: transientUrlsOnPage(),
        picked,
        questions,
        doc,
    };
}
