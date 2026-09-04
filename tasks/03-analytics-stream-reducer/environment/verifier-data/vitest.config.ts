import react from "@vitejs/plugin-react";
import path from "path";
import { defineConfig } from "vitest/config";

// The grading run lives outside the candidate's tree. `root` is this directory;
// module aliases point at the candidate's sources so the specs import exactly
// what the application imports.
const WORKSPACE = process.env.VERIFY_WORKSPACE ?? "/workspace";
const HERE = __dirname;

export default defineConfig({
    root: HERE,
    cacheDir: path.join(HERE, ".vite"),
    resolve: {
        alias: {
            "@components": path.join(WORKSPACE, "src/components"),
            "@data": path.join(WORKSPACE, "src/data"),
            "@util": path.join(WORKSPACE, "src/util"),
            "@pages": path.join(WORKSPACE, "src/pages"),
        },
    },
    define: {
        "import.meta.env.VITE_BASE_API_URL": '"http://api.test.local"',
    },
    plugins: [react()],
    test: {
        environment: "jsdom",
        globals: false,
        setupFiles: [path.join(HERE, "setup.ts")],
        include: ["graded.spec.tsx"],
        testTimeout: 60000,
        hookTimeout: 60000,
        pool: "forks",
        poolOptions: { forks: { singleFork: true } },
        sequence: { concurrent: false, shuffle: false },
        retry: 0,
        silent: false,
    },
});
