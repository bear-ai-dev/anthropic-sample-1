# Anthropic Sample 1

Seven enterprise coding tasks with repeated model rollouts, complete trajectories,
and verifier-backed outcomes. All requested Sample 1 cohorts are complete and represented below.

## Table of contents

- [Tasks](#tasks)
- [Pass rates](#pass-rates)
- [Measured effort](#measured-effort)
- [Evidence layout](#evidence-layout)
- [Evaluation method](#evaluation-method)

## Tasks

- [`01-linearizable-scan`](tasks/01-linearizable-scan/instruction.md)
- [`02-recurring-events`](tasks/02-recurring-events/instruction.md)
- [`03-analytics-stream-reducer`](tasks/03-analytics-stream-reducer/instruction.md)
- [`04-draft-recovery`](tasks/04-draft-recovery/instruction.md)
- [`08-envelope-intake`](tasks/08-envelope-intake/instruction.md)
- [`11-store-cutover`](tasks/11-store-cutover/instruction.md)
- [`12-readmodel-rebuild`](tasks/12-readmodel-rebuild/instruction.md)

## Pass rates

Each row is one model, harness, and provider configuration. Configurations are
kept separate so a harness or provider change is not presented as a base-model
comparison.

| Model | Harness | Harness version | Provider | Tasks | Passes | Scored rollouts | Pass rate |
|---|---|---|---|---:|---:|---:|---:|
| Fable 5.1 | mini-SWE-agent | 2.4.5 | Bedrock | 5 | 12 | 40 | 30.0% |
| Grok 4.6 | mini-SWE-agent | 2.4.5 | OpenRouter | 7 | 12 | 56 | 21.4% |
| Fable 5.1 | Claude Code | 2.1.258 | Bedrock | 7 | 9 | 56 | 16.1% |
| Opus 5 | Claude Code | 2.1.236; 2.1.258 | Bedrock | 7 | 8 | 56 | 14.3% |
| GLM 5.3 | Claude Code | 2.1.250 | OpenRouter | 2 | 2 | 16 | 12.5% |
| GPT-5.6 Sol | Codex CLI | 0.151.0 | Bedrock | 5 | 5 | 40 | 12.5% |
| Grok 4.6 | Grok Build | 1.0.18 | OpenRouter | 7 | 4 | 56 | 7.1% |
| GLM 5.3 | mini-SWE-agent | 2.4.5 | OpenRouter | 7 | 1 | 56 | 1.8% |
| GPT-5.6 Sol | Codex CLI | 0.151.0 | OpenRouter | 2 | 0 | 16 | 0.0% |
| Kimi K3 | Kimi Code | 0.39.1 | OpenRouter | 2 | 0 | 16 | 0.0% |

## Measured effort

Means are computed per scored rollout. Wall clock is the elapsed time between
the first and last timestamped trajectory step, with Harbor start and finish
timestamps used when trajectory timestamps are unavailable. Grok Build and
Kimi Code use their harness-native ACP/session elapsed time where recorded.
Output tokens are uncached model completion tokens. Step count is the number of
normalized ATIF trajectory steps. Metric coverage states how many scored
rollouts supplied all three fields.

| Model | Harness | Harness version | Provider | Metric coverage | Wall clock, mean | Output tokens, mean | Step count, mean |
|---|---|---|---|---:|---:|---:|---:|
| Fable 5.1 | mini-SWE-agent | 2.4.5 | Bedrock | 40/40 | 4,080.2 s | 115,098 | 92 |
| Grok 4.6 | mini-SWE-agent | 2.4.5 | OpenRouter | 56/56 | 3,014.9 s | 161,522 | 66 |
| Fable 5.1 | Claude Code | 2.1.258 | Bedrock | 56/56 | 1,543.6 s | 105,404 | 27 |
| Opus 5 | Claude Code | 2.1.236; 2.1.258 | Bedrock | 56/56 | 3,182.9 s | 132,818 | 129 |
| GLM 5.3 | Claude Code | 2.1.250 | OpenRouter | 16/16 | 2,480.1 s | 170,831 | 142 |
| GPT-5.6 Sol | Codex CLI | 0.151.0 | Bedrock | 40/40 | 663.6 s | 39,703 | 60 |
| Grok 4.6 | Grok Build | 1.0.18 | OpenRouter | 56/56 | 4,875.9 s | 283,843 | 65 |
| GLM 5.3 | mini-SWE-agent | 2.4.5 | OpenRouter | 56/56 | 2,772.7 s | 147,593 | 164 |
| GPT-5.6 Sol | Codex CLI | 0.151.0 | OpenRouter | 16/16 | 599.5 s | 33,552 | 55 |
| Kimi K3 | Kimi Code | 0.39.1 | OpenRouter | 16/16 | 2,014.4 s | 63,013 | 104 |

## Evidence layout

- [`indexes/trials.json`](indexes/trials.json) is the machine-readable source of truth.
- [`indexes/artifacts.json`](indexes/artifacts.json) records retained artifact hashes.
- `trajectories/<task>/<arm>/trajectory-trial-<01-08>.json` contains normalized trajectories.
- `results/<arm>/tasks/<task>/trial-<01-08>/` contains available verifier and result evidence.
- [`manifest.json`](manifest.json) records counts, hashes, and completion state.
- [`task-publication.json`](task-publication.json) distinguishes frozen execution
  hashes from the privacy-safe published task packages.

## Evaluation method

A rollout passes only when its numeric verifier reward is `1.0`. Provider and
infrastructure failures are excluded from scored denominators. Every included
row resolves to a non-empty trajectory and verifier/result evidence. The task
packages include reference solutions and deterministic verifier controls; their
control status is recorded in [`control-results.json`](control-results.json).

The licensed application workspaces used for execution are intentionally
omitted. Task contracts, verifiers, reference materials, frozen execution
hashes, trajectories, and verifier evidence are retained after credential,
restricted-name, and infrastructure redaction. The published task directories
are audit packages, not turnkey execution images; controls bind to the frozen
execution hashes recorded in `task-publication.json`.
