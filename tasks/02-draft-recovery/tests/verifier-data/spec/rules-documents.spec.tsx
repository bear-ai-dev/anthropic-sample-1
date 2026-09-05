/**
 * Graded rules: the document the form holds, and which one it is.
 *
 * Every test drives the app through its own controls and compares what the page
 * ends up showing against an independent model of the specification. No test
 * imports a candidate module, inspects a type, or looks for a name.
 *
 * The document is the one field where saying nothing and saying "gone" are
 * different answers with different consequences, and where a page can be
 * holding a document and still be holding the wrong one: the address a page
 * mints for a file it was handed means nothing to the page after it.
 */
import { beforeAll, describe, expect, it } from "vitest";
import { check } from "../model/check";
import { primeBaselines } from "../model/baselines";
import { OK, create, editEquinox, editSolstice } from "./common";

beforeAll(async () => {
    await primeBaselines([
        { mode: "create", user: "ada", doc: true },
        { mode: "edit", user: "ada", eventId: "event-solstice", doc: true },
        { mode: "edit", user: "ada", eventId: "event-equinox", doc: true },
    ]);
}, 300000);

describe("R12 a document taken off, and one only just chosen", () => {
    it("remembers that the document was taken off", async () => {
        // Nothing was put in its place, and there is nothing to fall back to:
        // saying nothing about the document would bring the event's own back.
        const { problems, observed } = await check([editSolstice, { do: "removeDoc" }, { do: "reload" }], {
            withDoc: true,
        });
        expect(problems).toEqual(OK);
        expect(observed.doc).toBe("");
    });

    it("brings the event's own document back rather than the one from disk", async () => {
        // The draft cannot carry a file the user chose from disk, so it has
        // nothing to say about the document, and a field it says nothing about
        // shows the event's own. Not an address minted by the page that is now
        // gone -- which looks the same from outside the viewer and is not.
        const { problems, observed } = await check(
            [editSolstice, { do: "uploadDoc" }, { do: "type", value: "Solstice With Terms" }, { do: "reload" }],
            { withDoc: true }
        );
        expect(problems).toEqual(OK);
        expect(observed.doc).not.toBe("");
        expect(observed.transient).toEqual([]);
    });

    it("holds no document at all in a flow that never had one", async () => {
        // The create flow has no document of its own to fall back to, so a
        // draft that wrote down the address of the file chosen from disk shows
        // a document here where there should be none.
        const { problems, observed } = await check(
            [create, { do: "uploadDoc" }, { do: "typeRun", values: ["Terms And Nothing Else"] }, { do: "reload" }],
            { withDoc: true }
        );
        expect(problems).toEqual(OK);
        expect(observed.doc).toBe("");
    });

    it("keeps the removal when a document from disk was chosen first", async () => {
        const { problems } = await check([editSolstice, { do: "uploadDoc" }, { do: "removeDoc" }, { do: "reload" }], {
            withDoc: true,
        });
        expect(problems).toEqual(OK);
    });

    it("keeps a document taken off and a question written beside it", async () => {
        const { problems } = await check(
            [
                editSolstice,
                { do: "removeDoc" },
                { do: "addQuestion", text: "Read the rules?" },
                { do: "type", value: "Solstice, No Waiver" },
                { do: "reload" },
            ],
            { withDoc: true }
        );
        expect(problems).toEqual(OK);
    });

    it("does not lose a document taken off a moment before the page went away", async () => {
        const { problems, observed } = await check(
            [editSolstice, { do: "removeDoc", now: true }, { do: "reload" }],
            { withDoc: true }
        );
        expect(problems).toEqual(OK);
        expect(observed.doc).toBe("");
    });

    it("does not take one event's document off another event's form", async () => {
        // Two events, each with a document of its own. Emptying one draft's
        // says nothing about the other's, and neither draft may hand the other
        // its address.
        const { problems, observed } = await check(
            [editSolstice, { do: "removeDoc" }, { do: "reload" }, editEquinox],
            { withDoc: true }
        );
        expect(problems).toEqual(OK);
        expect(observed.doc).not.toBe("");
    });

    it("gives the event's document back when the draft is discarded", async () => {
        const { problems, observed } = await check(
            [editSolstice, { do: "removeDoc" }, { do: "discard" }, { do: "reload" }],
            { withDoc: true }
        );
        expect(problems).toEqual(OK);
        expect(observed.doc).not.toBe("");
    });
});
