/**
 * Graded rules: when a draft is written, and what happens to writes that cross.
 *
 * Every test drives the app through its own controls and compares what the page
 * ends up showing against an independent model of the specification. No test
 * imports a candidate module, inspects a type, or looks for a name.
 *
 * These are the situations a solver would have to think to arrange: a save
 * still in flight when the next one is issued, a record arriving after the user
 * has already worked on the page, a store that will not take another write, and
 * a page that goes away between one keystroke and the next.
 */
import { beforeAll, describe, expect, it } from "vitest";
import { check } from "../model/check";
import { primeBaselines } from "../model/baselines";
import { OK, create, editSolstice } from "./common";

beforeAll(async () => {
    await primeBaselines([
        { mode: "create", user: "ada" },
        { mode: "edit", user: "ada", eventId: "event-solstice" },
    ]);
}, 300000);

describe("R7 saves that overtake one another", () => {
    it("does not let a slow earlier save undo a later one", async () => {
        const { problems } = await check([
            create,
            { do: "slowFirstWrite", ms: 8000 },
            { do: "typeAndMoveOn", value: "Early" },
            { do: "type", value: "Late" },
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
    });

    it("does not let a slow earlier save undo a section's work either", async () => {
        // The first write is still in flight when the gallery section writes
        // into the same draft. Whichever way the two are ordered on the way out,
        // what is stored at the end has to be the later of them.
        const { problems } = await check(
            [
                editSolstice,
                { do: "slowFirstWrite", ms: 8000 },
                { do: "typeAndMoveOn", value: "Solstice Early" },
                { do: "removePhoto", index: 0 },
                { do: "reload" },
            ],
            { withGallery: true }
        );
        expect(problems).toEqual(OK);
    });

    it("keeps saving after the store refuses a write", async () => {
        const { problems } = await check([
            create,
            { do: "failNextWrite" },
            { do: "typeAndMoveOn", value: "Refused" },
            { do: "type", value: "Accepted" },
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
    });
});

describe("R8 a draft that arrives late", () => {
    it("does not roll back what was typed while the store was slow", async () => {
        const { problems } = await check([
            create,
            { do: "type", value: "Stored Earlier" },
            { do: "slowReads", ms: 5000 },
            { do: "reload" },
            { do: "type", value: "Typed While Waiting" },
        ]);
        expect(problems).toEqual(OK);
    });

    it("saves what was typed while the store was slow", async () => {
        const { problems } = await check([
            create,
            { do: "type", value: "Stored Earlier" },
            { do: "slowReads", ms: 5000 },
            { do: "reload" },
            { do: "type", value: "Typed While Waiting" },
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
    });

    it("does not roll back a picture chosen while the store was slow", async () => {
        // What was stored says the flyer is a library picture; the user has
        // since put one from disk on the form. The record arriving cannot undo
        // that, so this page is showing an address only it can resolve -- which
        // is allowed, because this page is the one holding the file.
        const { problems, observed } = await check([
            editSolstice,
            { do: "pickFlyer", index: 1 },
            { do: "slowReads", ms: 5000 },
            { do: "reload" },
            { do: "uploadFlyer" },
        ]);
        expect(problems).toEqual(OK);
        expect(observed.transient.length).toBeGreaterThan(0);
    });
});

describe("R10 writing for the work rather than for the keystroke", () => {
    it("does not spend a write on every keystroke", async () => {
        // The store will take ten writes of this draft and refuse the rest, and
        // a page that treats each keystroke as a save runs out before the typing
        // does -- so what comes back is what it managed to store rather than
        // what was typed. Any design that writes for the work instead of for
        // the keystroke is nowhere near the limit.
        const { problems } = await check([
            create,
            { do: "storeBudget", writes: 10 },
            {
                do: "typeRun",
                values: [
                    "H",
                    "Ha",
                    "Har",
                    "Harb",
                    "Harbo",
                    "Harbou",
                    "Harbour",
                    "Harbour ",
                    "Harbour L",
                    "Harbour Li",
                    "Harbour Lig",
                    "Harbour Ligh",
                    "Harbour Light",
                    "Harbour Lights",
                    "Harbour Lights ",
                    "Harbour Lights 88",
                ],
            },
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
    });

    it("does not lose what was typed a moment before the page went away", async () => {
        // Nothing here waits for a timer to come round: the page is torn down
        // between one keystroke and the next.
        const { problems } = await check([
            create,
            { do: "typeRun", values: ["Harbour", "Harbour Lights"] },
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
    });

    it("does not bring back work that was discarded before it was ever written", async () => {
        // The second lot of typing has not been written when the draft is
        // thrown away. Whatever gets a page's last writes out of the door must
        // not send this one.
        const { problems } = await check([
            create,
            { do: "type", value: "Never Mind" },
            { do: "typeRun", values: ["Never Mind At All"] },
            { do: "discard" },
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
    });
});
