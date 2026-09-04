# Anthropic Sample 1

Anthropic Sample 1 is a Real SWE benchmark sample of engineering tasks on private, real world company codebases. All traces are recorded under [`trajectories/`](trajectories/).

## Table of contents

- [Pass rates](#pass-rates)
- [Efficiency](#efficiency)
- [Task distribution](#task-distribution)
- [Evidence and validity](#evidence-and-validity)
- [Repository layout](#repository-layout)

## Pass rates

| Model | Harness | Passes | Scored rollouts | Pass rate |
|---|---|---:|---:|---:|
| Fable 5.1 | Claude Code | 9 | 56 | 16.1% |
| Opus 5 | Claude Code | 8 | 56 | 14.3% |
| GLM 5.3 | Claude Code | 2 | 16 | 12.5% |
| GPT-5.6 Sol | Codex CLI | 5 | 56 | 8.9% |
| GLM 5.3 | mini-SWE-agent | 1 | 56 | 1.8% |
| Kimi K3 | Kimi Code | 0 | 16 | 0.0% |

The table presents the selected model-and-harness comparison. GPT-5.6 Sol combines all 56 Codex CLI rollouts into one result.

## Efficiency

| Model | Harness | Mean wall clock | Mean output tokens | Mean steps |
|---|---|---:|---:|---:|
| Fable 5.1 | Claude Code | 26m | 105,403.7 | 27.4 |
| Opus 5 | Claude Code | 53m | 132,817.5 | 128.7 |
| GLM 5.3 | Claude Code | 41m | 170,830.7 | 142.4 |
| GPT-5.6 Sol | Codex CLI | 11m | 37,945.4 | 58.8 |
| GLM 5.3 | mini-SWE-agent | 46m | 147,592.7 | 163.5 |
| Kimi K3 | Kimi Code | 34m | 63,013.0 | 103.9 |

Wall clock is the recorded elapsed time for a complete scored rollout and is rounded to the nearest minute. Output tokens are the total completion/output tokens recorded by the native harness. Steps are normalized trajectory events. Means use only recorded values, and missing values are not treated as zero.

## Task distribution

The benchmark contains seven Real SWE tasks:

1. [Task 1: Linearizable ticket scanning](tasks/01-linearizable-scan/instruction.md) — Make simultaneous door scans, partial party admissions, and retries agree on exactly who was admitted while preserving authorization and host reporting.
2. [Task 2: Recurring event series](tasks/02-recurring-events/instruction.md) — Let organizers extend, rebuild, delete, or reschedule recurring events without disturbing occurrences protected by an audience or paid tickets.
3. [Task 3: Live analytics stream](tasks/03-analytics-stream-reducer/instruction.md) — Render dashboard sections as live results arrive, recover from interruptions, and prevent retired connections from showing stale data.
4. [Task 4: Durable draft recovery](tasks/04-draft-recovery/instruction.md) — Recover event-form drafts across create, edit, and duplicate flows while isolating users, migrating older records, and handling local files safely.
5. [Task 5: Support-envelope intake](tasks/08-envelope-intake/instruction.md) — Group retried, concurrent, and out-of-order email envelopes into the right support tickets and send each agent reply exactly once.
6. [Task 6: Membership-ledger cutover](tasks/11-store-cutover/instruction.md) — Move a live financial ledger from one store to another without pausing traffic, losing movements, or returning superseded balances.
7. [Task 7: Online read-model rebuild](tasks/12-readmodel-rebuild/instruction.md) — Rebuild and switch an event-feed projection while new events continue to arrive, without exposing partial generations to readers.

## Evidence and validity

A rollout is scored only when it has no harness exception, a numeric verifier reward, a complete non-empty trajectory, verifier evidence, the task identity, and the declared model route and harness. Infrastructure and provider failures are excluded from denominators.

- [`indexes/trials.json`](indexes/trials.json) is the scored index.
- [`manifest.json`](manifest.json) records task identities, totals, content hashes, and completion state.
- [`trajectories/`](trajectories/) contains every normalized scored trajectory.
- [`results/`](results/) contains available verifier and result evidence for each trial.
- [`indexes/artifacts.json`](indexes/artifacts.json) records retained artifact hashes.
- [`control-results.json`](control-results.json) records task oracle and no-op validity checks.
- [`task-publication.json`](task-publication.json) maps the execution task identities to the privacy-safe published task packages.

The licensed application workspaces used for execution are intentionally omitted. Their task contracts, verifiers, reference materials, source hashes, trajectories, and verifier evidence are retained after credential, restricted-name, and infrastructure redaction.

Private chain-of-thought fields and encrypted provider reasoning blobs are intentionally blanked in every trajectory. Observable assistant messages, tool activity, final answers, metrics, and verifier evidence are retained.

## Repository layout

```text
tasks/<task>/
results/<model-harness-route>/tasks/<task>/trial-<01-08>/
trajectories/<task>/<model-harness-route>/trajectory-trial-<01-08>.json
indexes/trials.json
indexes/artifacts.json
control-results.json
task-publication.json
manifest.json
```
