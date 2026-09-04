# Sample 1 handoff and evidence scope

This is an audit package, not a self-contained runnable licensed-environment delivery. Application workspaces and provider-native session material are intentionally omitted. Do not promise a clean-machine task build from these Dockerfiles alone. A runnable delivery needs a separately authorized workspace/image and bootstrap route.

## What can be checked here

- The scored index preserves model, harness, task and trial identities.
- `analysis/recovered-evidence.json` joins all 40 Fable Claude Code trials to the original AWS verifier bundles by `trial_name`, matching the original verifier result and recording original/redacted hashes.
- `analysis/fable-failure-modes.json` and `analysis/README.md` give a per-trial label with requirement, verifier and observable trace references. They replace the inherited 64.5% / 22.6% / 12.9% causal breakdown.
- `analysis/admission-review.json` adjudicates the seven nested harness flags. Original records are preserved; the completed cutover grader correction is a separate effective-result record. Its replay remains a model failure, so the recorded pass rates are unchanged.
- `control-results.json` now links to the ten original oracle/no-op control bundles under `controls/`. Controls are not model rollouts and do not enter the score denominator.

## Limits

Behavioral failure labels are an analyst's interpretation, not proof of the model's private reasoning or a unique root cause. Reference-solution success demonstrates solvability of that implementation, not an exhaustive fairness proof for every alternative implementation. Original and corrected verifier versions must remain distinguishable.

The original Opus results remain unchanged. No new Opus work is included in this follow-up. Some recovered original records carry a non-hexadecimal task-checksum marker; this release does not silently replace that marker with a stronger provenance claim.

GitHub reported admin access for `siddhantpaliwal2` on both sample repositories on September 4, 2026. This confirms that account's access only, not the identity or access of a separate Anthropic recipient. No invitations were sent and neither repository was made public.
