/**
 * Graded rules: the parts of the form that a section of its own owns.
 *
 * Every test drives the app through its own controls and compares what the page
 * ends up showing against an independent model of the specification. No test
 * imports a candidate module, inspects a type, or looks for a name.
 *
 * The gallery and the questions list are both owned by sections beside the form
 * rather than by an input on it, and both are lists: a draft has to carry which
 * entries there are, in which order, and has to carry them from a page that was
 * torn down while the section still had the user's attention.
 */
import { beforeAll, describe, expect, it } from "vitest";
import { check } from "../model/check";
import { primeBaselines } from "../model/baselines";
import { OK, create, duplicateSolstice, editEquinox, editSolstice } from "./common";

beforeAll(async () => {
    await primeBaselines([
        { mode: "create", user: "ada", questions: true },
        { mode: "edit", user: "ada", eventId: "event-solstice", questions: true },
        { mode: "edit", user: "ada", eventId: "event-equinox", questions: true },
        { mode: "duplicate", user: "ada", eventId: "event-solstice", questions: true },
    ]);
}, 300000);

describe("R3 the gallery is a list, not a picture", () => {
    it("keeps the pictures that have addresses and drops the ones that do not", async () => {
        const { problems, observed } = await check(
            [editSolstice, { do: "addPhoto" }, { do: "removePhoto", index: 0 }, { do: "reload" }],
            { withGallery: true }
        );
        expect(problems).toEqual(OK);
        expect(observed.transient).toEqual([]);
    });

    it("remembers a gallery someone emptied, across two pages", async () => {
        // Emptied on one page, and the second reload has to find it still
        // empty: an empty list is something the user did, not a field the
        // draft has nothing to say about.
        const { problems } = await check(
            [
                editSolstice,
                { do: "removePhoto", index: 0 },
                { do: "reload" },
                { do: "removePhoto", index: 0 },
                { do: "type", value: "No Pictures Please" },
                { do: "reload" },
            ],
            { withGallery: true }
        );
        expect(problems).toEqual(OK);
    });

    it("carries the gallery of a duplicate without the picture from disk", async () => {
        const { problems, observed } = await check(
            [
                duplicateSolstice,
                { do: "addPhoto" },
                { do: "removePhoto", index: 0 },
                { do: "typeRun", values: ["Copy With Pictures"] },
                { do: "reload" },
            ],
            { withGallery: true }
        );
        expect(problems).toEqual(OK);
        expect(observed.transient).toEqual([]);
    });
});

describe("R11 work that a section of its own put into the form", () => {
    it("brings back a question written in the questions section", async () => {
        const { problems } = await check([create, { do: "addQuestion", text: "Any allergies?" }, { do: "reload" }], {
            withQuestions: true,
        });
        expect(problems).toEqual(OK);
    });

    it("adds to the questions the event already had rather than replacing them", async () => {
        const { problems } = await check(
            [editSolstice, { do: "addQuestion", text: "Arriving by bike?" }, { do: "reload" }],
            { withQuestions: true }
        );
        expect(problems).toEqual(OK);
    });

    it("keeps which questions there are and the order they were in", async () => {
        // Two written, then the event's own first one taken away. What comes
        // back has to be the list as the section left it: same entries, same
        // order, the removed one gone. A draft that keeps the list by index, or
        // rebuilds it from what it happens to hold, gets a different answer.
        const { problems } = await check(
            [
                editSolstice,
                { do: "addQuestion", text: "Arriving by bike?" },
                { do: "addQuestion", text: "Staying for dinner?" },
                { do: "removeQuestion", index: 0 },
                { do: "reload" },
            ],
            { withQuestions: true }
        );
        expect(problems).toEqual(OK);
    });

    it("does not lose a question written a moment before the page went away", async () => {
        // Nothing here waits: the question is written and the page is torn down
        // while whatever groups the writes is still holding on to it. A page's
        // last write has to be of the form as it is, not of the form as it was
        // when the write was scheduled.
        const { problems } = await check(
            [editSolstice, { do: "addQuestion", text: "Anything we should know?", now: true }, { do: "reload" }],
            { withQuestions: true }
        );
        expect(problems).toEqual(OK);
    });

    it("carries three sections' work out of one page that went away", async () => {
        // A question, a picture taken out of the gallery and the title, all
        // changed with nothing settling in between, and then the page goes.
        // Sections owning part of the form write into the same draft, so one
        // record has to arrive with all three; a writer that sends each
        // section's own slice leaves whichever came first behind.
        const { problems, observed } = await check(
            [
                editSolstice,
                { do: "addQuestion", text: "Bringing a plus two?", now: true },
                { do: "removePhoto", index: 0, now: true },
                { do: "typeRun", values: ["Solstice, All At Once"] },
                { do: "reload" },
            ],
            { withQuestions: true, withGallery: true }
        );
        expect(problems).toEqual(OK);
        expect(observed.transient).toEqual([]);
    });

    it("keeps a question written while the store was still answering", async () => {
        // The stored draft arrives after the user has already written a
        // question of their own on this page. What was found has to be applied
        // to the fields nobody touched -- the title here -- without rolling the
        // section back, and what the user wrote has to be saved on top of it.
        const { problems } = await check(
            [
                editEquinox,
                { do: "type", value: "Equinox Stored" },
                { do: "slowReads", ms: 5000 },
                { do: "reload" },
                { do: "addQuestion", text: "Written While Waiting" },
                { do: "reload" },
            ],
            { withQuestions: true }
        );
        expect(problems).toEqual(OK);
    });

    it("keeps a question, a picture from disk and an emptied gallery in one draft", async () => {
        const { problems, observed } = await check(
            [
                editSolstice,
                { do: "addQuestion", text: "Arriving by bike?" },
                { do: "uploadFlyer" },
                { do: "removePhoto", index: 0 },
                { do: "removePhoto", index: 0 },
                { do: "reload" },
            ],
            { withQuestions: true, withGallery: true }
        );
        expect(problems).toEqual(OK);
        expect(observed.transient).toEqual([]);
    });

    it("leaves no questions behind after the draft is discarded", async () => {
        const { problems } = await check(
            [create, { do: "addQuestion", text: "Never Mind" }, { do: "discard" }, { do: "reload" }],
            { withQuestions: true }
        );
        expect(problems).toEqual(OK);
    });
});
