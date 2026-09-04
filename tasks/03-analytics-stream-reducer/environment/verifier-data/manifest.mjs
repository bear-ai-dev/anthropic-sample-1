#!/usr/bin/env node
// Record a hash per file of the starting workspace. The grader compares against
// this to tell "implemented nothing" from "implemented something wrong": the
// first is a graded zero, the second is also a zero but for a different reason,
// and only the first can be recognised without running anything.
//
// Run at image build time: node manifest.mjs <src-dir> <out-file>

import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const [root, out] = process.argv.slice(2);
if (!root || !out) {
    console.error("usage: manifest.mjs <src-dir> <out-file>");
    process.exit(2);
}

const manifest = {};
const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
        if (entry.name === "node_modules" || entry.name === ".git") continue;
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (entry.isFile()) {
            manifest[path.relative(root, full)] = createHash("sha256").update(fs.readFileSync(full)).digest("hex");
        }
    }
};
walk(root);

fs.writeFileSync(out, JSON.stringify(manifest, null, 0) + "\n");
console.log(`manifest: ${Object.keys(manifest).length} files`);
