# Foundation research and design rationale

Sources inspected on **2026-10-30**. This memo supports the v0.1 design; it does not report test outcomes or claim better agent performance. Validation evidence belongs in the implementation's test report.

## The problem to solve first

Each project should give a human or a newly started agent the same answers to six questions: how to diagnose the environment, install dependencies, run locally, check a change, run tests, and produce a build. The source layout can differ by stack while the operating contract remains consistent. A small number of maintained profiles is easier to evaluate than an unrestricted collection of templates and agent personas.

Keep three independent layers:

| Layer | Owns | Relationship to the others |
| --- | --- | --- |
| Versioned `project-foundation` template repository | Copier questions, stack profiles, contract checks, template tests, release history | Produces new projects and supplies explicit, reviewed upgrades |
| Independently generated project repositories | Domain source, dependencies, architecture decisions, tasks, evidence, project history | Work without the foundation checkout, an editor extension, or an orchestration server after generation |
| Future company workspace | A project catalog, cross-project goals, assignments, and explicit links to project records | Invokes each project's existing contract; does not become shared global agent memory |

This separation is a design choice for portability and clear ownership. Cross-project learning should become a reviewed template improvement or an explicit linked decision. An agent's private conversation history should not silently become another project's requirements.

## Why Copier

| Candidate | Relevant documented capability | Decision for v0.1 |
| --- | --- | --- |
| [Copier](https://copier.readthedocs.io/en/stable/updating/) | Retains answers and source revision; updates Git projects by comparing template versions and reapplying project changes; exposes conflicts for review | Use for generation and upgrades. The project needs a lifecycle after its first scaffold. |
| [Cookiecutter replay](https://cookiecutter.readthedocs.io/en/stable/advanced/replay.html) | Saves template inputs for later generation | Useful for repeatable starts, but replay alone does not provide the selected template-update workflow. |
| [Nx](https://nx.dev/docs/features/enforce-module-boundaries) | Enforces dependency rules across projects through tags and import checks | Consider when a particular project grows into a multi-package workspace. Its project graph does not replace the independent-project template contract. |
| [Turborepo](https://turborepo.dev/docs) | Schedules and caches package tasks, including monorepo workflows | Consider when measured build duplication justifies it. A one-app starter does not need another task graph. |
| [Backstage catalog](https://backstage.io/docs/features/software-catalog/) | Collects software ownership and metadata from files stored with code | A possible later catalog for the third layer. It adds a separate system to operate and is not needed for a consistent local project start. |

Copier is a dependency with its own behavior to test, not an overwrite guarantee. Generate from a pinned, immutable template tag. Commit the generated project and Copier lineage file. Upgrade on a clean branch to an explicit release, review the diff, and resolve conflicts before accepting it. Never edit the answers file by hand or use recopy as an ordinary upgrade. These constraints follow [Copier's update guidance](https://copier.readthedocs.io/en/stable/updating/).

Ownership must also be encoded in the template. Domain source, project tests, and project-owned documentation are initial seeds. Exclude those paths when `_copier_operation == 'update'`. Copier documents this pattern for files that must never be rendered again during updates; `skip_if_exists` behaves differently when a file has been deleted. Contract tooling and schemas remain eligible for reviewed template updates. [Copier configuration](https://copier.readthedocs.io/en/stable/configuring/#exclude).

The template contains no Copier tasks, migrations, or custom Jinja extensions and needs no `--trust`. Installation is an explicit subsequent operation. This reduces hidden behavior during rendering; it is not a sandbox for dependency code.

## Turn conventions into checks

Both profiles expose `./project doctor|bootstrap|dev|check|test|build`. VS Code tasks and CI call that interface. The project owns the implementation; no editor or agent plugin is required.

- `doctor` reports readiness without installing or repairing anything.
- `bootstrap` is the explicit dependency installation step and may use the network.
- `dev` runs a cancellable server bound to loopback.
- `check` validates metadata, task records, unresolved merge artifacts, architecture boundaries, types/lint as applicable, and tests. Missing dependencies or tests fail; checks never silently install or modify tracked sources.
- `test` runs once and returns a failure status when tests fail.
- `build` creates local artifacts; it does not publish or deploy.

Use a committed npm lockfile and `npm ci` for the web profile; npm documents failure on manifest/lock mismatch and no rewriting of those files. [npm ci](https://docs.npmjs.com/cli/v11/commands/npm-ci/). For Python, bootstrap uses the checked uv lock with `--locked`; `--frozen` alone skips the freshness check. Ordinary `uv run` can lock and synchronize automatically, so validation must deliberately avoid that install path. [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/).

The task record is the durable handoff: goal, allowed paths, acceptance checks, base commit, actual results, unrun checks, blockers, and next action. Schema validation detects malformed records. It cannot prove that an agent's prose is true or prevent a process from accessing files; those require evidence review and execution controls.

## Keep agent context small and test its value

[`AGENTS.md`](https://agents.md/) is an open, predictable location for repository instructions supported by multiple coding tools. That makes it useful as an entry point; adoption alone does not prove a performance benefit.

The evidence does not justify making a large `AGENTS.md` the foundation's main mechanism. Gloaguen et al. found no statistically significant success-rate gain from either generated or developer context files in their tested Python issue-resolution settings, while inference cost and steps increased. Their scope does not establish that all context files are harmful, nor that shorter files are always better. [Evaluating AGENTS.md, version 3](https://arxiv.org/html/2602.11988v3).

Lulla et al. found lower runtime and output-token use in a separate paired study. They explicitly state that a full correctness evaluation was outside its scope. Faster completion is therefore not sufficient evidence of more reliable changes. [Impact on agent efficiency, version 2](https://arxiv.org/html/2601.20404v2).

Our inference: keep `AGENTS.md` as a short routing map to commands, architecture, ownership, and the current task. Put enforceable rules in checks. Add instructions only when a real failure shows they are useful. A later fresh-agent evaluation should score correctness, unnecessary changes, discovery work, and truthful handoffs on representative tasks; v0.1 smoke tests do not establish agent-efficiency gains.

Two vendor engineering case studies inform implementation details. OpenAI describes a short repository map, deeper versioned documentation, and mechanically enforced boundaries in [Harness engineering](https://openai.com/index/harness-engineering/). Anthropic describes task decomposition, explicit evaluation criteria, and structured handoffs across sessions in [Harness design for long-running application development](https://www.anthropic.com/research/harness-design-long-running-apps). These are reports from particular systems, not controlled evidence that this scaffold will produce the same outcomes. We adopt testable practices without importing their scale or performance claims.

VS Code's [session documentation](https://code.visualstudio.com/docs/agents/concepts/sessions) distinguishes conversations from execution environments and notes that conversation histories are not automatically shared. Our design therefore uses VS Code to guide and review work, while committed project records hold durable decisions and evidence. A session view is not our task ledger or an execution sandbox.

## Inspected tool versions

These exact versions are available from upstream and align with the local readiness inventory where noted. They are reproducibility choices for this implementation, not a claim to be the newest versions or a permanent support promise. Manifests and lockfiles are the executable source of truth; compatibility still needs the generation matrix.

| Tool | Version | Evidence |
| --- | --- | --- |
| Copier | `9.19.1` | [PyPI release](https://pypi.org/project/copier/9.19.1/), released 2026-10-13; requires Python 3.10+ and Git 2.27+ |
| Node.js | `24.11.1` | Pinned runtime; [official LTS release](https://nodejs.org/en/blog/release/v24.11.1/) |
| npm | `11.6.2` | Pinned runtime; [upstream release tag](https://github.com/npm/cli/releases/tag/v11.6.2) |
| uv | `0.11.8` | Pinned runtime; [upstream release tag](https://github.com/astral-sh/uv/releases/tag/0.11.8) |

Use project-local environments. Copier requires Python 3.10+; the generated project command supports Python 3.9+ while the service runtime remains pinned separately. macOS and Linux are the v1 target; native Windows remains unverified until tested.

## Future orchestration choices

| Option | Useful when | Additional work before adoption |
| --- | --- | --- |
| [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) | A specific workflow needs explicit state, resumable execution, and human intervention points | Define the workflow, persistence, provider adapters, tool permissions, budgets, and evaluation. Its runtime can be used without LangChain. |
| [Paperclip](https://github.com/paperclipai/paperclip) | A company workspace needs assignments, agents, org structure, run tracking, and budgets in one application | Review a pinned release's adapters, execution settings, credentials, approval behavior, and operating burden before any installation. Product-level governance does not prove isolation of an underlying agent process. |
| [CrewAI Flows](https://docs.crewai.com/en/concepts/production-architecture) | A workflow benefits from typed state, explicit control flow, and focused crews as individual units of work | Evaluate persistence and failure recovery on the actual workflow. Role descriptions alone do not supply the control flow. |
| [Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/overview/) | The application needs its agent, workflow, session, and provider integrations | Choose by required runtime and integrations, then test provider and tool behavior. |
| [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) | A Python application needs managed tool calls, handoffs, sessions, and tracing | Evaluate provider portability and runtime controls explicitly. An SDK's input/output guardrails do not replace operating-system isolation. |

The [AutoGen repository](https://github.com/microsoft/autogen) currently marks the project archived and directs new users to Microsoft Agent Framework. It is a historical reference rather than a new v0.1 dependency.

Paperclip illustrates why version-specific verification matters. The [raw v2026.1023.0 adapter source](https://raw.githubusercontent.com/paperclipai/paperclip/v2026.1023.0/packages/adapters/codex-local/src/index.ts) exports a bypass-default constant as `true`, while its embedded documentation describes a CLI default without bypass and managed credential-home mitigations. That inconsistency requires following the actual invocation path before adoption. Separately, [GHSA-gqqj-85qm-8qhf](https://github.com/paperclipai/paperclip/security/advisories/GHSA-gqqj-85qm-8qhf) reports inherited connector access for version `2026.403.0`. This does not establish that the latest release has that vulnerability. We install none of these runtimes and reuse no personal agent credentials in this foundation.

None is part of v0.1. The immediate abstraction is an ordinary repository with a stable command and handoff contract. The future orchestrator can consume those interfaces without becoming necessary to run the project.

Git worktrees can separate concurrent branches and working files, but Git documents shared repository configuration and administration. They do not create an operating-system boundary around credentials or network access. Any later agent sandbox requires separate runtime controls. [Git worktree documentation](https://git-scm.com/docs/git-worktree).

## Evidence needed before expanding

The foundation's acceptance matrix should generate two differently named projects per profile, run bootstrap/check/test/build and cancellable local-server smoke checks, inject failures, verify check leaves tracked content unchanged, and exercise an upgrade with both preserved edits and a deliberate conflict. Preserve exact commands, exit statuses, limitations, and unrun checks. A successful matrix supports the contract on the tested environment; it does not establish production readiness, arbitrary future upgrade safety, or superior autonomous-agent performance.

Add a Python research profile only after its data, notebook, experiment, and reproducibility requirements are concrete. Add a company catalog after several independent projects demonstrate which metadata and coordination are actually needed.
