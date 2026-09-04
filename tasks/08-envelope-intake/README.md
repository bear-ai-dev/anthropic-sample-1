The agent has access to the full source code for a private support desk and a local mailbox with example conversations. It must group retried, concurrent, and out-of-order email envelopes into the correct customer ticket without mixing unrelated mail. Agent replies must survive retries and be sent exactly once, while later customer replies either reopen the ticket or start a linked follow-up according to the closing window.

| Model | Harness | Passes | Scored rollouts | Pass rate |
|---|---|---:|---:|---:|
| Fable 5.1 | Claude Code | 4 | 8 | 50.0% |
| Opus 5 | Claude Code | 4 | 8 | 50.0% |
| GPT-5.6 Sol | Codex CLI | 0 | 8 | 0.0% |
| GLM 5.3 | mini-SWE-agent | 0 | 8 | 0.0% |

| Model | Harness | Mean wall clock | Mean output tokens | Mean steps |
|---|---|---:|---:|---:|
| Fable 5.1 | Claude Code | 16m | 77,175.1 | 17.8 |
| Opus 5 | Claude Code | 55m | 110,826.9 | 90.8 |
| GPT-5.6 Sol | Codex CLI | 10m | 41,077.0 | 55.0 |
| GLM 5.3 | mini-SWE-agent | 53m | 145,626.3 | 115.0 |
