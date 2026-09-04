import { DraftEnvelope, DraftScope, DurableFields } from "./draftTypes";

/** Bumped whenever the durable shape changes in a way older records lack. */
export const DRAFT_FORMAT_VERSION = 2;

export function makeEnvelope(scope: DraftScope, revision: number, fields: DurableFields): DraftEnvelope {
    return {
        version: DRAFT_FORMAT_VERSION,
        revision,
        savedAt: Date.now(),
        scope: scope.eventId
            ? { userId: scope.userId, mode: scope.mode, eventId: scope.eventId }
            : { userId: scope.userId, mode: scope.mode },
        fields,
    };
}

export function encodeEnvelope(envelope: DraftEnvelope): string {
    return JSON.stringify(envelope);
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === "object" && !Array.isArray(value);
}

/**
 * Read a stored record.
 *
 * Storage is shared, long lived, and outside this code's control: it can hold
 * text that is not JSON, JSON that is not a record, a record from a future
 * release, or a record that belongs to somebody else. All of those are treated
 * the same way — as no draft — because the alternative is a page that will not
 * open until the user knows how to clear their browser storage.
 */
export function decodeEnvelope(raw: string | null, expected: DraftScope): DraftEnvelope | null {
    if (typeof raw !== "string" || raw.length === 0) return null;

    let parsed: unknown;
    try {
        parsed = JSON.parse(raw);
    } catch {
        return null;
    }
    if (!isRecord(parsed)) return null;

    // A record this release does not know how to read is no better than none:
    // the previous format lives under its own key, and a later one may mean
    // anything at all.
    const version = parsed.version;
    if (version !== DRAFT_FORMAT_VERSION) return null;

    const scope = parsed.scope;
    if (!isRecord(scope)) return null;
    if (scope.userId !== expected.userId) return null;
    if (scope.mode !== expected.mode) return null;
    if ((scope.eventId ?? null) !== (expected.eventId ?? null)) return null;

    if (!isRecord(parsed.fields)) return null;

    const revision = typeof parsed.revision === "number" && Number.isFinite(parsed.revision) ? parsed.revision : 0;
    const savedAt = typeof parsed.savedAt === "number" && Number.isFinite(parsed.savedAt) ? parsed.savedAt : 0;

    return {
        version,
        revision,
        savedAt,
        scope: expected,
        fields: parsed.fields as DurableFields,
    };
}

/** True when `incoming` should replace what is already stored. */
export function supersedes(incoming: DraftEnvelope, stored: DraftEnvelope | null): boolean {
    if (!stored) return true;
    return incoming.revision > stored.revision;
}

