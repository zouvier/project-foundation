# ADR 0001: Start with one profile and a common command contract

Status: Accepted starting decision; revise with project-specific evidence.

## Context and decision

This project starts with one stack profile and exposes `./project doctor|bootstrap|dev|check|test|build`. Humans, editor tasks, CI, and agents use the same interface. The architecture document maps source ownership, and executable checks enforce the supported import boundaries and record schemas.

Domain source, tests, README, architecture, decisions, and task records belong to this project. The foundation supplies explicit, reviewable updates to contract tooling. `.copier-answers.yml` records template lineage and must remain under Copier's control.

## Consequences and next decision

The initial example demonstrates a small behavior and is ready to replace. It does not establish this project's product requirements. Start with a bounded task, actual acceptance evidence, and a new decision when adding a database, deployment target, provider integration, or source layer.

Agent role descriptions coordinate work; they do not grant access. Git worktrees separate working files and branches, while credentials and network access require separate execution controls.
