/**
 * An independent model of the specification.
 *
 * This shares no code with the reference solution and is written from the
 * prompt, not from it. Where the reference is an incremental writer — a
 * versioned envelope per scope, a revision that has to keep climbing across a
 * reload, a chain that serialises writes — this is a replay: it holds the whole
 * scenario, applies each action to a plain picture of the page, and says what
 * the last page should show. It has no envelope, no version, no revision, no
 * queue and no timers, and it reaches the same answers by a different route.
 *
 * The rules it encodes, all of them from the prompt:
 *
 *   1. Only what was written down comes back. The model's `written` map is the
 *      only thing that crosses a reload.
 *   2. A draft belongs to one account, one flow, and one event. The model keys
 *      `written` by exactly that triple, so nothing else can reach it.
 *   3. A picture with no address a later page could fetch is not written down.
 *      Absent is not the same as empty: an absent field falls back to what the
 *      flow shows on its own, and the gallery is always written, so removing a
 *      picture is remembered.
 *   4. Restoring never rolls back something the user has already touched.
 *   5. A record from the previous release is adopted once, and only where its
 *      key says unambiguously which draft it is.
 *   6. Anything unreadable is no draft at all.
 *   7. Submitting or discarding leaves nothing to come back.
 *   8. Two pages editing one draft do not overwrite each other. A page that
 *      saves onto a record it has never seen contributes what it changed and
 *      leaves the rest of that record alone.
 *
 * Rule 8 needs no counter and no clock. Each page remembers the projection of
 * its own form as of the last thing it wrote, and a save carries the difference
 * between that and the form now — nothing else. A page that has not touched the
 * questions therefore says nothing about the questions, whoever else has. What
 * is stored is the accumulation of both pages' saves, and it never has to be
 * decided which of them wins, because they are not asked the same question.
 */
import type { Action } from "../harness/script";

/** A picture the form is holding. */
type Picture = { at: string } | { fromDisk: true };

const isDurable = (picture: Picture): picture is { at: string } => "at" in picture;

interface Form {
    title: string;
    flyer: Picture;
    gallery: Picture[];
    /** The questions the form holds, in the order the section shows them. */
    questions: string[];
    /** The attached document, or null once the user has taken it off. */
    doc: Picture | null;
}

/** What the flow shows with no draft at all. Measured, never assumed. */
export interface Baseline {
    title: string;
    flyer: string;
    gallery: string[];
    /** Null when this flow's questions were never measured. */
    questions: string[] | null;
    /**
     * The address of the document this flow shows on its own, "" when it shows
     * none, and null when nobody measured it.
     */
    doc: string | null;
}

/** The durable projection: what the specification allows to be written down. */
interface Written {
    title: string;
    /** Missing when the flyer the form holds could not be written down. */
    flyer?: string;
    gallery: string[];
    questions: string[];
    /**
     * Missing when the document the form holds could not be written down;
     * present and null once the user has taken the document off. The two are
     * different answers: the first leaves the flow's own document alone, the
     * second says there is no document.
     */
    doc?: string | null;
}

/** The pre-versioning record: plain form values, and no media at all. */
interface Legacy {
    title?: string;
}

export interface Prediction {
    title: string;
    flyer: string;
    gallery: string[];
    /** Null when the flow this ended on never had its questions measured. */
    questions: string[] | null;
    /** Null when the flow this ended on never had its document measured. */
    doc: string | null;
}

type Scope = { user: string; mode: string; event: string };

const scopeId = (scope: Scope) => [scope.user, scope.mode, scope.event].map(encodeURIComponent).join("/");

/** The previous release keyed by account and flow only. */
const legacyId = (user: string, mode: string) => [user, mode].map(encodeURIComponent).join("/");

function baselineForm(baseline: Baseline): Form {
    return {
        title: baseline.title,
        flyer: { at: baseline.flyer },
        gallery: baseline.gallery.map((at) => ({ at })),
        questions: baseline.questions ? [...baseline.questions] : [],
        doc: baseline.doc ? { at: baseline.doc } : null,
    };
}

/**
 * Which draft a page is authoring in.
 *
 * A duplicate starts from an event and produces a different one, so the event
 * it was copied from is not part of which draft it is; the create flow it
 * shares a route with is, because that is a different flow.
 */
const scopeOf = (user: string, mode: string, event: string): Scope => ({
    user,
    mode,
    event: mode === "edit" ? event : "",
});

function project(form: Form): Written {
    const written: Written = { title: form.title, gallery: [], questions: [...form.questions] };
    if (isDurable(form.flyer)) written.flyer = form.flyer.at;
    written.gallery = form.gallery.filter(isDurable).map((picture) => picture.at);
    if (form.doc === null) written.doc = null;
    else if (isDurable(form.doc)) written.doc = form.doc.at;
    return written;
}

/** One open page. Several of these exist only while a scenario opens tabs. */
interface Open {
    /** Which account, which flow, which event it started from. */
    page: { user: string; mode: string; event: string };
    scope: Scope;
    baseline: Baseline;
    form: Form;
    /** Fields the user has changed on this page. Restoring leaves these alone. */
    touched: Set<keyof Form>;
    /** Whether the page has taken delivery of whatever was stored. */
    restored: boolean;
    deferredRestore: (() => void) | null;
    /**
     * This page's own form as of the last thing it wrote down, or as of the
     * record it loaded. Deliberately not "what is stored": the store may hold
     * another page's work, and being able to see that work is not the same as
     * being entitled to speak for it.
     */
    baseProjection: Written;
}

const emptyOpen = (): Open => ({
    page: { user: "", mode: "", event: "" },
    scope: { user: "", mode: "", event: "" },
    baseline: { title: "", flyer: "", gallery: [], questions: null, doc: null },
    form: { title: "", flyer: { at: "" }, gallery: [], questions: [], doc: null },
    touched: new Set(),
    restored: true,
    deferredRestore: null,
    baseProjection: { title: "", gallery: [], questions: [] },
});

/** Stable text for one field's value, so two of them can be compared. */
const same = (a: unknown, b: unknown): boolean => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

/**
 * What this page has done to the form since the last thing it wrote down.
 *
 * Two halves, because a page can say something about a field and it can say
 * that there is nothing to say. A field that has dropped out of the projection
 * is the second: the picture it held has no address a later page could use, and
 * the record must lose the field rather than keep a value the user has replaced.
 */
function contribution(base: Written, next: Written): { set: Record<string, unknown>; unset: string[] } {
    const from = base as unknown as Record<string, unknown>;
    const to = next as unknown as Record<string, unknown>;
    const set: Record<string, unknown> = {};
    const unset: string[] = [];
    for (const field of Object.keys(to)) {
        if (to[field] === undefined) continue;
        if (field in from && same(from[field], to[field])) continue;
        set[field] = to[field];
    }
    for (const field of Object.keys(from)) {
        if (from[field] === undefined) continue;
        if (field in to && to[field] !== undefined) continue;
        unset.push(field);
    }
    return { set, unset };
}

export class DraftModel {
    /** The only state that survives a reload. */
    private readonly written = new Map<string, Written>();
    private readonly legacy = new Map<string, Legacy>();

    /**
     * Every page currently open, in the order it was opened. A scenario with no
     * tabs has exactly one, under the empty name, which is the single page the
     * other rules are all about.
     */
    private readonly open = new Map<string, Open>([["", emptyOpen()]]);
    private active = "";

    private get here(): Open {
        const found = this.open.get(this.active);
        if (!found) throw new Error(`model has no page ${this.active}`);
        return found;
    }

    constructor(private readonly baselines: (mode: string, user: string, event: string) => Baseline) {}

    run(actions: Action[]): Prediction {
        for (const action of actions) this.apply(action);
        // Every page still open gets to finish what it started, in the order
        // the pages were opened, because the scenario ends by letting
        // everything come to rest rather than by closing one page.
        const observed = this.active;
        for (const name of [...this.open.keys()]) {
            this.active = name;
            this.finishRestore();
        }
        this.active = observed;
        return this.observe();
    }

    private apply(action: Action): void {
        switch (action.do) {
            case "open":
            case "reload": {
                const user = action.do === "open" ? (action.user ?? "ada") : this.here.page.user;
                const mode = action.do === "open" ? action.mode : this.here.page.mode;
                const event = action.do === "open" ? (action.eventId ?? "") : this.here.page.event;
                this.load(user, mode, event, this.slowRead);
                break;
            }
            case "openTab": {
                // A tab of its own, over the same store. The page it replaces
                // is not closed, so any read it is still waiting on comes back
                // for it and not for this one.
                this.open.set(action.tab, emptyOpen());
                this.active = action.tab;
                this.load(action.user ?? "ada", action.mode, action.eventId ?? "", this.slowRead);
                break;
            }
            case "inTab":
                if (!this.open.has(action.tab)) throw new Error(`model has no page ${action.tab}`);
                this.active = action.tab;
                break;
            case "closeTabs": {
                // Every tab is let go at once. Each finishes what it started,
                // in the order they were opened, and then there is one page
                // again for whatever the scenario opens next.
                const names = [...this.open.keys()].filter((name) => name !== "");
                for (const name of names) {
                    this.active = name;
                    this.finishRestore();
                }
                for (const name of names) this.open.delete(name);
                this.active = "";
                break;
            }
            case "type":
            case "typeAndMoveOn":
                this.change("title", (form) => {
                    form.title = action.value;
                });
                break;
            case "typeRun":
                // However a page groups its writes, the last thing typed is
                // still the work that was in it.
                for (const value of action.values) {
                    this.change("title", (form) => {
                        form.title = value;
                    });
                }
                break;
            case "pickFlyer":
                // The address is whatever the library offered; the page under
                // test is the authority on that, so the model only records that
                // the flyer is now something a later page could fetch.
                this.change("flyer", (form) => {
                    form.flyer = { at: PICKED };
                });
                break;
            case "uploadFlyer":
                this.change("flyer", (form) => {
                    form.flyer = { fromDisk: true };
                });
                break;
            case "addPhoto":
                this.change("gallery", (form) => {
                    form.gallery = [...form.gallery, { fromDisk: true }];
                });
                break;
            case "removePhoto":
                this.change("gallery", (form) => {
                    form.gallery = form.gallery.filter((_, index) => index !== action.index);
                });
                break;
            case "addQuestion":
                this.change("questions", (form) => {
                    form.questions = [...form.questions, action.text];
                });
                break;
            case "removeQuestion":
                this.change("questions", (form) => {
                    form.questions = form.questions.filter((_, index) => index !== action.index);
                });
                break;
            case "uploadDoc":
                this.change("doc", (form) => {
                    form.doc = { fromDisk: true };
                });
                break;
            case "removeDoc":
                this.change("doc", (form) => {
                    form.doc = null;
                });
                break;
            case "discard":
                this.finishRestore();
                this.written.delete(scopeId(this.here.scope));
                this.legacy.delete(legacyId(this.here.scope.user, this.here.scope.mode));
                this.here.form = baselineForm(this.here.baseline);
                this.here.touched.clear();
                this.here.baseProjection = project(this.here.form);
                break;
            case "submit":
                this.finishRestore();
                this.written.delete(scopeId(this.here.scope));
                this.legacy.delete(legacyId(this.here.scope.user, this.here.scope.mode));
                break;
            case "seedLegacy": {
                const title = action.fields.name;
                this.legacy.set(legacyId(action.user, action.mode), {
                    title: typeof title === "string" ? title : undefined,
                });
                break;
            }
            case "seedRaw":
                // Nothing readable was put anywhere the model can see, which is
                // exactly what the rule says the page should conclude.
                break;
            case "slowReads":
                this.slowRead = true;
                break;
            case "slowFirstWrite":
            case "failNextWrite":
            case "storeBudget":
                // None of these changes what should end up stored, only how
                // hard it is to get there. The prediction is the same either
                // way, which is the point of grading them.
                break;
        }
    }

    private slowRead = false;

    private load(user: string, mode: string, event: string, deferred: boolean): void {
        this.finishRestore();
        this.slowRead = false;
        this.here.page = { user, mode, event };
        this.here.scope = scopeOf(user, mode, event);
        this.here.baseline = this.baselines(mode, user, event);
        this.here.form = baselineForm(this.here.baseline);
        this.here.touched = new Set();
        this.here.baseProjection = project(this.here.form);

        const restore = () => {
            const stored = this.written.get(scopeId(this.here.scope));
            if (stored) {
                this.applyStored(stored);
                // What this page is working from: the form that record
                // produced. Read off the record rather than the live form,
                // because anything typed while the read was in flight is this
                // page's own change and not part of what it started from.
                this.here.baseProjection = project(this.restoredForm(stored));
                return;
            }
            // The previous release's key says which account and which flow but
            // not which event, so it can only be trusted where one draft per
            // account is all there ever was.
            if (mode === "edit") return;
            const old = this.legacy.get(legacyId(user, mode));
            if (!old) return;
            if (old.title !== undefined && !this.here.touched.has("title")) this.here.form.title = old.title;
            // Adopting it makes it the current draft; the old record is spent.
            this.legacy.delete(legacyId(user, mode));
            this.written.set(scopeId(this.here.scope), project(this.here.form));
        };

        if (deferred) {
            this.here.restored = false;
            this.here.deferredRestore = restore;
        } else {
            this.here.restored = true;
            this.here.deferredRestore = null;
            restore();
        }
    }

    /**
     * The form this page would be showing if the stored record were all there
     * was: the flow's starting point with that record laid over it, and nothing
     * the user has done since.
     */
    private restoredForm(stored: Written): Form {
        const form = baselineForm(this.here.baseline);
        form.title = stored.title;
        if (stored.flyer !== undefined) form.flyer = { at: stored.flyer };
        form.gallery = stored.gallery.map((at) => ({ at }));
        form.questions = [...stored.questions];
        if ("doc" in stored) form.doc = stored.doc === null || stored.doc === undefined ? null : { at: stored.doc };
        return form;
    }

    private applyStored(stored: Written): void {
        if (!this.here.touched.has("title")) this.here.form.title = stored.title;
        if (!this.here.touched.has("flyer") && stored.flyer !== undefined) this.here.form.flyer = { at: stored.flyer };
        if (!this.here.touched.has("gallery")) this.here.form.gallery = stored.gallery.map((at) => ({ at }));
        if (!this.here.touched.has("questions")) this.here.form.questions = [...stored.questions];
        if (!this.here.touched.has("doc") && "doc" in stored) {
            this.here.form.doc = stored.doc === null || stored.doc === undefined ? null : { at: stored.doc };
        }
    }

    private finishRestore(): void {
        if (this.here.restored) return;
        const restore = this.here.deferredRestore;
        this.here.restored = true;
        this.here.deferredRestore = null;
        restore?.();
        // Work done while the page was waiting is saved once it is not.
        if (this.here.touched.size > 0) this.save();
    }

    private change(field: keyof Form, mutate: (form: Form) => void): void {
        mutate(this.here.form);
        this.here.touched.add(field);
        if (this.here.restored) this.save();
    }

    /**
     * Write this page's work down.
     *
     * With nothing stored there is nothing to preserve, and the record starts
     * as everything this page can say. With something stored, this page may
     * only say what it has changed since the last thing it wrote: the rest of
     * the record belongs to whoever put it there, which may be another tab of
     * the same flow, and this page cannot see their work to reproduce it.
     */
    private save(): void {
        const here = this.here;
        const id = scopeId(here.scope);
        const stored = this.written.get(id) ?? null;
        const projection = project(here.form);

        let next: Written;
        if (stored === null) {
            next = projection;
        } else {
            const { set, unset } = contribution(here.baseProjection, projection);
            if (Object.keys(set).length === 0 && unset.length === 0) {
                here.baseProjection = projection;
                return;
            }
            const merged = { ...(stored as unknown as Record<string, unknown>), ...set };
            for (const field of unset) delete merged[field];
            next = merged as unknown as Written;
        }

        this.written.set(id, next);
        here.baseProjection = projection;
    }

    private observe(): Prediction {
        return {
            title: this.here.form.title,
            flyer: isDurable(this.here.form.flyer) ? this.here.form.flyer.at : TRANSIENT,
            gallery: this.here.form.gallery.map((picture) => (isDurable(picture) ? picture.at : TRANSIENT)),
            questions: this.here.baseline.questions === null ? null : [...this.here.form.questions],
            // Which document, not merely whether there is one: a page that
            // brought back an address only the page that made it could resolve
            // is holding a document, and is holding the wrong one.
            doc:
                this.here.baseline.doc === null
                    ? null
                    : this.here.form.doc === null
                      ? ""
                      : isDurable(this.here.form.doc)
                        ? this.here.form.doc.at
                        : TRANSIENT,
        };
    }
}

/**
 * Two addresses the model does not know and does not need to: one the flyer
 * library chose, and one that only the page holding the file can resolve. The
 * comparison treats them as wildcards.
 */
export const PICKED = "\u0000picked";
export const TRANSIENT = "\u0000transient";
