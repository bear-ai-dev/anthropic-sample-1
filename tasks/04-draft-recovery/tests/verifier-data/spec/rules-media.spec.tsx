/**
 * Graded rules: what a draft carries across a teardown, and what it cannot.
 *
 * Every test drives the app through its own controls and compares what the page
 * ends up showing against an independent model of the specification. No test
 * imports a candidate module, inspects a type, or looks for a name.
 *
 * The scenarios are deliberately not one situation each. A picture chosen from
 * the library and then replaced by one from disk, in a flow that started from an
 * event, on a page that went away before anything settled, is one scenario --
 * and every part of it follows from the stated requirements.
 */
import { beforeAll, describe, expect, it } from "vitest";
import { check } from "../model/check";
import { primeBaselines } from "../model/baselines";
import { OK, create, duplicateSolstice, editEquinox, editSolstice } from "./common";

beforeAll(async () => {
    await primeBaselines([
        { mode: "create", user: "ada" },
        { mode: "edit", user: "ada", eventId: "event-solstice" },
        { mode: "edit", user: "ada", eventId: "event-equinox" },
        { mode: "duplicate", user: "ada", eventId: "event-solstice" },
    ]);
}, 300000);

describe("R1 what survives a page that went away", () => {
    it("brings back work that was left in the form", async () => {
        const { problems } = await check([create, { do: "type", value: "Harbour Lights" }, { do: "reload" }]);
        expect(problems).toEqual(OK);
    });

    it("brings back the last of several changes across three reloads", async () => {
        const { problems } = await check([
            create,
            { do: "type", value: "First" },
            { do: "type", value: "Second" },
            { do: "typeRun", values: ["Third"] },
            { do: "reload" },
            { do: "reload" },
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
    });

    it("brings back work left in a duplicate of an event", async () => {
        const { problems } = await check([duplicateSolstice, { do: "type", value: "Solstice, again" }, { do: "reload" }]);
        expect(problems).toEqual(OK);
    });

    it("brings back work in an edit flow whose store also holds something unreadable", async () => {
        const { problems } = await check([
            { do: "seedRaw", key: "ExampleCo:draft:event:user-ada:edit", text: "not a draft at all" },
            editEquinox,
            { do: "type", value: "Equinox Revised" },
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
    });
});

describe("R2 pictures that cannot be written down", () => {
    it("does not bring back a picture chosen from disk", async () => {
        const { problems, observed } = await check([
            editSolstice,
            { do: "uploadFlyer" },
            { do: "type", value: "Solstice II" },
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
        expect(observed.transient).toEqual([]);
    });

    it("brings back a picture that has an address of its own", async () => {
        const { problems } = await check([create, { do: "pickFlyer", index: 2 }, { do: "reload" }]);
        expect(problems).toEqual(OK);
    });

    it("stops speaking for a picture once the one on the form came from disk", async () => {
        // A picture from the library was written down, and then the user put one
        // from disk in its place. The draft now has nothing to say about the
        // flyer, and a field it says nothing about shows the flow's own -- not
        // the library picture from the save before, which is no longer what the
        // form is holding.
        //
        // The picture has to be one the event does not already have, or the
        // right answer and the wrong one are the same address and the scenario
        // proves nothing: the library this flow offers leads with the event's
        // own flyer, so the first indices hand back what the form was already
        // showing.
        const { problems, observed } = await check([
            editSolstice,
            { do: "pickFlyer", index: 3 },
            { do: "uploadFlyer" },
            { do: "type", value: "Solstice, Reshot" },
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
        expect(observed.transient).toEqual([]);
    });

    it("keeps a library picture in a duplicate, and the typing beside it", async () => {
        const { problems } = await check([
            duplicateSolstice,
            { do: "pickFlyer", index: 2 },
            { do: "typeRun", values: ["Copy Of Solstice"] },
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
    });

    it("loses nothing when the page goes away with a picture from disk on the form", async () => {
        // The flyer was replaced and the title typed, and the page was torn
        // down before either had a chance to settle. The title has to be there
        // and the picture must not be.
        const { problems, observed } = await check([
            editSolstice,
            { do: "uploadFlyer", now: true },
            { do: "typeRun", values: ["Went Away Mid-Edit"] },
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
        expect(observed.transient).toEqual([]);
    });
});
