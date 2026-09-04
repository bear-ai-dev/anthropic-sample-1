import { CreateEventSchemaInput } from "../schema";
import { durableGallery, durableUrl, isTransientValue, restoreGallery } from "./draftMedia";
import { DurableFields } from "./draftTypes";

/**
 * Fields that are copied straight through. Anything not listed is either
 * derived, transient, or owned by a sub-form that is not part of the event
 * being authored — `currentTicket` is the ticket editor's scratch space and
 * has no business outliving the page.
 */
const PLAIN_FIELDS = [
    "name",
    "description",
    "dateStart",
    "dateEnd",
    "location",
    "revealAddress",
    "visibility",
    "campus",
    "hostId",
    "hostType",
    "coHosts",
    "groupCoHost",
    "eventType",
    "enableSimpleRSVP",
    "requireGuestApproval",
    "maxCapacity",
    "publicLink",
    "videoUrl",
    "effect",
    "color",
    "settings",
    "tickets",
    "questionnaires",
    "musicTrack",
] as const;

/** Deep copy through JSON, dropping anything JSON cannot carry. */
function plainCopy<T>(value: T): T | undefined {
    try {
        const encoded = JSON.stringify(value);
        return encoded === undefined ? undefined : (JSON.parse(encoded) as T);
    } catch {
        return undefined;
    }
}

/**
 * Project the live form onto what can be written down.
 *
 * A field is omitted rather than nulled when its current value cannot survive,
 * because omission means "no opinion, use the flow's own value" while null
 * would mean "the user removed this".
 */
export function toDurableFields(values: CreateEventSchemaInput): DurableFields {
    const fields: Record<string, unknown> = {};

    for (const field of PLAIN_FIELDS) {
        const value = (values as Record<string, unknown>)[field];
        if (value === undefined) continue;
        if (isTransientValue(value)) continue;
        const copied = plainCopy(value);
        if (copied === undefined) continue;
        fields[field] = copied;
    }

    fields.gallery = durableGallery(values.gallery as never);

    const flyer = durableUrl(values.flyer);
    if (flyer !== undefined) fields.flyer = flyer;

    if (values.waiverPdf === null) {
        fields.waiverPdf = null;
    } else {
        const waiver = durableUrl(values.waiverPdf);
        if (waiver !== undefined) fields.waiverPdf = waiver;
    }

    return fields as DurableFields;
}

/**
 * Rebuild the form's values from a draft.
 *
 * `base` is what the flow would show with no draft at all. Fields the draft
 * carries replace it; fields it does not carry are left as they are, which is
 * how a picture that could not be written down comes back as the event's own
 * rather than as a broken reference.
 */
export function applyDurableFields(base: CreateEventSchemaInput, fields: DurableFields): CreateEventSchemaInput {
    const merged: Record<string, unknown> = { ...(base as Record<string, unknown>) };
    const source = fields as Record<string, unknown>;

    for (const field of PLAIN_FIELDS) {
        if (!(field in source)) continue;
        const value = source[field];
        if (value === undefined) continue;
        merged[field] = value;
    }

    if ("gallery" in source) merged.gallery = restoreGallery(source.gallery);
    if (typeof source.flyer === "string" && durableUrl(source.flyer)) merged.flyer = source.flyer;
    if ("waiverPdf" in source) {
        const waiver = source.waiverPdf;
        merged.waiverPdf = waiver === null ? null : (durableUrl(waiver) ?? merged.waiverPdf);
    }

    return merged as CreateEventSchemaInput;
}

/**
 * What this page has done to the form since the state it last wrote down.
 *
 * Needed because a page is not the only thing writing its draft: the key names
 * an account and a flow, so a second tab of the same flow is editing the same
 * record. Saving the whole projection would replace that tab's work with this
 * page's idea of it, and this page's idea was formed before that work existed.
 * A page may only speak for what it has actually changed.
 *
 * `unset` is the other half of that, and it is what keeps the media rule
 * intact. A field that has dropped out of the projection because its value can
 * no longer be written down — a picture whose only address dies with the page
 * holding it — is a field this page has changed, and the change is that there
 * is nothing to say. That has to be recorded as the field going away, not as
 * the field keeping the value it had before, and not as null: absence falls
 * back to what the flow shows on its own, and null would claim the user
 * cleared it.
 */
export interface DraftPatch {
    set: DurableFields;
    unset: string[];
}

export function patchBetween(base: DurableFields, next: DurableFields): DraftPatch {
    const from = base as Record<string, unknown>;
    const to = next as Record<string, unknown>;
    const set: Record<string, unknown> = {};
    const unset: string[] = [];

    for (const field of Object.keys(to)) {
        if (to[field] === undefined) continue;
        if (field in from && fingerprint(from[field]) === fingerprint(to[field])) continue;
        set[field] = to[field];
    }
    for (const field of Object.keys(from)) {
        if (from[field] === undefined) continue;
        if (field in to && to[field] !== undefined) continue;
        unset.push(field);
    }

    return { set: set as DurableFields, unset };
}

/** Lay a patch over a record, leaving every field it says nothing about. */
export function applyPatch(fields: DurableFields, patch: DraftPatch): DurableFields {
    const merged: Record<string, unknown> = { ...(fields as Record<string, unknown>), ...patch.set };
    for (const field of patch.unset) delete merged[field];
    return merged as DurableFields;
}

/** True when a patch would leave the record exactly as it found it. */
export function patchIsEmpty(patch: DraftPatch): boolean {
    return Object.keys(patch.set).length === 0 && patch.unset.length === 0;
}

/** Stable text for comparing two projections, insensitive to key order. */
export function fingerprint(value: unknown): string {
    if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
    if (Array.isArray(value)) return `[${value.map(fingerprint).join(",")}]`;
    const entries = Object.entries(value as Record<string, unknown>)
        .filter(([, v]) => v !== undefined)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${fingerprint(v)}`).join(",")}}`;
}
