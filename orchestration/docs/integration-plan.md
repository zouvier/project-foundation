# Closeout and Orca handoff

The foundation and the preserved custom orchestration prototype live in the same public repository. Custom runtime development is closed. Future coordination is intended to use [Orca](https://github.com/stablyai/orca); no Orca installation, configuration, compatibility test or migration has been performed in this project.

## Repository boundary

```text
project-foundation/
  copier.yml              existing Copier entry point
  template/               only files copied into generated projects
  tests/                  foundation and combined-layout acceptance
  orchestration/          experimental coordinator, tests and fixture harness

independent-project/      separate Git repository outside this source checkout
  .copier-answers.yml     original template source and release reference
  .project/template.json generated provenance receipt
  .project/tasks/         project-owned handoff records
  src/ and tests/         project-owned application code
```

The public foundation release remains `v0.1.2`, commit `975e5ffe387cb474f9fbc8ffd38df601cdf1b1de`. Its tag, `copier.yml` and template bytes are unchanged. No orchestration tag or new foundation release is created. Existing projects keep their original pins and recorded source locations. Local-source projects still require that source location; changing lineage needs a separately reviewed migration.

## Completed connection and remaining work

Use the root README's pinned Copier command to create a project, then its own `./project` commands to install dependencies and check it explicitly. The preserved coordinator can record an existing project through its manual catalog, assign a bounded task at an exact Git revision, and retain review/checkpoint evidence. These records are local, editor-neutral JSON and SQLite.

The coordinator does not invoke Copier, validate a project's receipt against a trusted source release, bootstrap arbitrary projects, or map `.project/tasks/` into its own task schema. The catalog's `foundation_revision` is a human declaration, not provenance attestation. General model workers and a contained arbitrary-project check runner remain unavailable. A generated project can pass the offline task flow with test-only workers; that is not a deployed agent workflow.

The combined-layout tests generate both profiles from a source repository containing `orchestration/`, confirm that orchestration stays out of the generated tree, and exercise manual registration, task tracking, independent simulated review and exact-artifact acceptance. Human gates in these tests are simulated. Existing foundation tests separately exercise actual project commands, runtime checks and Copier upgrades.

## Carry forward into Orca

Use the project contract as the integration boundary: pinned generation, independent repositories, explicit `doctor/bootstrap/check/test/build` commands, and source-backed task/check evidence. Evaluate the future runtime's Codex adapter, authentication reuse, filesystem/network/tool controls, cancellation and approval gates before assigning real project work. The old one-trial read permission is not standing permission for Orca or ongoing workers.

Keep independent review bound to the actual artifact and actual checks. Human acceptance must name the reviewed artifact; it does not authorize merge, deployment, external messages or a foundation upgrade. Preserve useful failures in a source-backed improvement ledger. Foundation improvements remain separate reviewed changes with regression tests and human adoption; no agent may silently change the active template or existing project pins.

The historical live addition trial proves only a bounded two-turn protocol and fixed arithmetic checker. It did not generate a foundation project, validate arbitrary-project containment, run an overseer, or record human acceptance. Reuse its lessons, not its temporary permissions or private run data.

No daemon, schedule or autostart entry was created by this closeout. Local private prototype history, artifacts and workspaces remain intact outside this public snapshot. No license has been added.
