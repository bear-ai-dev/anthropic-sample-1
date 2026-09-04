// One connection to the analytics stream, scoped to a generation.
//
// The hook hands out a new generation number every time the stream is re-opened
// or the viewed event changes. A session remembers the generation it was born
// into and asks the hook, on every callback, what the current generation is. The
// moment those differ the session is superseded and must be silent: the frames
// it is still holding belong to a view of the world that the user has left.
//
// Reconnecting is deliberately *not* this class's business. The library will
// happily retry for us, but only to the URL it was given, and a resumed read has
// to ask for a different one — so a failure is reported to the owner and the
// owner opens the next connection.
//
// The generation matters because aborting a fetch does not unwind the callbacks
// already in flight. `AbortController.abort()` marks the signal, but a chunk that has
// already been read is still dispatched, and the promise chain of the previous
// invocation can still settle after the next one has started. Checking the
// signal alone is necessary and not sufficient, so the generation is the
// authority and the signal is a fast path.

import { fetchEventSource } from "@microsoft/fetch-event-source";

/**
 * What the owner wants done about a connection that failed.
 *   handoff - the owner will open the next connection itself
 *   stop    - there is nothing left to try
 */
export type LostVerdict = "handoff" | "stop";

export interface StreamSessionCallbacks {
    /** A frame arrived and this session is still the current one. */
    onFrame: (raw: string, generation: number) => void;
    /** The connection is established. */
    onOpen: (generation: number) => void;
    /**
     * The connection failed. The owner decides what happens next, because only
     * the owner knows what the dashboard is showing and therefore where a
     * resumed read would have to start.
     */
    onLost: (error: Error, generation: number) => LostVerdict;
    /** Nothing further will be attempted on this read. */
    onGiveUp: (error: Error, generation: number) => void;
}

/** Thrown to make `fetch-event-source` stop retrying a superseded session. */
class SupersededError extends Error {
    constructor() {
        super("analytics stream session superseded");
        this.name = "SupersededError";
    }
}

/**
 * Thrown to stop the library's own retry loop when the owner has taken over.
 * The library would retry the same URL, which is precisely what a resume must
 * not do: it would ask the backend to recompute sections already on screen.
 */
class HandedOffError extends Error {
    constructor() {
        super("analytics stream reconnect handed to the owner");
        this.name = "HandedOffError";
    }
}

export class AnalyticsStreamSession {
    private readonly controller = new AbortController();
    private disposed = false;

    constructor(
        readonly generation: number,
        readonly url: string,
        private readonly headers: Record<string, string>,
        private readonly callbacks: StreamSessionCallbacks,
        /** Reads the generation the hook considers current, right now. */
        private readonly currentGeneration: () => number
    ) {}

    /**
     * A session is superseded once it has been closed, its request aborted, or
     * a newer generation has been started. Every callback consults this before
     * touching anything the user can see.
     */
    get superseded(): boolean {
        if (this.disposed) return true;
        if (this.controller.signal.aborted) return true;
        return this.currentGeneration() !== this.generation;
    }

    async open(): Promise<void> {
        const generation = this.generation;

        try {
            await fetchEventSource(this.url, {
                method: "GET",
                headers: this.headers,
                signal: this.controller.signal,
                // The dashboard should keep reading while the tab is in the
                // background; a hidden tab is not a reason to drop a section.
                openWhenHidden: true,

                onopen: async (response) => {
                    if (this.superseded) throw new SupersededError();

                    if (response.ok) {
                        this.callbacks.onOpen(generation);
                        return;
                    }

                    if (response.status >= 400 && response.status < 500) {
                        throw new Error(`Client error: ${response.status} ${response.statusText}`);
                    }
                    throw new Error(`Server error: ${response.status} ${response.statusText}`);
                },

                onmessage: (message) => {
                    // The guard has to be here, before parsing, and the hook
                    // checks again before it commits: a frame can cross both
                    // boundaries while a generation change is in flight.
                    if (this.superseded) return;
                    if (!message.data) return;
                    this.callbacks.onFrame(message.data, generation);
                },

                onclose: () => {
                    // The server closed cleanly. Nothing to report: whatever
                    // sections arrived are already committed, and the terminal
                    // frame is what marks the stream finished.
                },

                onerror: (error) => {
                    if (this.superseded) throw new SupersededError();
                    if (error instanceof SupersededError) throw error;
                    if (error instanceof HandedOffError) throw error;

                    const failure = error instanceof Error ? error : new Error(String(error));
                    // Never return a delay from here. Returning one puts the
                    // library in charge of the reconnect, and the library
                    // reconnects to the URL it already has — with no resume
                    // point on it.
                    if (this.callbacks.onLost(failure, generation) === "handoff") {
                        throw new HandedOffError();
                    }
                    throw failure;
                },
            });
        } catch (error) {
            if (this.superseded) return;
            if (error instanceof SupersededError) return;
            if (error instanceof HandedOffError) return;
            this.callbacks.onGiveUp(error instanceof Error ? error : new Error(String(error)), generation);
        }
    }

    close(): void {
        if (this.disposed) return;
        this.disposed = true;
        try {
            this.controller.abort();
        } catch {
            // An environment without AbortController support still gets the
            // generation guard, which is the part that has to hold.
        }
    }
}
