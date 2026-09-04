/**
 * Running one scenario against both the candidate and the model, and saying
 * whether they agree.
 *
 * The model does not know two things, and does not need to: the address the
 * flyer library hands out, and the address a page mints for a file it is
 * holding. Both are wildcards here — the first has to be the address the page
 * itself showed when the picture was chosen, the second has to be an address
 * only the page that made it could resolve.
 */
import { perform, type Action, type Observation, type RunOptions } from "../harness/script";
import { measureBaseline } from "./baselines";
import { DraftModel, PICKED, TRANSIENT, type Prediction } from "./draftModel";

export interface Comparison {
    observed: Observation;
    predicted: Prediction;
    problems: string[];
}

const isTransient = (url: string) => /^(blob:|data:)/i.test(url);

function compareUrl(label: string, predicted: string, actual: string, picked: string | null, problems: string[]): void {
    if (predicted === TRANSIENT) {
        if (!isTransient(actual)) problems.push(`${label}: expected an address only this page can resolve, saw ${actual}`);
        return;
    }
    if (predicted === PICKED) {
        if (picked === null) {
            if (!actual || isTransient(actual)) problems.push(`${label}: expected a durable address, saw ${actual}`);
            return;
        }
        if (actual !== picked) problems.push(`${label}: expected the chosen picture ${picked}, saw ${actual}`);
        return;
    }
    if (actual !== predicted) problems.push(`${label}: expected ${JSON.stringify(predicted)}, saw ${JSON.stringify(actual)}`);
}

export async function check(actions: Action[], options: RunOptions = {}): Promise<Comparison> {
    const observed = await perform(actions, options);
    const model = new DraftModel((mode, user, event) => measureBaseline(mode, user, event));
    const predicted = model.run(actions);

    const problems: string[] = [];
    const picked = observed.picked.length ? observed.picked[observed.picked.length - 1] : null;

    if (observed.title !== predicted.title) {
        problems.push(`title: expected ${JSON.stringify(predicted.title)}, saw ${JSON.stringify(observed.title)}`);
    }
    compareUrl("flyer", predicted.flyer, observed.flyer, picked, problems);
    if (options.withQuestions) {
        if (predicted.questions === null) {
            // Not a wrong answer: a rule asked about a flow whose questions
            // nobody measured, so there is nothing to compare against.
            throw new Error("this flow's questions were never measured; prime it with questions: true");
        }
        const seen = (observed.questions ?? []).join(" | ");
        const want = predicted.questions.join(" | ");
        if (seen !== want) problems.push(`questions: expected ${JSON.stringify(want)}, saw ${JSON.stringify(seen)}`);
    }
    if (options.withDoc) {
        if (predicted.doc === null) {
            // Not a wrong answer: a rule asked about a flow whose document
            // nobody measured, so there is nothing to compare against.
            throw new Error("this flow's document was never measured; prime it with doc: true");
        }
        // An empty answer on either side is about whether a document is held at
        // all, and reads better said that way than as an address of nothing.
        if (!predicted.doc || !observed.doc) {
            const say = (value: string) => (value ? "a document" : "no document");
            if ((observed.doc ?? "") !== predicted.doc) {
                problems.push(`document: expected ${say(predicted.doc)}, saw ${say(observed.doc ?? "")}`);
            }
        } else {
            compareUrl("document", predicted.doc, observed.doc, picked, problems);
        }
    }
    if (options.withGallery) {
        if (observed.gallery.length !== predicted.gallery.length) {
            problems.push(`gallery: expected ${predicted.gallery.length} pictures, saw ${observed.gallery.length}`);
        } else {
            predicted.gallery.forEach((url, index) => {
                compareUrl(`gallery[${index}]`, url, observed.gallery[index], picked, problems);
            });
        }
    }

    return { observed, predicted, problems };
}
