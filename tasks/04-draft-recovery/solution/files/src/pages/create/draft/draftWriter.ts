import { DraftStorage } from "@data/storage/draftStorage";
import { decodeEnvelope, encodeEnvelope, makeEnvelope, supersedes } from "./draftEnvelope";
import { applyPatch, patchBetween, patchIsEmpty } from "./draftFields";
import { DraftEnvelope, DraftScope, DurableFields } from "./draftTypes";

/**
 * The only thing allowed to write a draft.
 *
 * Three hazards are handled here and nowhere else.
 *
 * The first is that a write takes time. Two saves issued a moment apart can
 * complete in either order, and if the older one completes last it undoes the
 * newer one. Every write for a key therefore goes through one chain, so a save
 * is only issued once the save before it has finished.
 *
 * The second is that the page is not the only writer. The key names an account
 * and a flow, not a page, so a second tab of the same flow is editing this same
 * record — and a window left open on another screen is a second tab. Its work
 * is not in this page's form and cannot be: the store is the only channel
 * between them and it carries no notification. So a save is not "write down my
 * form". It is "put what I have changed into the record", which is why what
 * goes out is a patch against `mine` rather than the projection itself. A page
 * that has not touched the questions says nothing about the questions, and
 * whoever did touch them keeps them.
 *
 * The third is that saying nothing and saying "nothing" are different answers,
 * and a patch has to be able to make both. A field whose value can no longer be
 * written down has to leave the record rather than keep its old value, or a
 * picture the user replaced with one from disk comes back from the dead.
 *
 * The revision is not what decides any of this; it is bookkeeping, so that a
 * reader can tell two records apart and a write that would not advance the
 * record is refused.
 */
export class DraftWriter {
    /**
     * The projection of this page's form as of the last thing it wrote down,
     * or as of the record it loaded. Not what is stored: what is stored may
     * contain another page's work, and this page must not start speaking for
     * that work merely because it can see it.
     */
    private mine: DurableFields = {};
    /** The revision this page last saw, so its writes keep advancing. */
    private base = 0;
    private chain: Promise<void> = Promise.resolve();
    private queued: DurableFields | null = null;
    private closed = false;

    constructor(
        private readonly storage: DraftStorage,
        private readonly key: string,
        private readonly scope: DraftScope
    ) {}

    /**
     * Declare what this page is working from: the revision it loaded, and the
     * projection of the form as that record left it.
     *
     * Called once after the load, and again after every write this page makes.
     */
    rebase(revision: number, fields: DurableFields): void {
        if (revision >= this.base) this.base = revision;
        this.mine = fields;
    }

    /**
     * Start again from nothing stored.
     *
     * Discarding removes the record, so the page is working from the flow's own
     * starting point and not from the draft it just threw away.
     */
    restart(fields: DurableFields): void {
        this.base = 0;
        this.mine = fields;
    }

    /** Coalesce a save. Only the newest queued projection is written. */
    save(fields: DurableFields): Promise<void> {
        if (this.closed) return Promise.resolve();
        this.queued = fields;
        return this.enqueue(() => this.flush());
    }

    /** Remove the draft and refuse any save issued before this point. */
    remove(extraKeys: string[] = []): Promise<void> {
        this.queued = null;
        this.closed = true;
        return this.enqueue(async () => {
            await this.storage.remove(this.key);
            for (const key of extraKeys) await this.storage.remove(key);
        });
    }

    /** Allow saving again after a removal, starting from the next revision. */
    reopen(): void {
        this.closed = false;
    }

    /**
     * Add a step to the chain.
     *
     * A storage that is full, or switched off, rejects. That failure must not
     * take the chain with it: a draft is best effort, and one refused write is
     * no reason to stop trying on the next keystroke. So the chain is kept
     * settled and the error stops here.
     */
    private enqueue(step: () => Promise<void>): Promise<void> {
        this.chain = this.chain.then(step).catch(() => undefined);
        return this.chain;
    }

    private async flush(): Promise<void> {
        const fields = this.queued;
        this.queued = null;
        if (fields === null || this.closed) return;

        const stored = decodeEnvelope(await this.storage.read(this.key), this.scope);
        const revision = Math.max(this.base, stored?.revision ?? 0) + 1;

        let envelope: DraftEnvelope;
        if (stored === null) {
            // Nothing is there to preserve, so the record starts as everything
            // this page can say. Without this a draft would only ever contain
            // the fields the user happened to touch.
            envelope = makeEnvelope(this.scope, revision, fields);
        } else {
            const patch = patchBetween(this.mine, fields);
            // Nothing has moved since this page last wrote. Leaving the record
            // alone is not just an optimisation: rewriting it would spend a
            // write the store may not have to give.
            if (patchIsEmpty(patch)) {
                this.rebase(stored.revision, fields);
                return;
            }
            envelope = makeEnvelope(this.scope, revision, applyPatch(stored.fields, patch));
        }

        if (!supersedes(envelope, stored)) return;
        if (this.closed) return;
        await this.storage.write(this.key, encodeEnvelope(envelope));
        // What this page has said is now said. What is in the record besides
        // that is somebody else's, and this page still does not speak for it.
        this.rebase(envelope.revision, fields);
    }
}

export const createDraftWriter = (storage: DraftStorage, key: string, scope: DraftScope): DraftWriter =>
    new DraftWriter(storage, key, scope);
