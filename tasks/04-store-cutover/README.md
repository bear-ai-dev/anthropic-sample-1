The agent has access to the full source code for a private membership ledger, operational cutover records, and local repository history. It must move the live financial ledger from a legacy store to an empty destination without pausing reads or writes, losing or double-counting movements, or returning superseded balances. Authority must switch exactly once and never return to the legacy store.

| Model | Harness | Passes | Scored rollouts | Pass rate |
|---|---|---:|---:|---:|
| Fable 5.1 | Claude Code | 1 | 8 | 12.5% |
| Opus 5 | Claude Code | 2 | 8 | 25.0% |
| GPT-5.6 Sol | Codex CLI | 1 | 8 | 12.5% |
| Grok 4.6 | Grok Build | 3 | 8 | 37.5% |
| GLM 5.3 | mini-SWE-agent | 0 | 8 | 0.0% |

| Model | Harness | Mean wall clock | Mean output tokens | Mean steps |
|---|---|---:|---:|---:|
| Fable 5.1 | Claude Code | 36m | 140,021.4 | 33.1 |
| Opus 5 | Claude Code | 1h 17m | 223,063.8 | 160.9 |
| GPT-5.6 Sol | Codex CLI | 13m | 46,636.8 | 65.9 |
| Grok 4.6 | Grok Build | 1h 29m | 298,910.4 | 53.8 |
| GLM 5.3 | mini-SWE-agent | 1h 16m | 230,445.1 | 202.5 |
