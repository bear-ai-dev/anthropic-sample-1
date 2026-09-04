import { DraftScope, DurableFields } from "./draftTypes";

/**
 * Reading drafts written before this format existed.
 *
 * The previous release stored a bare object of form values with no version, no
 * revision and no scope beyond what was in the key. Those records are still in
 * people's browsers, so they are read once, folded into the current shape, and
 * then superseded by the first save the page makes.
 */

const LEGACY_FIELDS = [
    "name",
    "dateStart",
    "dateEnd",
    "visibility",
    "campus",
    "eventType",
    "enableSimpleRSVP",
    "requireGuestApproval",
    "maxCapacity",
    "publicLink",
] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === "object" && !Array.isArray(value);
}

/**
 * Recognise a pre-versioning record.
 *
 * Anything carrying a `version` belongs to the current format and is not our
 * business; anything that is not a record of recognisable fields is not a
 * draft at all and is ignored rather than half applied.
 */
export function decodeLegacy(raw: string | null, scope: DraftScope): DurableFields | null {
    if (scope.mode === "edit") return null;
    if (typeof raw !== "string" || raw.length === 0) return null;

    let parsed: unknown;
    try {
        parsed = JSON.parse(raw);
    } catch {
        return null;
    }
    if (!isRecord(parsed)) return null;
    if ("version" in parsed || "fields" in parsed) return null;

    const fields: Record<string, unknown> = {};
    let recognised = 0;
    for (const field of LEGACY_FIELDS) {
        if (!(field in parsed)) continue;
        const value = parsed[field];
        if (value === undefined) continue;
        recognised += 1;
        fields[field] = value;
    }

    return recognised > 0 ? (fields as DurableFields) : null;
}
