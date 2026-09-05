/**
 * What the graded files share.
 *
 * The rules are split across six files on purpose. Every page this suite opens
 * leaves something behind — a module registry, a rendered tree, an animation
 * frame still rescheduling itself — and fifty of them in one process is more
 * than the sandbox's memory. Six files, one worker at a time, means each part
 * starts in a process that has never opened a page.
 *
 * Nothing in here is a scenario. The scenarios are cross products of the
 * situations the requirements describe — which flow, which account, what the
 * store already held, when the page went away, what the media fields were
 * holding at that moment, and whether a field was cleared or merely absent —
 * and they are written out in the files that grade them.
 */
import type { Action } from "../harness/script";

/** No problems: what every comparison against the model should come back with. */
export const OK: string[] = [];

export const create: Action = { do: "open", mode: "create" };
export const editSolstice: Action = { do: "open", mode: "edit", eventId: "event-solstice" };
export const editEquinox: Action = { do: "open", mode: "edit", eventId: "event-equinox" };
export const duplicateSolstice: Action = { do: "open", mode: "duplicate", eventId: "event-solstice" };

/** Where the current release keeps a draft, for seeding one directly. */
export const currentKey = (user: string, mode: string, event = "new") => `ExampleCo:draft:event:${user}:${mode}:${event}`;

/** Where the release before it did. */
export const oldKey = (user: string, mode: string) => `ExampleCo:draft:event:${user}:${mode}`;
