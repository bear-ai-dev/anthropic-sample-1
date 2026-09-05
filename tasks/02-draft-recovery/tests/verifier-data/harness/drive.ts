/**
 * Driving the app through the controls a person would use. Nothing here
 * reaches into a candidate's modules: every interaction is a DOM event on the
 * workspace's own inputs and buttons, and every reading is taken from the
 * rendered page or from the durable medium.
 */
import { act, fireEvent } from "@testing-library/react";
import { activeScope, nudge, settle } from "./page";

/**
 * Where to look for the app.
 *
 * One page open and this is the document, as it always was. Two tabs open
 * and it is the one being driven, because both trees are mounted into the
 * same document and an unscoped query would find two of every input.
 */
const root = () => activeScope();

/**
 * How long a step waits when the scenario is deliberately not letting the page
 * come to rest. Long enough for React to flush the click and the form to hear
 * about it, far too short for any grouped write to come round.
 */
const QUICK_MS = 20;

/** Wait for everything to stop, or barely at all when the scenario says so. */
async function pause(quick: boolean): Promise<void> {
    if (quick) await nudge(QUICK_MS);
    else await settle();
}

/**
 * A control the suite drives is not on the page. The name is set by hand: a
 * subclass of `Error` keeps `Error` as its name, and the report the grader
 * reads carries the name rather than the class, so without this the one thing
 * that distinguishes a broken harness from a wrong answer is not in the
 * transcript the grader greps.
 */
export class SeamError extends Error {
    constructor(message: string) {
        super(message);
        this.name = "SeamError";
    }
}

function all(selector: string): HTMLElement[] {
    return [...root().querySelectorAll<HTMLElement>(selector)];
}

export function byText(text: string, selector = "button"): HTMLElement | null {
    return all(selector).find((n) => (n.textContent ?? "").trim() === text) ?? null;
}

export function requireByText(text: string, selector = "button"): HTMLElement {
    const found = byText(text, selector);
    if (!found) throw new SeamError(`no ${selector} reading ${JSON.stringify(text)}`);
    return found;
}

export function titleInput(): HTMLInputElement | null {
    return root().querySelector<HTMLInputElement>('input[name="name"]');
}

export function requireTitleInput(): HTMLInputElement {
    const input = titleInput();
    if (!input) throw new SeamError("the event title input is not on the page");
    return input;
}

export function dateInputs(): HTMLInputElement[] {
    return all('input[type="datetime-local"]') as HTMLInputElement[];
}

export async function typeTitle(value: string): Promise<void> {
    const input = requireTitleInput();
    await act(async () => {
        fireEvent.change(input, { target: { value } });
    });
}

export async function setStartDate(value: string): Promise<void> {
    const [start] = dateInputs();
    if (!start) throw new SeamError("the start date input is not on the page");
    await act(async () => {
        fireEvent.change(start, { target: { value } });
    });
}

export function readTitle(): string {
    return requireTitleInput().value;
}

export function readStartDate(): string {
    const [start] = dateInputs();
    return start ? start.value : "";
}

export async function click(element: HTMLElement): Promise<void> {
    await act(async () => {
        fireEvent.click(element);
    });
}

/** Number of gallery items the form holds, as the open gallery modal reports it. */
export function galleryCount(): number {
    const counter = all("*").find((n) => /^\d+\/\d+ photos added$/.test((n.textContent ?? "").trim()));
    if (!counter) throw new SeamError("the gallery modal is not open");
    return Number((counter.textContent ?? "").trim().split("/")[0]);
}

export function ticketNames(): string[] {
    return all("[data-ticket-name]").map((n) => n.textContent ?? "");
}

/** Every URL currently referenced by the rendered page. */
export function renderedUrls(): string[] {
    const urls: string[] = [];
    root().querySelectorAll("img").forEach((n) => urls.push(n.getAttribute("src") ?? ""));
    root().querySelectorAll("[style]").forEach((n) => {
        const style = n.getAttribute("style") ?? "";
        const match = style.match(/url\(["']?([^"')]+)["']?\)/);
        if (match) urls.push(match[1]);
    });
    root().querySelectorAll("object, iframe").forEach((n) => urls.push(n.getAttribute("data") ?? n.getAttribute("src") ?? ""));
    return urls.filter(Boolean);
}

export function makeFile(name: string, contents = "binary-ish"): File {
    return new File([contents], name, { type: name.endsWith(".pdf") ? "application/pdf" : "image/jpeg" });
}

/**
 * A real `FileList`, which the app distinguishes from an array: jsdom offers no
 * way to build one, and a plain array silently takes a different code path.
 */
function fileList(files: File[]): FileList {
    const list: Record<string | number | symbol, unknown> = {
        length: files.length,
        item: (index: number) => files[index] ?? null,
        [Symbol.iterator]: function* () {
            yield* files;
        },
    };
    files.forEach((file, index) => {
        list[index] = file;
    });
    Object.setPrototypeOf(list, FileList.prototype);
    return list as unknown as FileList;
}

/** Put a file on a hidden file input the way a file picker would. */
export async function chooseFile(input: HTMLInputElement, file: File): Promise<void> {
    Object.defineProperty(input, "files", { configurable: true, value: fileList([file]) });
    await act(async () => {
        fireEvent.change(input);
    });
}

export function fileInputs(): HTMLInputElement[] {
    return all('input[type="file"]') as HTMLInputElement[];
}

/**
 * The deepest element whose whole text is `text`. Clicking it bubbles to
 * whatever row handler is above it, which is how a person would open these.
 */
export function leafWithText(text: string): HTMLElement | null {
    const matches = all("*").filter((n) => (n.textContent ?? "").replace(/\s+/g, " ").trim() === text);
    return matches.length ? matches[matches.length - 1] : null;
}

export async function clickRow(text: string, quick = false): Promise<void> {
    const leaf = leafWithText(text);
    if (!leaf) throw new SeamError(`nothing on the page reads ${JSON.stringify(text)}`);
    await click(leaf);
    await pause(quick);
}

export async function expandAdvanced(quick = false): Promise<void> {
    if (leafWithText("Add Gallery")) return;
    await clickRow("Advanced Settings (optional)", quick);
}

/** Open the gallery half modal from the advanced settings section. */
export async function openGalleryModal(quick = false): Promise<void> {
    await expandAdvanced(quick);
    await clickRow("Add Gallery", quick);
}

export function galleryImages(): HTMLImageElement[] {
    return [...root().querySelectorAll<HTMLImageElement>('img[alt="Gallery"]')];
}

/** The flyer the page is showing, whatever produced it. */
export function flyerPreview(): string {
    const img = root().querySelector<HTMLImageElement>('img[alt="Event Flyer"]');
    if (!img) throw new SeamError("the flyer preview is not on the page");
    return img.getAttribute("src") ?? "";
}

async function openFlyerModal(quick = false): Promise<void> {
    const img = root().querySelector<HTMLImageElement>('img[alt="Event Flyer"]');
    if (!img?.parentElement) throw new SeamError("the flyer preview is not on the page");
    await click(img.parentElement);
    await pause(quick);
}

/** Choose the nth picture from the built-in flyer library: a durable address. */
export async function pickLibraryFlyer(index: number, quick = false): Promise<void> {
    await openFlyerModal(quick);
    const choices = [...root().querySelectorAll<HTMLImageElement>("img")].filter((n) => {
        const src = n.getAttribute("src") ?? "";
        return n.getAttribute("alt") !== "Event Flyer" && /^https?:/.test(src);
    });
    const choice = choices[index];
    if (!choice?.parentElement) throw new SeamError(`the flyer library has no picture ${index}`);
    await click(choice.parentElement);
    await pause(quick);
}

/** Upload a flyer from disk: a picture with no address a later page could use. */
export async function uploadFlyer(file: File, quick = false): Promise<void> {
    await openFlyerModal(quick);
    const input = root().querySelector<HTMLInputElement>("#partyFlyerUpload");
    if (!input) throw new SeamError("the flyer upload input is not on the page");
    await chooseFile(input, file);
    await pause(quick);
}

/** Add a picture to the gallery from disk. Leaves the gallery modal open. */
export async function addGalleryFile(file: File, quick = false): Promise<void> {
    await openGalleryModal(quick);
    const inputs = fileInputs().filter((n) => n.getAttribute("accept") === "image/*" && n.id !== "partyFlyerUpload");
    const input = inputs[inputs.length - 1];
    if (!input) throw new SeamError("the gallery upload input is not on the page");
    await chooseFile(input, file);
    await pause(quick);
}

/** Remove the nth picture from the gallery. */
export async function removeGalleryImage(index: number, quick = false): Promise<void> {
    await openGalleryModal(quick);
    const images = galleryImages();
    const target = images[index];
    if (!target) throw new SeamError(`the gallery has no picture ${index}`);
    const button = target.parentElement?.querySelector("button");
    if (!button) throw new SeamError("the gallery picture has no remove control");
    await click(button as HTMLElement);
    await pause(quick);
}

/** The addresses of the gallery pictures, in the order the page shows them. */
export async function galleryUrls(): Promise<string[]> {
    await openGalleryModal();
    return galleryImages().map((n) => n.getAttribute("src") ?? "");
}

/** Anything on the page that only the page that made it could resolve. */
export function transientUrlsOnPage(): string[] {
    return renderedUrls().filter((url) => /^blob:|^data:/i.test(url));
}

/**
 * Half modals are opened and left open, deliberately.
 *
 * Closing one starts an exit animation that does not finish on the frame it was
 * asked for, and opening the same modal again while the old body is still on
 * its way out gets a body nothing is listening to: the controls are there, the
 * clicks land nowhere, and the whole thing disappears one wait later. Every
 * reading and every interaction below works with the modal left as it found it,
 * which costs nothing -- the form is one form whether a section's modal is over
 * it or not -- and removes the one interaction in this app that is not
 * reproducible.
 */

/**
 * The body of the questions modal, found by its own running count.
 *
 * The inputs it holds carry no placeholder of their own — the section draws the
 * prompt as a floating label beside them — so the modal has to be located first
 * and its inputs read from inside it.
 */
function questionsBody(): HTMLElement | null {
    const counter = all("p, span, div").find((n) => /^\d+\/\d+ questions added$/.test((n.textContent ?? "").trim()));
    return counter?.parentElement ?? null;
}

function questionBoxes(): HTMLTextAreaElement[] {
    const body = questionsBody();
    return body ? [...body.querySelectorAll<HTMLTextAreaElement>("textarea")] : [];
}

/**
 * The questions the form holds, read from the inputs the section shows.
 *
 * Opening the modal on an empty list makes the section add a blank question of
 * its own, so only questions someone actually wrote are reported.
 */
export async function questionTexts(): Promise<string[]> {
    await expandAdvanced();
    await clickRow("Add Questions");
    if (!questionsBody()) throw new SeamError("the questions modal did not open");
    return questionBoxes()
        .map((box) => box.value)
        .filter((text) => text.trim().length > 0);
}

/**
 * Write one more question, through the section that owns the list.
 *
 * `quick` performs the same interaction without ever letting the page come to
 * rest, so that whatever the candidate does about grouping its writes has not
 * had a chance to happen when the next action arrives.
 */
export async function addQuestion(text: string, quick = false): Promise<void> {
    await expandAdvanced(quick);
    await clickRow("Add Questions", quick);
    if (!questionsBody()) throw new SeamError("the questions modal did not open");
    const before = questionBoxes().length;
    const add = leafWithText("Add Question");
    if (!add) throw new SeamError("the questions modal has no way to add one");
    await click(add);
    await pause(quick);
    const boxes = questionBoxes();
    const box = boxes[boxes.length - 1];
    if (!box || boxes.length <= before) throw new SeamError("adding a question did not add an input");
    await act(async () => {
        fireEvent.change(box, { target: { value: text } });
    });
    await pause(quick);
}

/** Take the nth question off the form, through the section that owns the list. */
export async function removeQuestion(index: number, quick = false): Promise<void> {
    await expandAdvanced(quick);
    await clickRow("Add Questions", quick);
    if (!questionsBody()) throw new SeamError("the questions modal did not open");
    const box = questionBoxes()[index];
    if (!box) throw new SeamError(`the questions modal has no question ${index}`);
    // Up from the input to the card the question is drawn in: the nearest
    // ancestor holding a control at all. The card's last control is the one
    // that takes the question away.
    let card: HTMLElement | null = box.parentElement;
    while (card && !card.querySelector("button")) card = card.parentElement;
    const remove = card ? [...card.querySelectorAll<HTMLElement>("button")].pop() : null;
    if (!remove) throw new SeamError(`question ${index} has no remove control`);
    await click(remove);
    await pause(quick);
}

/**
 * The address of the document the form is holding, or "" when it holds none.
 *
 * Which document it is, not merely that there is one: the row outside says
 * only "Added", and a page that brought back an address no later page can
 * resolve says "Added" just as loudly as one that brought back the event's own
 * file. So the modal is opened and the viewer's own source read — an <object>
 * for a file the page is holding, a viewer frame for a document with an
 * address of its own.
 *
 * The modal is opened without waiting for the page to come to rest, because it
 * shows a spinner until the document loads, which in this environment is
 * never: a wait after opening it runs to its ceiling and buys nothing. The
 * cheap answer comes first — with no document there is nothing to open.
 */
export async function documentSeen(): Promise<string> {
    await expandAdvanced();
    if (!leafWithText("Added")) return "";
    await clickRow("Add File", true);
    const held = root().querySelector<HTMLElement>('object[type="application/pdf"]');
    const remote = root().querySelector<HTMLElement>('iframe[title="PDF Document"]');
    let seen = "";
    if (held) seen = held.getAttribute("data") ?? "";
    else if (remote) seen = viewerSource(remote.getAttribute("src") ?? "");
    else throw new SeamError("the document modal is not showing a document");
    return seen;
}

/** The document address a viewer frame was pointed at. */
function viewerSource(src: string): string {
    const match = src.match(/[?&]url=([^&]*)/);
    return match ? decodeURIComponent(match[1]) : src;
}

/** Take the document off the form, the way its own control does. */
export async function removeDocument(quick = false): Promise<void> {
    await expandAdvanced(quick);
    // Opened without waiting: the viewer inside spins for a document that never
    // arrives, so waiting for rest here costs the ceiling and changes nothing.
    await clickRow("Add File", true);
    const shown = root().querySelector<HTMLElement>('object[type="application/pdf"], iframe[title="PDF Document"]');
    // The body of the modal: the row naming the document, its remove control
    // and the viewer below it. Staying inside it keeps the modal's own close
    // button, which is also a button with no text, out of reach.
    const body = shown?.closest("div")?.parentElement;
    if (!body) throw new SeamError("the document modal is not showing a document");
    const button = [...body.querySelectorAll<HTMLElement>("button")].find((n) => !(n.textContent ?? "").trim());
    if (!button) throw new SeamError("the document has no remove control");
    await click(button);
    await pause(quick);
}

/**
 * Put a document on the form from disk: no address a later page could use.
 * The picker's input is on the page whether the modal is open or not, so this
 * never opens it.
 */
export async function uploadDocument(file: File, quick = false): Promise<void> {
    await expandAdvanced(quick);
    const input = fileInputs().find((n) => (n.getAttribute("accept") ?? "").includes("pdf"));
    if (!input) throw new SeamError("the document upload input is not on the page");
    await chooseFile(input, file);
    await pause(quick);
}
