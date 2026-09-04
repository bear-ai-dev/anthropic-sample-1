/**
 * Graded rules: two pages editing one draft.
 *
 * Every test drives the app through its own controls and compares what the page
 * ends up showing against an independent model of the specification. No test
 * imports a candidate module, inspects a type, or looks for a name.
 *
 * A host can have the same event open twice — a second tab, a window left
 * behind on another screen — and both of them are editing one draft, because
 * one draft is what the key names. The store is the only thing the two share,
 * so the store is where they have to be reconciled.
 *
 * Each tab here is a page of its own: its own module graph, so nothing can pass
 * between them except through the store, and its own container, so neither one
 * reads the other's form.
 */
import { beforeAll, describe, expect, it } from "vitest";
import { check } from "../model/check";
import { primeBaselines } from "../model/baselines";
import { OK, editSolstice } from "./common";
import type { Action } from "../harness/script";

beforeAll(async () => {
    await primeBaselines([
        { mode: "create", user: "ada", questions: true, doc: true },
        { mode: "edit", user: "ada", eventId: "event-solstice", questions: true, doc: true },
    ]);
}, 300000);

/** Two tabs of the same event, both open before either has saved anything. */
const twoTabs: Action[] = [
    { do: "openTab", tab: "left", mode: "edit", eventId: "event-solstice" },
    { do: "openTab", tab: "right", mode: "edit", eventId: "event-solstice" },
];

const inLeft: Action = { do: "inTab", tab: "left" };
const inRight: Action = { do: "inTab", tab: "right" };
const closeTabs: Action = { do: "closeTabs" };

describe("R13 two pages editing one draft", () => {
    it("keeps the questions one tab wrote when the other tab saves a title", async () => {
        // The right tab writes a question. The left tab, whose form was built
        // before that question existed, then saves a title. The left tab's
        // record is the newer one, and it is not entitled to say that the
        // questions are what it thinks they are: it never saw them change.
        const { problems } = await check(
            [
                ...twoTabs,
                inRight,
                { do: "addQuestion", text: "Need parking?" },
                inLeft,
                { do: "type", value: "Solstice Party (final)" },
                closeTabs,
                editSolstice,
            ],
            { withQuestions: true }
        );
        expect(problems).toEqual(OK);
    });

    it("keeps the title one tab wrote when the other tab saves questions", async () => {
        // The same situation the other way round, so a candidate cannot pass by
        // treating one field as the one that always wins.
        const { problems } = await check(
            [
                ...twoTabs,
                inLeft,
                { do: "type", value: "Solstice Party (final)" },
                inRight,
                { do: "addQuestion", text: "Need parking?" },
                closeTabs,
                editSolstice,
            ],
            { withQuestions: true }
        );
        expect(problems).toEqual(OK);
    });

    it("keeps a picture one tab removed when the other tab saves a title", async () => {
        // The gallery is written whole, so a tab that takes a picture off is
        // making a change that the other tab's projection would put back.
        const { problems } = await check(
            [
                ...twoTabs,
                inRight,
                { do: "removePhoto", index: 0 },
                inLeft,
                { do: "type", value: "Solstice Rearranged" },
                closeTabs,
                editSolstice,
            ],
            { withGallery: true }
        );
        expect(problems).toEqual(OK);
    });

    it("keeps a document one tab took off when the other tab saves a title", async () => {
        // Taking the document off is a change that has to be written down as
        // one, and it has to survive the other tab's save the same way.
        const { problems } = await check(
            [
                ...twoTabs,
                inRight,
                { do: "removeDoc" },
                inLeft,
                { do: "type", value: "Solstice Without Terms" },
                closeTabs,
                editSolstice,
            ],
            { withDoc: true }
        );
        expect(problems).toEqual(OK);
    });

    it("keeps both tabs' work when each saves twice, in turn", async () => {
        // Every save moves what the tab that made it is working from. A tab
        // that saved once and then saves again must not be carrying its first
        // save's idea of the fields it has not touched since.
        const { problems } = await check(
            [
                ...twoTabs,
                inLeft,
                { do: "type", value: "Solstice One" },
                inRight,
                { do: "addQuestion", text: "Need parking?" },
                inLeft,
                { do: "type", value: "Solstice Two" },
                inRight,
                { do: "addQuestion", text: "Dogs welcome?" },
                closeTabs,
                editSolstice,
            ],
            { withQuestions: true }
        );
        expect(problems).toEqual(OK);
    });

    it("does not let the tab that never touched the title put the old one back", async () => {
        // The right tab is working on questions and has never touched the
        // title, so nothing it ever saves may say anything about the title --
        // including after it has saved onto a record where the title changed
        // under it. A page that takes the record it merged into as its own view
        // of the form passes this once and fails it on the second save, because
        // the second save then reads the other tab's title as a field this page
        // has changed back.
        const { problems } = await check(
            [
                ...twoTabs,
                inRight,
                { do: "addQuestion", text: "Need parking?" },
                inLeft,
                { do: "type", value: "Solstice Renamed" },
                inRight,
                { do: "addQuestion", text: "Dogs welcome?" },
                { do: "addQuestion", text: "Bringing a tent?" },
                closeTabs,
                editSolstice,
            ],
            { withQuestions: true }
        );
        expect(problems).toEqual(OK);
    });

    it("takes a picture out of the record when one tab replaces it from disk", async () => {
        // The right tab writes a library picture down and then puts one from
        // disk in its place, which the draft cannot carry. Its second save has
        // to take the field out of the record rather than leave the library
        // picture there, and the left tab's save must not put it back.
        //
        // This is the half of a patch that says nothing rather than says a
        // value, and it is the half that is easy to leave out: a patch of only
        // the fields that have values is a patch that can never clear one. The
        // picture is one the event does not already have, so the record's wrong
        // answer and the right answer are different addresses.
        const { problems, observed } = await check(
            [
                ...twoTabs,
                inRight,
                { do: "pickFlyer", index: 3 },
                { do: "uploadFlyer" },
                inLeft,
                { do: "type", value: "Solstice Reshot" },
                closeTabs,
                editSolstice,
            ],
            { withQuestions: true }
        );
        expect(problems).toEqual(OK);
        expect(observed.transient).toEqual([]);
    });

    it("hands a third tab everything the first two put in", async () => {
        // Not a reload: a tab opened while the other two are still there. What
        // it finds is the draft, and the draft is both tabs' work.
        const { problems } = await check(
            [
                ...twoTabs,
                inRight,
                { do: "addQuestion", text: "Need parking?" },
                inLeft,
                { do: "type", value: "Solstice Party (final)" },
                { do: "openTab", tab: "third", mode: "edit", eventId: "event-solstice" },
                closeTabs,
                editSolstice,
            ],
            { withQuestions: true }
        );
        expect(problems).toEqual(OK);
    });

    it("lets a tab opened after a save write the whole draft as it found it", async () => {
        // The second tab loaded what the first had already stored, so nothing
        // has moved past it and it is the authority on the whole draft. A
        // candidate that reconciles when there is nothing to reconcile gets a
        // different answer here from one that does not, so this is where the
        // rule is held to firing only when it should.
        const { problems } = await check(
            [
                editSolstice,
                { do: "type", value: "Solstice First" },
                { do: "addQuestion", text: "Need parking?" },
                { do: "openTab", tab: "second", mode: "edit", eventId: "event-solstice" },
                { do: "removeQuestion", index: 0 },
                closeTabs,
                editSolstice,
            ],
            { withQuestions: true }
        );
        expect(problems).toEqual(OK);
    });

    it("does not let one tab's discard bring back what the other tab wrote after it", async () => {
        // Discarding takes the draft away. What the other tab saves next is a
        // new draft, and it starts from the flow rather than from the record
        // that was just thrown away.
        const { problems } = await check(
            [
                ...twoTabs,
                inLeft,
                { do: "type", value: "Solstice Doomed" },
                inRight,
                { do: "discard" },
                inLeft,
                { do: "type", value: "Solstice Revived" },
                closeTabs,
                editSolstice,
            ],
            { withQuestions: true }
        );
        expect(problems).toEqual(OK);
    });

    it("keeps two tabs of the create flow apart from an edit draft of the same account", async () => {
        // Two tabs share a draft only when they are the same flow on the same
        // event. These are not, so neither reconciliation nor overwriting
        // should happen at all.
        const { problems } = await check(
            [
                { do: "openTab", tab: "creating", mode: "create" },
                { do: "openTab", tab: "editing", mode: "edit", eventId: "event-solstice" },
                { do: "inTab", tab: "creating" },
                { do: "type", value: "Something New" },
                { do: "inTab", tab: "editing" },
                { do: "addQuestion", text: "Need parking?" },
                closeTabs,
                editSolstice,
            ],
            { withQuestions: true }
        );
        expect(problems).toEqual(OK);
    });
});
