# Anthropic Sample 1

Anthropic Sample 1 contains private, real-world company tasks from company datasets that we've licenced. All traces are recorded under [`trajectories/`](trajectories/).

## Table of contents

- [Pass rates](#pass-rates)
- [Efficiency](#efficiency)
- [Task distribution](#task-distribution)
- [Evidence and validity](#evidence-and-validity)
- [Repository layout](#repository-layout)

## Pass rates

| Model | Harness | Passes | Scored rollouts | Pass rate |
|---|---|---:|---:|---:|
| Fable 5.1 | Claude Code | 9 | 40 | 22.5% |
| Opus 5 | Claude Code | 6 | 40 | 15.0% |
| GPT-5.6 Sol | Codex CLI | 5 | 40 | 12.5% |
| Grok 4.6 | Grok Build | 3 | 40 | 7.5% |
| GLM 5.3 | mini-SWE-agent | 1 | 40 | 2.5% |

The table presents the selected model-and-harness comparison across all five tasks.

## Efficiency

| Model | Harness | Mean wall clock | Mean output tokens | Mean steps |
|---|---|---:|---:|---:|
| Fable 5.1 | Claude Code | 28m | 112,797.7 | 28.1 |
| Opus 5 | Claude Code | 54m | 139,469.2 | 131.3 |
| GPT-5.6 Sol | Codex CLI | 11m | 39,702.7 | 60.2 |
| Grok 4.6 | Grok Build | 1h 21m | 282,232.1 | 60.1 |
| GLM 5.3 | mini-SWE-agent | 50m | 159,200.1 | 158.3 |

Wall clock is the recorded elapsed time for a complete scored rollout and is rounded to the nearest minute. Output tokens are the total completion/output tokens recorded by the native harness. Steps are normalized trajectory events. Means use only recorded values, and missing values are not treated as zero.

## Task distribution

The benchmark contains five Real SWE tasks:

1. [Task 1: Recurring event series](tasks/02-recurring-events/instruction.md) — Let organizers extend, rebuild, delete, or reschedule recurring events without disturbing occurrences protected by an audience or paid tickets.
2. [Task 2: Durable draft recovery](tasks/04-draft-recovery/instruction.md) — Recover event-form drafts across create, edit, and duplicate flows while isolating users, migrating older records, and handling local files safely.
3. [Task 3: Support-envelope intake](tasks/08-envelope-intake/instruction.md) — Group retried, concurrent, and out-of-order email envelopes into the right support tickets and send each agent reply exactly once.
4. [Task 4: Membership-ledger cutover](tasks/11-store-cutover/instruction.md) — Move a live financial ledger from one store to another without pausing traffic, losing movements, or returning superseded balances.
5. [Task 5: Online read-model rebuild](tasks/12-readmodel-rebuild/instruction.md) — Rebuild and switch an event-feed projection while new events continue to arrive, without exposing partial generations to readers.

## Evidence and validity

A rollout is scored only when it has no Harbor/provider exception, a numeric verifier reward, a complete non-empty trajectory, verifier evidence, the task identity, and the declared model route and harness. Nested task-grader `harness_failure` flags require explicit adjudication; they can also describe a submission that cannot build or start. The [five flagged rows](analysis/admission-review.json) in the reported configurations are now adjudicated: four are submission-induced failures, and one has a paired original/corrected saved-submission replay. The corrected replay still fails a product requirement, so every pass rate and denominator is unchanged. Infrastructure and provider failures remain excluded.

- [`indexes/trials.json`](indexes/trials.json) is the scored index.
- [`indexes/manifest.json`](indexes/manifest.json) records task identities, totals, content hashes, and completion state.
- [`trajectories/`](trajectories/) contains every normalized scored trajectory.
- [`results/`](results/) contains available verifier and result evidence for each trial.
- [`indexes/artifacts.json`](indexes/artifacts.json) records retained artifact hashes.
- [`controls/control-results.json`](controls/control-results.json) records task oracle and no-op validity checks.
- [`analysis/README.md`](analysis/README.md) provides the evidence-linked review of all 40 Fable Claude Code trials, replacing inherited failure labels.
- [`analysis/cutover-replay/README.md`](analysis/cutover-replay/README.md) documents the verifier-only correction, green controls, and unchanged effective zero.
- [`docs/HANDOFF.md`](docs/HANDOFF.md) distinguishes this audit package from a separately authorized runnable delivery.
- [`analysis/opus-task-provenance.md`](analysis/opus-task-provenance.md) documents all 40 Opus task identities: ten native hashes cross-checked and 30 reconstructed from the original run inputs, with original results preserved and the 6/40 score unchanged.
- [`indexes/task-publication.json`](indexes/task-publication.json) maps the execution task identities to the privacy-safe published task packages.

The licensed application workspaces used for execution are intentionally omitted. Their task contracts, verifiers, reference materials, source hashes, trajectories, and verifier evidence are retained after credential, restricted-name, and infrastructure redaction.

Private chain-of-thought fields and encrypted provider reasoning blobs are intentionally blanked in every trajectory. Observable assistant messages, tool activity, final answers, metrics, and verifier evidence are retained.

## Repository layout

```text
tasks/<task>/
results/<model-harness-route>/tasks/<task>/trial-<01-08>/
trajectories/<task>/<model-harness>/trajectory-trial-<01-08>.json
indexes/trials.json
indexes/artifacts.json
controls/control-results.json
indexes/task-publication.json
indexes/manifest.json
docs/HANDOFF.md
docs/task-provenance.md
```
