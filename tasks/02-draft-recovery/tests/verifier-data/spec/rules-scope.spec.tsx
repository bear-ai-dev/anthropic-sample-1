/**
 * Graded rules: whose draft it is, and what is not a draft at all.
 *
 * Every test drives the app through its own controls and compares what the page
 * ends up showing against an independent model of the specification. No test
 * imports a candidate module, inspects a type, or looks for a name.
 *
 * Scope is a cross product by nature: an account, a flow, and an event. The
 * scenarios walk the pairs that a key built from one or two of the three would
 * confuse, and the last of them do it with a store that also holds something
 * nobody can read.
 */
import { beforeAll, describe, expect, it } from "vitest";
import { perform } from "../harness/script";
import { check } from "../model/check";
import { primeBaselines } from "../model/baselines";
import { OK, create, currentKey, duplicateSolstice, editEquinox, editSolstice, oldKey } from "./common";

beforeAll(async () => {
    await primeBaselines([
        { mode: "create", user: "ada", questions: true },
        { mode: "create", user: "grace" },
        { mode: "edit", user: "ada", eventId: "event-solstice" },
        { mode: "edit", user: "grace", eventId: "event-solstice" },
        { mode: "edit", user: "ada", eventId: "event-equinox" },
        { mode: "duplicate", user: "ada", eventId: "event-solstice", questions: true },
    ]);
}, 300000);

describe("R4 whose draft it is", () => {
    it("does not show one account's draft to another", async () => {
        await perform([create, { do: "type", value: "Ada's Party" }]);
        const { problems } = await check([{ do: "open", mode: "create", user: "grace" }], { user: "grace" });
        expect(problems).toEqual(OK);
    });

    it("does not carry a draft from one flow into another", async () => {
        const { problems } = await check([
            create,
            { do: "type", value: "Something New" },
            { do: "open", mode: "edit", eventId: "event-solstice" },
        ]);
        expect(problems).toEqual(OK);
    });

    it("does not carry a draft from one event into another", async () => {
        const { problems } = await check([editSolstice, { do: "type", value: "Renamed Solstice" }, editEquinox]);
        expect(problems).toEqual(OK);
    });

    it("does not show one account the draft another left on the same event", async () => {
        const { problems } = await check(
            [
                editSolstice,
                { do: "type", value: "Ada Renamed It" },
                { do: "open", mode: "edit", user: "grace", eventId: "event-solstice" },
            ],
            { user: "grace" }
        );
        expect(problems).toEqual(OK);
    });

    it("keeps a duplicate apart from the event it was copied from", async () => {
        const { problems } = await check([
            duplicateSolstice,
            { do: "type", value: "Solstice, again" },
            editSolstice,
        ]);
        expect(problems).toEqual(OK);
    });

    it("keeps a duplicate apart from the create flow it shares a route with", async () => {
        // Both are authoring a new event, and they are not the same draft. The
        // question makes it a section's work as well as the title's.
        const { problems } = await check(
            [
                duplicateSolstice,
                { do: "type", value: "Copied Then Left" },
                { do: "addQuestion", text: "Same as last time?" },
                create,
            ],
            { withQuestions: true }
        );
        expect(problems).toEqual(OK);
    });

    it("keeps each account's draft for itself", async () => {
        const { problems } = await check([
            create,
            { do: "type", value: "Ada's Party" },
            { do: "open", mode: "create", user: "grace" },
            { do: "type", value: "Grace's Party" },
            { do: "open", mode: "create", user: "ada" },
        ]);
        expect(problems).toEqual(OK);
    });
});

describe("R6 records that cannot be read", () => {
    it("opens the flow when the store holds something that is not a draft", async () => {
        const { problems } = await check([
            { do: "seedRaw", key: currentKey("user-ada", "create"), text: "}{ not json" },
            { do: "seedRaw", key: oldKey("user-ada", "create"), text: "}{ not json" },
            create,
        ]);
        expect(problems).toEqual(OK);
    });

    it("opens the flow when the record is from a release this one does not know", async () => {
        const future = JSON.stringify({
            version: 99,
            revision: 4,
            savedAt: 1,
            scope: { user: "ada", mode: "create" },
            fields: { name: "From The Future" },
        });
        const { problems } = await check([
            { do: "seedRaw", key: currentKey("user-ada", "create"), text: future },
            { do: "seedRaw", key: oldKey("user-ada", "create"), text: future },
            create,
        ]);
        expect(problems).toEqual(OK);
    });

    it("still saves after finding something unreadable, and keeps saving", async () => {
        const { problems } = await check([
            { do: "seedRaw", key: currentKey("user-ada", "create"), text: "[]" },
            { do: "seedRaw", key: oldKey("user-ada", "create"), text: "[]" },
            create,
            { do: "type", value: "Written Anyway" },
            { do: "reload" },
            { do: "typeRun", values: ["Written Again"] },
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
    });

    // A fifth case stood here and has been dropped rather than repaired: an
    // unreadable current cell beside a readable old one, graded as falling back
    // to the old record. Two readings of that are defensible -- unreadable is
    // "no draft, look further" or it is "something is here, leave it alone" --
    // and the workspace settles it the other way from the way this graded.
    // `loadAndClearResumeStateFromStorage` reads `current ?? legacy`, so a
    // current cell holding text that will not parse yields nothing at all and
    // never reaches the old key; `test/ticketResumeStore.test.ts` pins that.
    // A rule whose only route points away from it is not difficulty, it is a
    // coin flip.
});
