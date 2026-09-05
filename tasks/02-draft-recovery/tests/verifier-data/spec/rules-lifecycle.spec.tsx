/**
 * Graded rules: records the previous release left, and when a draft stops
 * being one.
 *
 * Every test drives the app through its own controls and compares what the page
 * ends up showing against an independent model of the specification. No test
 * imports a candidate module, inspects a type, or looks for a name.
 *
 * The old key names an account and a flow and no event, so which flow the page
 * is in decides whether the record can be trusted at all -- and the flows where
 * it can are also the flows where submitting and discarding have to leave
 * nothing behind, including nothing of the old record.
 */
import { beforeAll, describe, expect, it } from "vitest";
import { check } from "../model/check";
import { primeBaselines } from "../model/baselines";
import { OK, create, duplicateSolstice, editEquinox, editSolstice } from "./common";

beforeAll(async () => {
    await primeBaselines([
        { mode: "create", user: "ada" },
        { mode: "create", user: "grace" },
        { mode: "edit", user: "ada", eventId: "event-solstice" },
        { mode: "edit", user: "ada", eventId: "event-equinox" },
        { mode: "duplicate", user: "ada", eventId: "event-solstice" },
    ]);
}, 300000);

describe("R5 records written by the previous release", () => {
    it("opens a draft left by the old format", async () => {
        const { problems } = await check([
            { do: "seedLegacy", user: "ada", mode: "create", fields: { name: "Left Over", campus: "" } },
            create,
        ]);
        expect(problems).toEqual(OK);
    });

    it("keeps the old draft after two reloads, in the current format", async () => {
        const { problems } = await check([
            { do: "seedLegacy", user: "ada", mode: "create", fields: { name: "Left Over", campus: "" } },
            create,
            { do: "reload" },
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
    });

    it("does not apply an old record to an event it cannot name", async () => {
        // The old key said only which account and which flow. There is no
        // saying which event an old edit draft belonged to, so it is not one.
        const { problems } = await check([
            { do: "seedLegacy", user: "ada", mode: "edit", fields: { name: "Ghost Of Some Event" } },
            editSolstice,
        ]);
        expect(problems).toEqual(OK);
    });

    it("applies an old record in the duplicate flow, which names no event either", async () => {
        // A duplicate authors a new event, so there is only ever one of these
        // per account and the old key is not ambiguous about it.
        const { problems } = await check([
            { do: "seedLegacy", user: "ada", mode: "duplicate", fields: { name: "Copied Long Ago" } },
            duplicateSolstice,
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
    });

    it("prefers a draft in the current format over an old one beside it", async () => {
        const { problems } = await check([
            create,
            { do: "type", value: "Current" },
            { do: "seedLegacy", user: "ada", mode: "create", fields: { name: "Ancient" } },
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
    });

    it("does not let an old record roll back typing done while it was being read", async () => {
        // The store is slow, the only thing in it is the previous release's
        // record, and the user has typed before it arrives. Adopting it must
        // not undo that, and what they typed has to be saved on top of it.
        const { problems } = await check([
            { do: "seedLegacy", user: "ada", mode: "create", fields: { name: "Left Over" } },
            { do: "slowReads", ms: 5000 },
            create,
            { do: "type", value: "Typed While Waiting" },
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
    });
});

describe("R9 when a draft stops being one", () => {
    it("leaves nothing to come back after the event is submitted", async () => {
        const { problems } = await check([
            editEquinox,
            { do: "type", value: "Edited Then Saved" },
            { do: "submit" },
            { do: "open", mode: "edit", eventId: "event-equinox" },
        ]);
        expect(problems).toEqual(OK);
    });

    it("puts the form back where it started when the draft is discarded", async () => {
        const { problems } = await check([create, { do: "type", value: "Never Mind" }, { do: "discard" }]);
        expect(problems).toEqual(OK);
    });

    it("leaves nothing to come back after a discard, media and all", async () => {
        const { problems, observed } = await check(
            [
                create,
                { do: "type", value: "Never Mind" },
                { do: "pickFlyer", index: 1 },
                { do: "addPhoto" },
                { do: "discard" },
                { do: "reload" },
            ],
            { withGallery: true }
        );
        expect(problems).toEqual(OK);
        expect(observed.transient).toEqual([]);
    });

    it("does not resurrect a discarded draft from the old format", async () => {
        const { problems } = await check([
            { do: "seedLegacy", user: "ada", mode: "create", fields: { name: "Left Over" } },
            create,
            { do: "discard" },
            { do: "reload" },
        ]);
        expect(problems).toEqual(OK);
    });

    it("throws away one account's draft without touching another's", async () => {
        const { problems } = await check(
            [
                create,
                { do: "type", value: "Ada's Party" },
                { do: "open", mode: "create", user: "grace" },
                { do: "type", value: "Grace's Party" },
                { do: "open", mode: "create", user: "ada" },
                { do: "discard" },
                { do: "open", mode: "create", user: "grace" },
            ],
            { user: "grace" }
        );
        expect(problems).toEqual(OK);
    });
});
