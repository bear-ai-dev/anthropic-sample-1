# Opus 5 + Claude Code: task-version provenance

All 40 scored trials now have a SHA-256 task identity in the [trial index](../indexes/trials.json), linked to the [per-trial provenance ledger](opus-task-provenance.json). The score remains **6/40 (15.0%)**. No model calls, regrading, cohort substitutions or reward changes were made for this provenance repair.

| Task | Native hashes cross-checked | Hashes reconstructed from original inputs |
|---|---:|---:|
| 02 — Recurring events | 0 | 8 |
| 04 — Draft recovery | 8 | 0 |
| 08 — Envelope intake | 1 | 7 |
| 11 — Store cutover | 0 | 8 |
| 12 — Readmodel rebuild | 1 | 7 |
| Total | 10 | 30 |

## Evidence chain

1. Resolve each original trial to its actual AWS run through the source trial index and AWS rollout registry. The cohort spans four runs; the eight draft-recovery trials belong to a later run and must not be assigned the earlier run's task version.
2. Read that run's archived specification. Record its SHA-256, task source revision, immutable task-image digest and runtime-init digest.
3. Retrieve its original `task.toml`, `instruction.md`, `environment.tar.gz`, `tests.tar.gz` and `solution.tar.gz`. All objects' last-modified timestamps precede the earliest corresponding agent event. Record individual archive SHA-256 values.
4. Reconstruct the task directory using the runner's extraction layout and compute Harbor's `Task.checksum`: `dirhash(task_directory, "sha256")`. All ten pre-existing native checksums match exactly. Envelope-intake and readmodel-rebuild native runs independently match the same input hashes reconstructed for the earlier recovered runs.
5. Bind each original result and trajectory to the exact AWS run and trial. Check verifier-result/checksum fields, trajectory session ID, every step ID/timestamp and step count. Record original, cloud-source and published artifact hashes.

The index's `task_checksum_source` distinguishes `native` from `reconstructed`. The 30 original `result.json` files still retain `recovered-from-original-sandbox`: they are immutable source evidence, not silently rewritten. Use the index and linked ledger for the effective task identity.

## Scope

This is recovered provenance for the archived execution inputs, not a claim that the runner originally emitted the missing launch-time checksums. S3 object version IDs were unavailable; pre-run modification timestamps, run-spec bindings, archived bytes and matching native hashes support the recovery. The ledger does not establish equality with every other model's task image or certify verifier fairness. It does not change any failure-mode label.

Licensed task-input archives, private cloud locations and native sessions are not included in this audit package. An authorized reviewer can reproduce the checksums from the archived inputs using the recorded per-file hashes and image digests. The published evidence supports artifact linkage; it is not a self-contained runnable environment delivery.
