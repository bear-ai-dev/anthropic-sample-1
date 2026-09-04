# Saved-submission cutover replay

Fable 5.1 + Claude Code, Sample 1 Task 4, trial 6. No model calls and no new rollout. Original and corrected replay input file hashes match exactly.

| Run | Reward | Harness flag | Meaning |
|---|---:|---:|---|
| Original verifier | 0 | 1 | Reproduces the retired-ledger corruption-probe error |
| Corrected verifier | 0 | 0 | Completes and fails shadow-copy rule R1: 86 members missing |
| Reference solution, corrected verifier | 1 | 0 | All counted rules hold |
| No-op, corrected verifier | 0 | 0 | Migration is not implemented |

The [patch](driver.patch) changes only the verifier-owned retired-row corruption probe: it suspends member-table triggers inside one transaction, corrupts the retired row, and restores the exact trigger definitions before committing. Ordinary writes remain blocked. Targeted regressions check original rejection, successful corruption plus restored guards, rollback on error, and the independent two-connection lock mechanism.

The [manifest](manifest.json) records hashes of the control and replay evidence. The [effective result](effective-result.json) leaves the original score unchanged but supplies a valid, completed grading outcome. The [submitted-code excerpt](submission-excerpt.json) shows why members without a movement in the copied prefix are absent. Original result files are not overwritten.

This audit package intentionally omits the licensed full workspace. Replaying requires the authorized execution workspace plus the saved submission, the original pinned Gel image, and this verifier patch. The local replay runner's setup failures are not additional model trials and never enter the denominator.
