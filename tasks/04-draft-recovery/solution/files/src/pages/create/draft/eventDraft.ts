import { DRAFT_KEY_PREFIX } from "@data/storage/draftStorage";
import { DraftMode, DraftScope } from "./draftTypes";

export type { DraftMode, DraftScope } from "./draftTypes";

export const draftModeFor = (edit: boolean, isDuplicate: boolean): DraftMode =>
    isDuplicate ? "duplicate" : edit ? "edit" : "create";

/**
 * Build the scope a page is authoring in.
 *
 * Only the edit flow is tied to an event. A duplicate starts from one but
 * produces a new event, so it shares no draft with the event it copies, and
 * none with the plain create flow either.
 */
export function draftScopeFor(params: {
    edit: boolean;
    isDuplicate: boolean;
    userId: string;
    eventId?: string;
}): DraftScope {
    const mode = draftModeFor(params.edit, params.isDuplicate);
    return mode === "edit" && params.eventId
        ? { userId: params.userId, mode, eventId: params.eventId }
        : { userId: params.userId, mode };
}

const encode = (part: string) => encodeURIComponent(part);

/**
 * Where a draft lives.
 *
 * Every component of the scope is in the key, so a draft cannot be read by an
 * account, a flow, or an event other than the one that wrote it. Components
 * are escaped so that an identifier containing a separator cannot be made to
 * look like a different scope.
 */
export const eventDraftKey = (scope: DraftScope): string =>
    `${DRAFT_KEY_PREFIX}event:${encode(scope.userId)}:${encode(scope.mode)}:${encode(scope.eventId ?? "new")}`;

/**
 * Where the previous release put the same draft. Keyed by account and flow
 * only, which is why it can only be trusted for flows that have exactly one
 * draft per account.
 */
export const legacyEventDraftKey = (scope: DraftScope): string | null =>
    scope.mode === "edit" ? null : `${DRAFT_KEY_PREFIX}event:${encode(scope.userId)}:${encode(scope.mode)}`;

export const sameScope = (a: DraftScope, b: DraftScope): boolean =>
    a.userId === b.userId && a.mode === b.mode && (a.eventId ?? null) === (b.eventId ?? null);
