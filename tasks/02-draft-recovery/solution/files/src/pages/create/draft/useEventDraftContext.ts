import { createContext, useContext } from "react";
import { EventDraft } from "./useEventDraft";

export const EventDraftContext = createContext<EventDraft>({
    discardDraft: () => {},
    clearDraft: async () => {},
});

export const useEventDraftContext = () => useContext(EventDraftContext);
