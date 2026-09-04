import react from "@vitejs/plugin-react";
import path from "path";
import { defineConfig } from "vite";

// The graded tree lives outside this directory so that held-out material is
// never reachable from the workspace the solver edits. WORKSPACE_DIR lets the
// same spec be pointed at another checkout.
const workspace = process.env.WORKSPACE_DIR ?? "/workspace";
const src = path.join(workspace, "src");

export default defineConfig({
    cacheDir: "/tmp/vite-cache-grade",
    resolve: {
        alias: {
            "@components": path.join(src, "components"),
            "@data": path.join(src, "data"),
            "@util": path.join(src, "util"),
            "@pages": path.join(src, "pages"),
            "@workspace": src,
        },
    },
    define: {
        "import.meta.env.VITE_BASE_API_URL": JSON.stringify("http://api.invalid"),
        "import.meta.env.VITE_ENVIRONMENT": JSON.stringify("TEST"),
        "import.meta.env.VITE_FIREBASE_API_KEY": JSON.stringify("test-key"),
        "import.meta.env.VITE_FIREBASE_AUTH_DOMAIN": JSON.stringify("test.invalid"),
        "import.meta.env.VITE_FIREBASE_PROJECT_ID": JSON.stringify("test"),
        "import.meta.env.VITE_FIREBASE_STORAGE_BUCKET": JSON.stringify("test"),
        "import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID": JSON.stringify("0"),
        "import.meta.env.VITE_FIREBASE_APP_ID": JSON.stringify("test"),
        "import.meta.env.VITE_FIREBASE_MEASUREMENT_ID": JSON.stringify("test"),
        "import.meta.env.VITE_GOOGLE_MAPS_API_KEY": JSON.stringify("test"),
        "import.meta.env.VITE_GEOCODING_API_KEY": JSON.stringify("test"),
        "import.meta.env.VITE_GIPHY_API_KEY": JSON.stringify("test"),
        "import.meta.env.VITE_UNSPLASH_API_KEY": JSON.stringify("test"),
    },
    plugins: [react()],
    test: {
        globals: false,
        environment: "jsdom",
        setupFiles: [path.join(__dirname, "harness/setup.ts")],
        include: [path.join(__dirname, "spec/**/*.spec.tsx")],
        // A scenario that opens four pages costs a few seconds on a machine to
        // itself and a minute and a half on a build host running ten other
        // suites. The ceiling is here to stop a hung run, not to time anything:
        // a timeout is a fact about the machine, and the scorer treats one as a
        // case nobody reached rather than as a rule that did not hold.
        testTimeout: 300000,
        hookTimeout: 300000,
        pool: "forks",
        // One worker at a time, and a new one per file. Every page this suite
        // opens leaves something behind that the process cannot reclaim, so the
        // graded scenarios are split across six files and each part starts in a
        // process that has never opened one. A single fork for all of them ran
        // the sandbox out of memory part way through, which the grader reports
        // as a harness failure rather than a verdict — correct, and useless.
        //
        // The six files still go in one invocation: the candidate's module
        // graph is transformed once there and once per file otherwise, which was
        // most of the wall clock.
        poolOptions: { forks: { singleFork: false, minForks: 1, maxForks: 1 } },
        fileParallelism: false,
        reporters: ["default"],
        css: false,
    },
});
