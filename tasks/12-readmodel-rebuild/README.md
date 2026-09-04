The agent has access to the full source code for a private event-feed service, operational records, and local repository history. It must rebuild a richer reporting projection from six months of events while new events continue to arrive, then switch readers without exposing a partial generation or an inconsistent answer. The new projection must use the required local-day boundaries, and the old generation must be removed after cutover.

| Model | Harness | Passes | Scored rollouts | Pass rate |
|---|---|---:|---:|---:|
| Fable 5.1 | Claude Code | 3 | 8 | 37.5% |
| Opus 5 | Claude Code | 0 | 8 | 0.0% |
| GPT-5.6 Sol | Codex CLI | 1 | 8 | 12.5% |
| GLM 5.3 | mini-SWE-agent | 1 | 8 | 12.5% |

| Model | Harness | Mean wall clock | Mean output tokens | Mean steps |
|---|---|---:|---:|---:|
| Fable 5.1 | Claude Code | 44m | 154,748.5 | 36.8 |
| Opus 5 | Claude Code | 55m | 146,426.8 | 170.8 |
| GPT-5.6 Sol | Codex CLI | 12m | 39,581.6 | 75.9 |
| GLM 5.3 | mini-SWE-agent | 1h | 192,306.6 | 183.6 |
