# Coordination handoff

The foundation and the preserved [orchestration prototype](../orchestration/README.md) now share this source repository. Copier still generates only `template/`. Each generated project keeps its own repository, decisions, task records and dependencies; orchestration source and durable state are not copied into applications.

The prototype records manually registered projects, bounded tasks, independent reviews, exact-artifact acceptance and evidence-backed improvement proposals. Offline tests exercise these contracts. One historical real Codex builder/reviewer trial used a fixed arithmetic fixture; it did not use a foundation-generated project or validate general worker containment. Production workers remain disabled.

Custom runtime development is closed. Future coordination is intended to use [Orca](https://github.com/stablyai/orca), which has not been installed or validated here. Automatic pinned generation/registration and the connection between project handoff records and runtime tasks remain unfinished. The [closeout and handoff](../orchestration/docs/integration-plan.md) explains the exact boundary, existing evidence and remaining integration work.

Foundation changes should continue as reviewed commits in this repository with regression tests and immutable releases. Existing projects remain pinned until a human accepts an upgrade. Improvement notes are evidence for a future change, never permission to rewrite active templates, expand worker access or deploy an application.
