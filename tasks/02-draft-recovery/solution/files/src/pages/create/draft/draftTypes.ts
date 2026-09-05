import { CreateEventSchemaInput } from "../schema";

/** Which authoring flow a draft belongs to. */
export type DraftMode = "create" | "edit" | "duplicate";

/**
 * Everything that decides which draft a page is looking at. Two pages share a
 * draft only when all three agree: the same account, the same flow, and the
 * same event. Duplicating an event is authoring a new one, so it never carries
 * an event id even though it starts from one.
 */
export interface DraftScope {
    userId: string;
    mode: DraftMode;
    eventId?: string;
}

/** A gallery entry that a fresh page can render without the original file. */
export interface DurableGalleryItem {
    id: string;
    type?: string;
    urls: { small: string; large: string };
}

/**
 * The durable projection of the form.
 *
 * A field that is present here is restored; a field that is absent falls back
 * to whatever the flow would have shown with no draft at all. That distinction
 * carries the media rule: a picture the user selected from disk has no durable
 * representation, so its field is left out rather than written as null, which
 * would wrongly read as "the user cleared it".
 */
export type DurableFields = Partial<{
    name: string;
    description: string;
    dateStart: number;
    dateEnd: number | null;
    location: CreateEventSchemaInput["location"];
    revealAddress: boolean;
    visibility: "everyone" | "private";
    campus: string;
    hostId: string;
    hostType: "user" | "organization";
    coHosts: string[];
    groupCoHost: string[];
    eventType: "rsvpOnly" | "sellTickets";
    enableSimpleRSVP: boolean;
    requireGuestApproval: boolean;
    maxCapacity: number | null;
    publicLink: string;
    videoUrl: string | null;
    effect: CreateEventSchemaInput["effect"];
    color: string;
    settings: CreateEventSchemaInput["settings"];
    tickets: CreateEventSchemaInput["tickets"];
    questionnaires: CreateEventSchemaInput["questionnaires"];
    musicTrack: CreateEventSchemaInput["musicTrack"];
    gallery: DurableGalleryItem[];
    flyer: string;
    waiverPdf: string | null;
}>;

/** The record written to storage. */
export interface DraftEnvelope {
    /** Format of this record. Bumped when the durable shape changes. */
    version: number;
    /**
     * Increases with every save of a given draft. A write carrying a revision
     * no higher than the one already stored is a straggler and is dropped,
     * which is what keeps a slow earlier save from undoing a later one.
     */
    revision: number;
    savedAt: number;
    scope: DraftScope;
    fields: DurableFields;
}