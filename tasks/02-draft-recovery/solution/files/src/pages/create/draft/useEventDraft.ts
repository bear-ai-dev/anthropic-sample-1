import { DraftStorage, resolveDraftStorage } from "@data/storage/draftStorage";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { UseFormReturn } from "react-hook-form";
import { useDebouncedCallback } from "use-debounce";
import { useCreateEventContext } from "../context/useCreateEventContext";
import { CreateEventSchemaInput, CreateEventSchemaOutput } from "../schema";
import { decodeEnvelope } from "./draftEnvelope";
import { applyDurableFields, fingerprint, toDurableFields } from "./draftFields";
import { DraftScope, DurableFields } from "./draftTypes";
import { createDraftWriter } from "./draftWriter";
import { draftScopeFor, eventDraftKey, legacyEventDraftKey } from "./eventDraft";
import { decodeLegacy } from "./legacyDraft";

const SAVE_DEBOUNCE_MS = 500;

export interface EventDraft {
    /** Throw the stored draft away and put the form back as it started. */
    discardDraft: () => void;
    /** Remove the draft because the event it belonged to has been submitted. */
    clearDraft: () => Promise<void>;
}

interface LoadResult {
    fields: DurableFields;
    revision: number;
    upgraded: boolean;
}

/**
 * Find the draft for a scope.
 *
 * The current format wins outright. Only when there is nothing there does the
 * previous release's record get a look, so a draft that has already been saved
 * once cannot be undone by the older copy still sitting beside it.
 */
async function loadDraft(storage: DraftStorage, scope: DraftScope): Promise<LoadResult | null> {
    const current = decodeEnvelope(await storage.read(eventDraftKey(scope)), scope);
    if (current) return { fields: current.fields, revision: current.revision, upgraded: false };

    const legacyKey = legacyEventDraftKey(scope);
    if (!legacyKey) return null;
    const legacy = decodeLegacy(await storage.read(legacyKey), scope);
    if (!legacy) return null;
    return { fields: legacy, revision: 0, upgraded: true };
}

/**
 * Keeps the event form recoverable across a reload.
 *
 * Three things are load bearing. The draft is written to storage and nowhere
 * else, because a page that has been thrown away takes its memory with it.
 * Restoring merges into what the flow would otherwise show, and leaves alone
 * anything the user has already touched, because a slow read must not undo
 * typing that happened while it was in flight. And a form that matches the
 * flow's own starting point is not a draft at all, so it is removed rather
 * than written.
 */
export const useEventDraft = (
    methods: UseFormReturn<CreateEventSchemaInput, unknown, CreateEventSchemaOutput>
): EventDraft => {
    const { edit, isDuplicate, event, user } = useCreateEventContext();

    const scope = useMemo(
        () => draftScopeFor({ edit, isDuplicate, userId: user.id, eventId: event?.id }),
        [edit, isDuplicate, user.id, event?.id]
    );
    const key = eventDraftKey(scope);
    const legacyKey = legacyEventDraftKey(scope);
    const storage = useMemo(() => resolveDraftStorage(), []);
    const writer = useMemo(() => createDraftWriter(storage, key, scope), [storage, key, scope]);

    /** What this flow shows with no draft at all. Captured before any restore. */
    const baseline = useRef<CreateEventSchemaInput | null>(null);
    if (baseline.current === null) baseline.current = methods.getValues();
    const baselineFields = useMemo(() => toDurableFields(baseline.current as CreateEventSchemaInput), []);
    const baselinePrint = useMemo(() => fingerprint(baselineFields), [baselineFields]);

    /** Saves wait for the restore attempt, but are not thrown away by it. */
    const restored = useRef(false);
    const editedWhileLoading = useRef(false);
    const applyingRestore = useRef(false);
    const staleKeys = useMemo(() => (legacyKey ? [legacyKey] : []), [legacyKey]);

    const persist = useDebouncedCallback(() => {
        const fields = toDurableFields(methods.getValues());
        if (fingerprint(fields) === baselinePrint) {
            void writer.remove(staleKeys);
            return;
        }
        writer.reopen();
        void writer.save(fields);
    }, SAVE_DEBOUNCE_MS);

    useEffect(() => {
        let live = true;
        // Until the read comes back, what this page is working from is the
        // flow's own starting point at no revision at all. Set before the read
        // so that typing which beats it still counts as this page's change.
        writer.rebase(0, baselineFields);
        void (async () => {
            let loaded: LoadResult | null = null;
            try {
                loaded = await loadDraft(storage, scope);
            } catch {
                loaded = null;
            }
            if (!live) return;
            if (loaded) {
                const merged = applyDurableFields(baseline.current as CreateEventSchemaInput, loaded.fields);
                // What this page is working from: the revision it found, and
                // that record laid over the flow's own starting point. Taken
                // from the record rather than from the live form, because the
                // user may have typed while the read was in flight and that
                // typing is this page's change, not part of what it started
                // from.
                writer.rebase(loaded.revision, toDurableFields(merged));
                // Anything the user has already touched stays as they left it.
                // A read that took a while must not roll typing backwards.
                applyingRestore.current = true;
                methods.reset(merged, { keepDirtyValues: true });
                applyingRestore.current = false;
            }
            restored.current = true;
            // Work done while the read was in flight was not saved then,
            // because it would have been written against a revision this page
            // had not seen yet. It is saved now, on top of what was found.
            if (editedWhileLoading.current || loaded?.upgraded) {
                editedWhileLoading.current = false;
                writer.reopen();
                persist();
            }
        })();
        return () => {
            live = false;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key]);

    useEffect(() => {
        const subscription = methods.watch((_values, info) => {
            if (applyingRestore.current) return;
            // The ticket editor's scratch row is not part of the event.
            if (info?.name === "currentTicket") return;
            if (!restored.current) {
                editedWhileLoading.current = true;
                return;
            }
            persist();
        });
        return () => subscription.unsubscribe();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [persist]);

    /**
     * A page can be closed between one keystroke and the next, and a save that
     * is still waiting on its timer at that moment has not been made. Grouping
     * writes is only safe if the group is issued when there is no later.
     */
    useEffect(() => {
        const flush = () => {
            if (persist.isPending()) persist.flush();
        };
        const onHidden = () => {
            if (document.visibilityState === "hidden") flush();
        };
        window.addEventListener("pagehide", flush);
        document.addEventListener("visibilitychange", onHidden);
        return () => {
            window.removeEventListener("pagehide", flush);
            document.removeEventListener("visibilitychange", onHidden);
        };
    }, [persist]);

    const discardDraft = useCallback(() => {
        persist.cancel();
        void writer.remove(staleKeys);
        methods.reset(baseline.current as CreateEventSchemaInput);
        // The form is back where the flow started it, so that is what this page
        // is working from again. Without this, the next thing the user types
        // would look like a change against the discarded draft.
        writer.restart(baselineFields);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [persist, writer, staleKeys, methods, baselineFields]);

    const clearDraft = useCallback(async () => {
        persist.cancel();
        await writer.remove(staleKeys);
    }, [persist, writer, staleKeys]);

    return { discardDraft, clearDraft };
};
