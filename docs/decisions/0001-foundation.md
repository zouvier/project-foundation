# ADR 0001: A versioned project contract before company orchestration

Date: 2026-10-30
Status: Accepted for the v0.1 design; implementation evidence is recorded separately.

## Context

Inconsistent project starts force both the human and coding agents to rediscover setup, source layout, commands, and completion criteria. The foundation must support independent projects and remain usable as editors, model providers, and orchestration tools change.

## Decision

Maintain three layers: a versioned Copier template repository; independently generated project repositories; a later company workspace that catalogs and coordinates them. Each project keeps its own decisions and task records. There is no shared global agent memory that silently supplies requirements across projects.

Generate one profile at a time: TypeScript web or Python service. Both implement `./project doctor|bootstrap|dev|check|test|build`, with the same meanings documented in the generated README. CI and VS Code invoke these commands. Lock dependencies. Make installation explicit. Validation fails for missing prerequisites, invalid records, broken tests, or unresolved merge artifacts and does not repair tracked files.

Use Copier's recorded lineage and explicit template releases for upgrades. Seed domain files once; exclude them during updates. Template-managed contract files remain reviewable upgrade candidates. A clean upgrade branch and human conflict resolution are required. The answers file belongs to Copier. [Update behavior](https://copier.readthedocs.io/en/stable/updating/), [conditional exclusions](https://copier.readthedocs.io/en/stable/configuring/#exclude).

Keep `AGENTS.md` as a small map. Use minimal coordinator, builder, reviewer, and researcher role descriptions referencing the same task record. Put dependency boundaries and metadata rules in executable checks. Roles and allowed-path fields express workflow intent; they do not create security boundaries.

## Alternatives and consequences

Cookiecutter replay reproduces inputs but does not supply the chosen lifecycle. Nx and Turborepo remain options inside projects that acquire a real multi-package task graph. Backstage may later catalog projects. LangGraph or Paperclip may later coordinate work. Their differing responsibilities and source evidence are detailed in [the research memo](../research.md).

This choice adds template release and upgrade maintenance, plus a small command wrapper per profile. It avoids making generated applications depend on a central runtime. Project owners can change domain code freely while contract changes receive explicit review.

The first release targets macOS and Linux; native Windows is unverified. Smoke fixtures demonstrate behavior only in the environments actually exercised. A fresh-agent acceptance test and representative real projects are the next evidence needed before expanding profiles or making efficiency claims.

## Revisit when

- Repeated real projects require another stack profile or a shared multi-package graph.
- An upgrade cannot preserve project-owned files or creates ambiguous ownership.
- Fresh-agent tests identify unnecessary discovery, misleading instructions, or missing checks.
- Cross-project coordination requires durable scheduling, approvals, or run-state recovery beyond an explicit task handoff.
