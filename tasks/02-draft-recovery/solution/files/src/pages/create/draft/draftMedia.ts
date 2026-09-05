import { GalleryItemSchemaOutput } from "../schema";
import { DurableGalleryItem } from "./draftTypes";

/**
 * What can and cannot cross a reload.
 *
 * A `File` handed to the page by a file picker exists only for as long as that
 * page does, and so does the object URL minted from it. Neither can be written
 * down in a way a later page could use, so neither is written down at all. A
 * media field therefore survives only when it already has an address the
 * browser can fetch again on its own.
 */

const TRANSIENT_URL = /^(blob:|data:)/i;

/** True for anything whose lifetime is bound to the page that produced it. */
export function isTransientValue(value: unknown): boolean {
    if (value == null) return false;
    if (typeof value === "string") return TRANSIENT_URL.test(value);
    if (typeof Blob !== "undefined" && value instanceof Blob) return true;
    if (typeof FileList !== "undefined" && value instanceof FileList) return true;
    if (typeof value === "object") {
        const named = value as { name?: unknown; size?: unknown; lastModified?: unknown };
        // A File-like object from a non-standard picker.
        if (typeof named.size === "number" && typeof named.name === "string" && "lastModified" in named) return true;
    }
    return false;
}

/**
 * A URL the form is holding that a later page can still fetch, or nothing.
 * Used for the flyer and the waiver, both of which accept either a `File` from
 * a picker or an address already on the server.
 */
export function durableUrl(value: unknown): string | undefined {
    if (typeof value !== "string") return undefined;
    if (!value) return undefined;
    return TRANSIENT_URL.test(value) ? undefined : value;
}

/**
 * Reduce the gallery to the entries a later page could show.
 *
 * Order and identity are preserved for the entries that survive, so a reload
 * looks like the same gallery with the not-yet-uploaded pictures missing —
 * rather than the gallery the event started with, which is what happens when
 * the field is simply left out of the draft.
 */
export function durableGallery(items: GalleryItemSchemaOutput[] | undefined): DurableGalleryItem[] {
    if (!Array.isArray(items)) return [];
    const durable: DurableGalleryItem[] = [];
    for (const item of items) {
        const small = durableUrl(item.urls?.small);
        const large = durableUrl(item.urls?.large);
        if (!small && !large) continue;
        durable.push({
            id: item.id,
            ...(item.type ? { type: item.type } : {}),
            urls: { small: small ?? (large as string), large: large ?? (small as string) },
        });
    }
    return durable;
}

/** Turn a stored gallery entry back into the shape the form works with. */
export function restoreGallery(items: unknown): GalleryItemSchemaOutput[] {
    if (!Array.isArray(items)) return [];
    const restored: GalleryItemSchemaOutput[] = [];
    for (const raw of items) {
        if (!raw || typeof raw !== "object") continue;
        const item = raw as DurableGalleryItem;
        const small = durableUrl(item.urls?.small);
        const large = durableUrl(item.urls?.large);
        if (!small && !large) continue;
        restored.push({
            id: String(item.id ?? `${small ?? large}`),
            ...(item.type ? { type: item.type as GalleryItemSchemaOutput["type"] } : {}),
            urls: { small: small ?? (large as string), large: large ?? (small as string) },
        } as GalleryItemSchemaOutput);
    }
    return restored;
}
