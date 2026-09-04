The agent has access to the full source code for a private event platform and a local copy of the team's issue tracker. It must recover form drafts across the create, edit, and duplicate event flows without mixing drafts between organizers or workflows. Older records must migrate safely, unknown newer formats must remain untouched, and publishing or discarding must clear only the correct draft without trying to save unrecoverable local files.

| Model | Harness | Passes | Scored rollouts | Pass rate |
|---|---|---:|---:|---:|
| Fable 5.1 | Claude Code | 1 | 8 | 12.5% |
| Opus 5 | Claude Code | 0 | 8 | 0.0% |
| GPT-5.6 Sol | Codex CLI | 3 | 8 | 37.5% |
| GLM 5.3 | mini-SWE-agent | 0 | 8 | 0.0% |

| Model | Harness | Mean wall clock | Mean output tokens | Mean steps |
|---|---|---:|---:|---:|
| Fable 5.1 | Claude Code | 16m | 71,966.8 | 16.9 |
| Opus 5 | Claude Code | 22m | 85,398.5 | 59.9 |
| GPT-5.6 Sol | Codex CLI | 7m | 31,248.0 | 32.5 |
| GLM 5.3 | mini-SWE-agent | 22m | 88,412.3 | 89.8 |
