import { createEvent } from "@data/endpoints/event/createEvent";
import { editEvent } from "@data/endpoints/event/editEvent";
import { auth } from "@data/firebase";
import { Event } from "@data/types/event/event";
import { zodResolver } from "@hookform/resolvers/zod";
import {
    buildEventRequestFields,
    buildFlyerObject,
    extractGalleryFilesForUpload,
    handlePostEventSubmission,
} from "@pages/create/utils";
import { getPagePath, printDebug, showToast } from "@util/misc";
import { useMemo, useRef } from "react";
import { FieldErrors, SubmitErrorHandler, SubmitHandler, useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { NavigateFunction, useNavigate, useSearchParams } from "react-router-dom";
import { mutate } from "swr";
import { useCreateEventContext } from "../context/useCreateEventContext";
import { useCreateEventDefaultValues } from "../createEventFormDefaultValues";
import { useEventDraft } from "../draft/useEventDraft";
import {
    createEventSchemaFactory,
    CreateEventSchemaInput,
    CreateEventSchemaOutput,
    EventOriginalDates,
    OriginalTicket,
} from "../schema";

export const useCreateEventForm = () => {
    const { edit, isDuplicate, event, duplicateEvent, user, originalCoHosts, originalGroupCoHost } =
        useCreateEventContext();
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();

    // Use refs to store original dates/tickets on first render
    // Refs are more reliable than useMemo with empty deps for capturing initial values
    // For duplicates, we don't preserve original dates (treat as new event)
    const originalDatesRef = useRef<EventOriginalDates | undefined>(
        edit && event ? { dateStart: event.dateStart, dateEnd: event.dateEnd } : undefined
    );

    const originalTicketsRef = useRef<OriginalTicket[] | undefined>(
        edit && event
            ? event.tickets.map((ticket) => ({
                  id: ticket.id,
                  dateOpen: ticket.dateOpen,
                  dateExpire: ticket.dateExpire,
              }))
            : undefined
    );

    const defaultValues = useCreateEventDefaultValues({
        edit,
        isDuplicate,
        event,
        duplicateEvent,
        userId: user.id,
        coHosts: originalCoHosts,
        groupCoHost: originalGroupCoHost,
    });

    // Memoize the resolver to ensure it's created with the correct original values and doesn't get recreated on every render
    const resolver = useMemo(
        () => zodResolver(createEventSchemaFactory(originalDatesRef.current, false, originalTicketsRef.current)),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        []
    );

    const methods = useForm<CreateEventSchemaInput, unknown, CreateEventSchemaOutput>({
        resolver,
        mode: "onChange",
        defaultValues,
    });

    const draft = useEventDraft(methods);

    const onSubmit: SubmitHandler<CreateEventSchemaOutput> = async (data) => {
        try {
            if (methods.formState.errors) {
                printDebug("CREATE EVENT FORM ERRORS", methods.formState.errors);
            }
            const sidebarParam = searchParams.get("sidebar");
            const submitted = await createOrUpdateEvent(data, navigate, edit, {
                originalCoHosts,
                originalGroupCoHost,
                sidebarParam,
            });
            // The draft exists to survive a page that went away with work still
            // in it. Once the event is on the server there is nothing left to
            // recover, and leaving the record behind would offer the finished
            // event back as unfinished work the next time this flow is opened.
            if (submitted) await draft.clearDraft();
        } catch (e) {
            console.error(e);
            toast.error("Something went wrong");
        }
    };
    const onSubmitError: SubmitErrorHandler<CreateEventSchemaInput> = (e) => {
        console.error(e);
        toast.error(findFirstErrorMessage(e) || "Something went wrong");
    };
    return { methods, draft, onSubmit: methods.handleSubmit(onSubmit, onSubmitError) };
};

interface OriginalCoHostData {
    originalCoHosts: string[];
    originalGroupCoHost: string[];
    sidebarParam: string | null;
}

async function createOrUpdateEvent(
    data: CreateEventSchemaOutput,
    navigate: NavigateFunction,
    isEdit: boolean,
    originalCoHostData: OriginalCoHostData
) {
    printDebug("SUBMITTING", data);
    const authToken = await auth.currentUser?.getIdToken();
    // validation
    if (isEdit && !data.eventId) {
        toast.error("Event ID is required for editing.");
        return false;
    }
    if (!isEdit && data.eventId) {
        toast.error("Event ID is not allowed for creating a new event.");
        return false;
    }

    if (!data.flyer || (data.flyer instanceof FileList && data.flyer.length === 0)) {
        toast.error("Please upload a flyer before submitting the form.");
        return false;
    }

    if (!authToken) {
        toast.error("No authentication token found.");
        return false;
    }

    if (!data.location || !data.dateStart) {
        toast.error("Missing location or start date.");
        return false;
    }

    const flyer = buildFlyerObject(data.flyer);

    const galleryFiles = extractGalleryFilesForUpload(data.gallery);

    try {
        let event: Event;

        if (isEdit) {
            // convert form data to request data
            const requestData = await buildEventRequestFields(data, isEdit);
            console.log("SUBMIT EDIT EVENT", requestData);

            // request edit event
            event = await editEvent(authToken, requestData);
        } else {
            // convert form data to request data
            const requestData = await buildEventRequestFields(data, isEdit);
            console.log("SUBMIT CREATE EVENT", requestData);

            // request create event
            event = await createEvent(authToken, requestData);
        }

        if (!event || !event.id) {
            // creation/update failed
            throw new Error("Event creation failed.");
        }

        mutate(
            (key) => typeof key === "object" && key !== null && "url" in key && key.url === "/users/events",
            undefined,
            { revalidate: true }
        );

        await handlePostEventSubmission(event, data, flyer, galleryFiles, authToken, originalCoHostData);

        // creation/update success
        toast.success(isEdit ? "Event updated!" : "Event created!");
        if (isEdit) {
            const sidebarQuery = originalCoHostData.sidebarParam ? `?sidebar=${originalCoHostData.sidebarParam}` : "";
            navigate(`${getPagePath("event")}/${event.id}${sidebarQuery}`);
        } else {
            navigate(`${getPagePath("create")}/confirmation/${event.id}`);
        }

        return true;
    } catch (error: unknown) {
        console.error("CREATE OR UPDATE EVENT ERROR", error);
        showToast(error);
        return false;
    }
}

/**
 * Recursively finds the first error message in a FieldErrors object.
 * Handles nested objects and arrays.
 */
function findFirstErrorMessage(errors: FieldErrors): string | undefined {
    for (const value of Object.values(errors)) {
        if (!value) continue;

        // Direct FieldError with message
        if (typeof value.message === "string") {
            return value.message;
        }

        // Nested object or array - recurse
        if (typeof value === "object") {
            const nested = findFirstErrorMessage(value as FieldErrors);
            if (nested) return nested;
        }
    }
    return undefined;
}
