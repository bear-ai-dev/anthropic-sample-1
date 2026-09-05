# Fable 5.1 + Claude Code: per-trial review

Analyst review of recovered verifier checks, selected submitted implementation paths and observable final-answer/tool context. Not a claim to have reread every trajectory end-to-end.

One primary label per trial. The JSON retains all observed failing checks, so the primary label does not imply only one defect. Confidence applies to the label, not every causal detail. Agent self-reported tests are claims, not independent passing controls.

The earlier 64.5% / 22.6% / 12.9% paragraph is withdrawn. It was based on inherited labels without a per-trial evidence table.

| Task | Trial | Effective outcome | Primary label | Evidence |
|---|---:|---|---|---|
| 1 | 1 | 0 | WRONG_LOGIC | [review](#task-1-trial-1) |
| 1 | 2 | 0 | WRONG_LOGIC | [review](#task-1-trial-2) |
| 1 | 3 | 0 | WRONG_LOGIC | [review](#task-1-trial-3) |
| 1 | 4 | 0 | WRONG_LOGIC | [review](#task-1-trial-4) |
| 1 | 5 | 0 | WRONG_LOGIC | [review](#task-1-trial-5) |
| 1 | 6 | 0 | WRONG_LOGIC | [review](#task-1-trial-6) |
| 1 | 7 | 0 | WRONG_LOGIC | [review](#task-1-trial-7) |
| 1 | 8 | 0 | WRONG_LOGIC | [review](#task-1-trial-8) |
| 2 | 1 | 0 | WRONG_LOGIC | [review](#task-2-trial-1) |
| 2 | 2 | 0 | UNVERIFIED_ASSUMPTION | [review](#task-2-trial-2) |
| 2 | 3 | 0 | UNVERIFIED_ASSUMPTION | [review](#task-2-trial-3) |
| 2 | 4 | 0 | WRONG_LOGIC | [review](#task-2-trial-4) |
| 2 | 5 | 0 | WRONG_LOGIC | [review](#task-2-trial-5) |
| 2 | 6 | 1 | SOLVED | [review](#task-2-trial-6) |
| 2 | 7 | 0 | MISSED_REQUIREMENT | [review](#task-2-trial-7) |
| 2 | 8 | 0 | WRONG_LOGIC | [review](#task-2-trial-8) |
| 3 | 1 | 0 | WRONG_LOGIC | [review](#task-3-trial-1) |
| 3 | 2 | 0 | WRONG_LOGIC | [review](#task-3-trial-2) |
| 3 | 3 | 0 | WRONG_LOGIC | [review](#task-3-trial-3) |
| 3 | 4 | 1 | SOLVED | [review](#task-3-trial-4) |
| 3 | 5 | 0 | WRONG_LOGIC | [review](#task-3-trial-5) |
| 3 | 6 | 1 | SOLVED | [review](#task-3-trial-6) |
| 3 | 7 | 1 | SOLVED | [review](#task-3-trial-7) |
| 3 | 8 | 1 | SOLVED | [review](#task-3-trial-8) |
| 4 | 1 | 1 | SOLVED | [review](#task-4-trial-1) |
| 4 | 2 | 0 | WRONG_LOGIC | [review](#task-4-trial-2) |
| 4 | 3 | 0 | WRONG_LOGIC | [review](#task-4-trial-3) |
| 4 | 4 | 0 | WRONG_LOGIC | [review](#task-4-trial-4) |
| 4 | 5 | 0 | WRONG_LOGIC | [review](#task-4-trial-5) |
| 4 | 6 | 0 | WRONG_LOGIC | [review](#task-4-trial-6) |
| 4 | 7 | 0 | WRONG_LOGIC | [review](#task-4-trial-7) |
| 4 | 8 | 0 | WRONG_LOGIC | [review](#task-4-trial-8) |
| 5 | 1 | 0 | WRONG_LOGIC | [review](#task-5-trial-1) |
| 5 | 2 | 0 | WRONG_LOGIC | [review](#task-5-trial-2) |
| 5 | 3 | 0 | WRONG_LOGIC | [review](#task-5-trial-3) |
| 5 | 4 | 1 | SOLVED | [review](#task-5-trial-4) |
| 5 | 5 | 1 | SOLVED | [review](#task-5-trial-5) |
| 5 | 6 | 0 | WRONG_LOGIC | [review](#task-5-trial-6) |
| 5 | 7 | 1 | SOLVED | [review](#task-5-trial-7) |
| 5 | 8 | 0 | WRONG_LOGIC | [review](#task-5-trial-8) |

## Task 1, trial 1

Rebuild keeps ordinary in-pattern occurrence identities instead of replacing them; the survivor and money-across-operations checks fail.

- [Requirement](../tasks/01-recurring-events/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/01-recurring-events/trial-01/recovered-verifier/reward-detail.json); [trajectory](../trajectories/01-recurring-events/fable-5.1-claude-code/trajectory-trial-01.json), step 27.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: R25-survivor-identity, R26-money-across-operations

## Task 1, trial 2

Rebuild explicitly keeps all in-pattern unpublished occurrences, not only manually moved survivors; ordinary rows retain their old identities.

- [Requirement](../tasks/01-recurring-events/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/01-recurring-events/trial-02/recovered-verifier/reward-detail.json); [trajectory](../trajectories/01-recurring-events/fable-5.1-claude-code/trajectory-trial-02.json), step 25.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: R25-survivor-identity, R26-money-across-operations

## Task 1, trial 3

The implementation refreshes untouched rows in place under their existing identities; the verifier requires these rows to be replaced.

- [Requirement](../tasks/01-recurring-events/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/01-recurring-events/trial-03/recovered-verifier/reward-detail.json); [trajectory](../trajectories/01-recurring-events/fable-5.1-claude-code/trajectory-trial-03.json), step 27.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: R25-survivor-identity, R26-money-across-operations

## Task 1, trial 4

Extend chooses the wrong future dates after rebuilding, and the protection predicate refuses an allowed edit.

- [Requirement](../tasks/01-recurring-events/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/01-recurring-events/trial-04/recovered-verifier/reward-detail.json); [trajectory](../trajectories/01-recurring-events/fable-5.1-claude-code/trajectory-trial-04.json), step 23.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: R19-extend-after-regenerate, R25-survivor-identity, R26-money-across-operations

## Task 1, trial 5

Extend infers the pattern phase from held dates and selects incorrect dates after rebuilding; an allowed edit is also refused.

- [Requirement](../tasks/01-recurring-events/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/01-recurring-events/trial-05/recovered-verifier/reward-detail.json); [trajectory](../trajectories/01-recurring-events/fable-5.1-claude-code/trajectory-trial-05.json), step 52.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: R19-extend-after-regenerate, R25-survivor-identity

## Task 1, trial 6

Rebuild refreshes untouched rows in place, preserving identities that the rebuild is expected to replace.

- [Requirement](../tasks/01-recurring-events/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/01-recurring-events/trial-06/recovered-verifier/reward-detail.json); [trajectory](../trajectories/01-recurring-events/fable-5.1-claude-code/trajectory-trial-06.json), step 30.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: R25-survivor-identity, R26-money-across-operations

## Task 1, trial 7

Composed operations lose the template time of day and retain ordinary in-pattern identities; basic standalone recurrence tests are not sufficient.

- [Requirement](../tasks/01-recurring-events/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/01-recurring-events/trial-07/recovered-verifier/reward-detail.json); [trajectory](../trajectories/01-recurring-events/fable-5.1-claude-code/trajectory-trial-07.json), step 30.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: R8-protect-published, R9-edited-survives, R10-extend, R11-concurrent-regenerate, R18-extend-fills-gap, R25-survivor-identity, R26-money-across-operations

## Task 1, trial 8

Rebuild explicitly refreshes unedited rows under their existing IDs; the survivor-identity and money-across-operations checks reject this behavior.

- [Requirement](../tasks/01-recurring-events/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/01-recurring-events/trial-08/recovered-verifier/reward-detail.json); [trajectory](../trajectories/01-recurring-events/fable-5.1-claude-code/trajectory-trial-08.json), step 75.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: R25-survivor-identity, R26-money-across-operations

## Task 2, trial 1

The field-level merge is implemented, but concurrent media replacement leaves an obsolete hosted picture in the recovered draft.

- [Requirement](../tasks/02-draft-recovery/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/02-draft-recovery/trial-01/recovered-verifier/reward-detail.json); [trajectory](../trajectories/02-draft-recovery/fable-5.1-claude-code/trajectory-trial-01.json), step 20.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- [Full assertion report](../results/fable-5.1-claude-code/tasks/02-draft-recovery/trial-01/recovered-verifier/verifier-report.json).
- Failing checks: R13 two pages editing one draft takes a picture out of the record when one tab replaces it from disk, R2 pictures that cannot be written down stops speaking for a picture once the one on the form came from disk

## Task 2, trial 2

The submission deliberately changes duplicate:new to per-source-event keys and refuses supplied usable duplicate records; several flush and field-persistence checks also fail.

- [Requirement](../tasks/02-draft-recovery/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/02-draft-recovery/trial-02/recovered-verifier/reward-detail.json); [trajectory](../trajectories/02-draft-recovery/fable-5.1-claude-code/trajectory-trial-02.json), step 16.
- Primary label: `UNVERIFIED_ASSUMPTION`; confidence: high.
- [Full assertion report](../results/fable-5.1-claude-code/tasks/02-draft-recovery/trial-02/recovered-verifier/verifier-report.json).
- Failing checks: R12 a document taken off, and one only just chosen holds no document at all in a flow that never had one, R12 a document taken off, and one only just chosen does not lose a document taken off a moment before the page went away, R5 records written by the previous release applies an old record in the duplicate flow, which names no event either, R2 pictures that cannot be written down keeps a library picture in a duplicate, and the typing beside it, R2 pictures that cannot be written down loses nothing when the page goes away with a picture from disk on the form, R6 records that cannot be read still saves after finding something unreadable, and keeps saving, R3 the gallery is a list, not a picture carries the gallery of a duplicate without the picture from disk, R11 work that a section of its own put into the form does not lose a question written a moment before the page went away, R11 work that a section of its own put into the form carries three sections' work out of one page that went away, R10 writing for the work rather than for the keystroke does not spend a write on every keystroke, R10 writing for the work rather than for the keystroke does not lose what was typed a moment before the page went away

## Task 2, trial 3

The submission refuses the supplied duplicate:new and earlier duplicate records based on a newly imposed source-event requirement; question persistence also fails.

- [Requirement](../tasks/02-draft-recovery/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/02-draft-recovery/trial-03/recovered-verifier/reward-detail.json); [trajectory](../trajectories/02-draft-recovery/fable-5.1-claude-code/trajectory-trial-03.json), step 17.
- Primary label: `UNVERIFIED_ASSUMPTION`; confidence: high.
- [Full assertion report](../results/fable-5.1-claude-code/tasks/02-draft-recovery/trial-03/recovered-verifier/verifier-report.json).
- Failing checks: R5 records written by the previous release applies an old record in the duplicate flow, which names no event either, R11 work that a section of its own put into the form brings back a question written in the questions section

## Task 2, trial 4

A per-session/channel implementation exists, but one tab saving a field overwrites work held by the other tab.

- [Requirement](../tasks/02-draft-recovery/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/02-draft-recovery/trial-04/recovered-verifier/reward-detail.json); [trajectory](../trajectories/02-draft-recovery/fable-5.1-claude-code/trajectory-trial-04.json), step 14.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- [Full assertion report](../results/fable-5.1-claude-code/tasks/02-draft-recovery/trial-04/recovered-verifier/verifier-report.json).
- Failing checks: R13 two pages editing one draft keeps the questions one tab wrote when the other tab saves a title, R13 two pages editing one draft keeps the title one tab wrote when the other tab saves questions, R13 two pages editing one draft keeps a picture one tab removed when the other tab saves a title, R13 two pages editing one draft keeps a document one tab took off when the other tab saves a title, R13 two pages editing one draft keeps both tabs' work when each saves twice, in turn, R13 two pages editing one draft does not let the tab that never touched the title put the old one back, R13 two pages editing one draft hands a third tab everything the first two put in

## Task 2, trial 5

Session queues exist, but question persistence and two-tab field preservation fail under the shared-storage checks.

- [Requirement](../tasks/02-draft-recovery/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/02-draft-recovery/trial-05/recovered-verifier/reward-detail.json); [trajectory](../trajectories/02-draft-recovery/fable-5.1-claude-code/trajectory-trial-05.json), step 18.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- [Full assertion report](../results/fable-5.1-claude-code/tasks/02-draft-recovery/trial-05/recovered-verifier/verifier-report.json).
- Failing checks: R13 two pages editing one draft keeps the questions one tab wrote when the other tab saves a title, R13 two pages editing one draft keeps the title one tab wrote when the other tab saves questions, R13 two pages editing one draft keeps a picture one tab removed when the other tab saves a title, R13 two pages editing one draft keeps a document one tab took off when the other tab saves a title, R13 two pages editing one draft keeps both tabs' work when each saves twice, in turn, R13 two pages editing one draft does not let the tab that never touched the title put the old one back, R13 two pages editing one draft hands a third tab everything the first two put in, R11 work that a section of its own put into the form brings back a question written in the questions section

## Task 2, trial 6

All counted verifier rules pass in the retained evidence.

- [Requirement](../tasks/02-draft-recovery/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/02-draft-recovery/trial-06/recovered-verifier/reward-detail.json); [trajectory](../trajectories/02-draft-recovery/fable-5.1-claude-code/trajectory-trial-06.json), step 18.
- Primary label: `SOLVED`; confidence: high.
- [Full assertion report](../results/fable-5.1-claude-code/tasks/02-draft-recovery/trial-06/recovered-verifier/verifier-report.json).
- Failing checks: See grader/adjudication record; no completed failed-rule list.

## Task 2, trial 7

The final answer explicitly leaves two-tab overwrite unresolved. Seven concurrency assertions fail independently of the missing-control flag. The loading-only layout also hides controls while storage is slow.

- [Requirement](../tasks/02-draft-recovery/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/02-draft-recovery/trial-07/recovered-verifier/reward-detail.json); [trajectory](../trajectories/02-draft-recovery/fable-5.1-claude-code/trajectory-trial-07.json), step 14.
- Primary label: `MISSED_REQUIREMENT`; confidence: high.
- [Full assertion report](../results/fable-5.1-claude-code/tasks/02-draft-recovery/trial-07/recovered-verifier/verifier-report.json).
- Failing checks: R13 two pages editing one draft keeps the questions one tab wrote when the other tab saves a title, R13 two pages editing one draft keeps the title one tab wrote when the other tab saves questions, R13 two pages editing one draft keeps a picture one tab removed when the other tab saves a title, R13 two pages editing one draft keeps a document one tab took off when the other tab saves a title, R13 two pages editing one draft keeps both tabs' work when each saves twice, in turn, R13 two pages editing one draft does not let the tab that never touched the title put the old one back, R13 two pages editing one draft hands a third tab everything the first two put in, R5 records written by the previous release does not let an old record roll back typing done while it was being read, R2 pictures that cannot be written down stops speaking for a picture once the one on the form came from disk, R11 work that a section of its own put into the form keeps a question written while the store was still answering, R8 a draft that arrives late does not roll back what was typed while the store was slow, R8 a draft that arrives late saves what was typed while the store was slow, R8 a draft that arrives late does not roll back a picture chosen while the store was slow

## Task 2, trial 8

Read-before-write merging is implemented, but three shared-draft concurrency assertions still lose another page's changes.

- [Requirement](../tasks/02-draft-recovery/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/02-draft-recovery/trial-08/recovered-verifier/reward-detail.json); [trajectory](../trajectories/02-draft-recovery/fable-5.1-claude-code/trajectory-trial-08.json), step 18.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- [Full assertion report](../results/fable-5.1-claude-code/tasks/02-draft-recovery/trial-08/recovered-verifier/verifier-report.json).
- Failing checks: R13 two pages editing one draft keeps the title one tab wrote when the other tab saves questions, R13 two pages editing one draft keeps both tabs' work when each saves twice, in turn, R13 two pages editing one draft does not let the tab that never touched the title put the old one back

## Task 3, trial 1

Conversation merging is implemented, but merged-history and closure/window behavior fail R11; a successful replay of the small recorded desk is not a counterexample to these larger scenarios.

- [Requirement](../tasks/03-envelope-intake/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/03-envelope-intake/trial-01/recovered-verifier/reward-detail.json); [trajectory](../trajectories/03-envelope-intake/fable-5.1-claude-code/trajectory-trial-01.json), step 16.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: R11

## Task 3, trial 2

The submission explicitly leaves two closed tickets unmerged. The graded merged-history scenarios reject that policy; the final answer itself notes that the small recording does not disambiguate every policy choice.

- [Requirement](../tasks/03-envelope-intake/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/03-envelope-intake/trial-02/recovered-verifier/reward-detail.json); [trajectory](../trajectories/03-envelope-intake/fable-5.1-claude-code/trajectory-trial-02.json), step 22.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: R11

## Task 3, trial 3

The implemented merge chooses an incorrect survivor/history state in the composed closed/open conversation scenario.

- [Requirement](../tasks/03-envelope-intake/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/03-envelope-intake/trial-03/recovered-verifier/reward-detail.json); [trajectory](../trajectories/03-envelope-intake/fable-5.1-claude-code/trajectory-trial-03.json), step 14.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: R11

## Task 3, trial 4

All counted verifier rules pass in the retained evidence.

- [Requirement](../tasks/03-envelope-intake/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/03-envelope-intake/trial-04/recovered-verifier/reward-detail.json); [trajectory](../trajectories/03-envelope-intake/fable-5.1-claude-code/trajectory-trial-04.json), step 19.
- Primary label: `SOLVED`; confidence: high.
- Failing checks: See grader/adjudication record; no completed failed-rule list.

## Task 3, trial 5

Conversation merging and desk participation are implemented but produce incorrect merged history and closure/window behavior.

- [Requirement](../tasks/03-envelope-intake/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/03-envelope-intake/trial-05/recovered-verifier/reward-detail.json); [trajectory](../trajectories/03-envelope-intake/fable-5.1-claude-code/trajectory-trial-05.json), step 16.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: R11, R16

## Task 3, trial 6

All counted verifier rules pass in the retained evidence.

- [Requirement](../tasks/03-envelope-intake/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/03-envelope-intake/trial-06/recovered-verifier/reward-detail.json); [trajectory](../trajectories/03-envelope-intake/fable-5.1-claude-code/trajectory-trial-06.json), step 19.
- Primary label: `SOLVED`; confidence: high.
- Failing checks: See grader/adjudication record; no completed failed-rule list.

## Task 3, trial 7

All counted verifier rules pass in the retained evidence.

- [Requirement](../tasks/03-envelope-intake/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/03-envelope-intake/trial-07/recovered-verifier/reward-detail.json); [trajectory](../trajectories/03-envelope-intake/fable-5.1-claude-code/trajectory-trial-07.json), step 19.
- Primary label: `SOLVED`; confidence: high.
- Failing checks: See grader/adjudication record; no completed failed-rule list.

## Task 3, trial 8

All counted verifier rules pass in the retained evidence.

- [Requirement](../tasks/03-envelope-intake/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/03-envelope-intake/trial-08/recovered-verifier/reward-detail.json); [trajectory](../trajectories/03-envelope-intake/fable-5.1-claude-code/trajectory-trial-08.json), step 17.
- Primary label: `SOLVED`; confidence: high.
- Failing checks: See grader/adjudication record; no completed failed-rule list.

## Task 4, trial 1

All counted verifier rules pass in the retained evidence.

- [Requirement](../tasks/04-store-cutover/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/04-store-cutover/trial-01/recovered-verifier/reward-detail.json); [trajectory](../trajectories/04-store-cutover/fable-5.1-claude-code/trajectory-trial-01.json), step 29.
- Primary label: `SOLVED`; confidence: high.
- Failing checks: See grader/adjudication record; no completed failed-rule list.

## Task 4, trial 2

Final destination reconciliation retains foreign movements and a post-authority read is behind the authoritative ledger.

- [Requirement](../tasks/04-store-cutover/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/04-store-cutover/trial-02/recovered-verifier/reward-detail.json); [trajectory](../trajectories/04-store-cutover/fable-5.1-claude-code/trajectory-trial-02.json), step 38.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: cutover/R10, cutover/R13

## Task 4, trial 3

The composed cutover loses late movements and allows a superseded worker to affect state; final reconciliation and fresh-read checks fail.

- [Requirement](../tasks/04-store-cutover/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/04-store-cutover/trial-03/recovered-verifier/reward-detail.json); [trajectory](../trajectories/04-store-cutover/fable-5.1-claude-code/trajectory-trial-03.json), step 56.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: cutover/R10, cutover/R13, cutover/R5, cutover/R8, handover/R10, handover/R8

## Task 4, trial 4

The composed cutover loses late movements and does not fully fence a stale worker; end-state reconciliation and freshness checks fail.

- [Requirement](../tasks/04-store-cutover/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/04-store-cutover/trial-04/recovered-verifier/reward-detail.json); [trajectory](../trajectories/04-store-cutover/fable-5.1-claude-code/trajectory-trial-04.json), step 29.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: cutover/R10, cutover/R13, cutover/R5, cutover/R8, handover/R10, handover/R8

## Task 4, trial 5

The candidate holds the legacy SQLite write transaction across the parked authority-write call. The verifier's concurrent legacy writer consequently hits database is locked; this is a submission-induced liveness failure, not a provider failure.

- [Requirement](../tasks/04-store-cutover/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/04-store-cutover/trial-05/recovered-verifier/reward-detail.json); [trajectory](../trajectories/04-store-cutover/fable-5.1-claude-code/trajectory-trial-05.json), step 28.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: See grader/adjudication record; no completed failed-rule list.

## Task 4, trial 6

The original verifier tries to corrupt retired legacy rows through a legitimate database write-blocking trigger. The original zero is task-side and is not a model failure; use a controlled saved-submission replay for the effective outcome. The original retirement-trigger error reproduces. With only the verifier fault-injection correction, grading completes at reward 0 with no harness flag. R1 fails because the shadow copy omits 86 members. The candidate copies member rows only for IDs touched by ledger batches, rather than the complete member book.

- [Requirement](../tasks/04-store-cutover/instruction.md); [verifier detail](../analysis/cutover-replay/corrected/reward-detail.json); [trajectory](../trajectories/04-store-cutover/fable-5.1-claude-code/trajectory-trial-06.json), step 35.
- Primary label: `WRONG_LOGIC`; confidence: high.
- Failing checks: cutover/R1

## Task 4, trial 7

Shadow member balances do not match the ledger prefix, late movements are not replayed, and legacy traffic is closed too early.

- [Requirement](../tasks/04-store-cutover/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/04-store-cutover/trial-07/recovered-verifier/reward-detail.json); [trajectory](../trajectories/04-store-cutover/fable-5.1-claude-code/trajectory-trial-07.json), step 21.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: cutover/R1, cutover/R13, cutover/R15, cutover/R8

## Task 4, trial 8

BEGIN IMMEDIATE is held across the parked authority write. Another legacy writer cannot proceed until that call returns, causing a cutover deadlock under the supplied storage fault.

- [Requirement](../tasks/04-store-cutover/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/04-store-cutover/trial-08/recovered-verifier/reward-detail.json); [trajectory](../trajectories/04-store-cutover/fable-5.1-claude-code/trajectory-trial-08.json), step 29.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: See grader/adjudication record; no completed failed-rule list.

## Task 5, trial 1

Late log positions are missing from v2; the gate remains at SWITCH and v1 is never retired.

- [Requirement](../tasks/05-readmodel-rebuild/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/05-readmodel-rebuild/trial-01/recovered-verifier/reward-detail.json); [trajectory](../trajectories/05-readmodel-rebuild/fable-5.1-claude-code/trajectory-trial-01.json), step 31.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: R2, R6, R9

## Task 5, trial 2

The implemented parity gate never advances under the graded run; v1 remains at PARITY rather than completing and retiring.

- [Requirement](../tasks/05-readmodel-rebuild/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/05-readmodel-rebuild/trial-02/recovered-verifier/reward-detail.json); [trajectory](../trajectories/05-readmodel-rebuild/fable-5.1-claude-code/trajectory-trial-02.json), step 43.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: R6

## Task 5, trial 3

The grader observes mixed generations across the three routing keys during the switch, despite the final answer's whole-generation guarantee.

- [Requirement](../tasks/05-readmodel-rebuild/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/05-readmodel-rebuild/trial-03/recovered-verifier/reward-detail.json); [trajectory](../trajectories/05-readmodel-rebuild/fable-5.1-claude-code/trajectory-trial-03.json), step 51.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: R5

## Task 5, trial 4

All counted verifier rules pass in the retained evidence.

- [Requirement](../tasks/05-readmodel-rebuild/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/05-readmodel-rebuild/trial-04/recovered-verifier/reward-detail.json); [trajectory](../trajectories/05-readmodel-rebuild/fable-5.1-claude-code/trajectory-trial-04.json), step 31.
- Primary label: `SOLVED`; confidence: high.
- Failing checks: See grader/adjudication record; no completed failed-rule list.

## Task 5, trial 5

All counted verifier rules pass in the retained evidence.

- [Requirement](../tasks/05-readmodel-rebuild/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/05-readmodel-rebuild/trial-05/recovered-verifier/reward-detail.json); [trajectory](../trajectories/05-readmodel-rebuild/fable-5.1-claude-code/trajectory-trial-05.json), step 31.
- Primary label: `SOLVED`; confidence: high.
- Failing checks: See grader/adjudication record; no completed failed-rule list.

## Task 5, trial 6

Late positions are missing and the drain/cleanup never completes; the final v2 projection is behind the log.

- [Requirement](../tasks/05-readmodel-rebuild/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/05-readmodel-rebuild/trial-06/recovered-verifier/reward-detail.json); [trajectory](../trajectories/05-readmodel-rebuild/fable-5.1-claude-code/trajectory-trial-06.json), step 24.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: R2, R6, R9

## Task 5, trial 7

All counted verifier rules pass in the retained evidence.

- [Requirement](../tasks/05-readmodel-rebuild/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/05-readmodel-rebuild/trial-07/recovered-verifier/reward-detail.json); [trajectory](../trajectories/05-readmodel-rebuild/fable-5.1-claude-code/trajectory-trial-07.json), step 40.
- Primary label: `SOLVED`; confidence: high.
- Failing checks: See grader/adjudication record; no completed failed-rule list.

## Task 5, trial 8

The parity path never advances under the graded run and leaves v1 intact. The final-answer smoke claim does not establish completion under these conditions.

- [Requirement](../tasks/05-readmodel-rebuild/instruction.md); [verifier detail](../results/fable-5.1-claude-code/tasks/05-readmodel-rebuild/trial-08/recovered-verifier/reward-detail.json); [trajectory](../trajectories/05-readmodel-rebuild/fable-5.1-claude-code/trajectory-trial-08.json), step 43.
- Primary label: `WRONG_LOGIC`; confidence: medium.
- Failing checks: R6
