# Task provenance

The sample is derived from licensed, mature enterprise application code and
operational history, plus tasks written to specifications grounded in real
support, migration, and projection workflows. Restricted company names,
repository names, ticket identifiers, and application workspaces are omitted.

| Task | Licensed source class | Workflow basis | Published material |
|---|---|---|---|
| Task 1 | Go service backend | Recurring-event lifecycle and protected occurrences | Contract, harness, verifier, reference solution |
| Task 2 | React/TypeScript web application | Form draft persistence and recovery | Contract, harness, verifier, reference solution |
| Task 3 | Support and mailbox workflow | Envelope routing and identity aliases | Contract, harness, verifier, reference solution |
| Task 4 | Store-migration workflow | Lease-fenced online cutover | Contract, harness, verifier, reference solution |
| Task 5 | Search and activity projections | Concurrent read-model rebuild | Contract, harness, verifier, reference solution |

Task numbers 1–5 match the proposal and the published task, trajectory, result,
and control folders. Original execution IDs are retained as `source_task` in
the indexes; recorded trajectories and verifier payloads remain unchanged.

The frozen execution hashes in [`indexes/task-publication.json`](../indexes/task-publication.json)
identify the exact packages used for evaluation. Published task-package hashes
cover the privacy-safe materials in this repository. This separation keeps the
evaluation auditable without redistributing licensed application workspaces or
restricted operational identifiers.
