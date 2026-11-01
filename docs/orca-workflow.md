# Bounded Codex maintenance in Orca

Use Orca to organize one small change to this scaffold, with one Codex builder and a separately launched Codex reviewer. This is a source-repository maintenance procedure, not a validated universal setup, an automated release system, or production worker containment. Machine-specific launch success does not establish compatibility elsewhere. The [custom coordinator closeout](../orchestration/docs/integration-plan.md) remains closed; do not revive it, add a dashboard, or run live prototype trials.

## Agree on the boundary

Before launching, record the source repository, absolute checkout path, branch, base commit, allowed files, concrete change, exclusions, and acceptance commands. Read the root `AGENTS.md` and any applicable nested guidance. Set a finite task and stop condition: one improvement, checks, review, then human acceptance. If scope or permissions need expansion, stop and return that decision to the human.

Create an isolated Orca worktree/branch for the builder and verify `pwd`, `git rev-parse --show-toplevel`, `git branch --show-current`, `git rev-parse HEAD`, and `git status --short`. Worktrees isolate working files and branch state; they share Git storage and do not isolate credentials, host files, processes, or network access. `AGENTS.md` and role prompts guide agents; they do not enforce access controls.

Choosing **Full access** for the builder is an explicit operator decision for trusted work on that machine. It is not a worktree sandbox or permission to change unrelated repositories, credentials, global settings, or external services. Confirm the effective launch settings rather than inferring them from the task text. Do not enable hooks or grant repository/hook trust as a side effect of this procedure: those are separate, inspected opt-in decisions. No hooks are required. A requested Daybreak selection is not proof of effective activation; Daybreak behavior in this Orca workflow remains unverified.

## Build and identify the artifact

Give the builder only the bounded task. Leave changes uncommitted unless a local commit was explicitly requested; do not push, merge, deploy, publish a tag, or send external messages. The completion packet must identify:

- Absolute changed-checkout path, branch, full base commit and current HEAD.
- Exact tracked diff against the agreed base, including staged changes, and the paths and bytes of all untracked deliverables. `git diff BASE --` does not include untracked files; list them with `git ls-files --others --exclude-standard` and include them explicitly.
- A stable artifact identity: a requested local commit with a clean tree, or a saved patch plus an untracked-file manifest and SHA-256 hashes of their bytes. Record the patch hash too. Save evidence outside the reviewed file set and state where it lives. A branch name or HEAD alone cannot identify dirty changes.
- Every actual check's command, absolute working directory, interpreter/environment used, exit status, output/log location, and skipped or unrun checks. Capture status and artifact identity before and after checks; any input change requires fresh evidence and review.

Run checks against the actual changed checkout. An existing source checkout's Python environment can supply dependencies, but invoke tests by paths in the changed checkout and record both paths. A green run in another checkout does not validate this diff. For docs-only work, inspect relative links and run `git diff --check`; choose existing lightweight tests appropriate to the change. Do not install dependencies implicitly or describe skipped integration cases as acceptance.

For template changes, follow the [foundation maintenance instructions](../README.md#maintaining-the-foundation): change shared conventions under `template/`, generate independent disposable repositories, exercise the real project commands, and test updates with edits, deletions and conflicts. Record actual fixture revisions and results. Deterministic smoke tests establish behavior, not agent productivity.

## Launch an independent read-only review

Stop builder edits while review is in progress. Open a fresh Orca terminal for a new Codex invocation, pointed at the exact artifact checkout; do not resume the builder conversation or assume a reviewer role label changes its permissions. Explicitly launch read-only rather than inheriting the builder's Full access setting:

```sh
codex --cd /absolute/path/to/changed-checkout \
  --sandbox read-only --ask-for-approval never
```

Verify the installed CLI supports these options and the session reports the intended effective settings. If Orca's launch path cannot express or confirm them, use its terminal with the explicit CLI invocation or stop; do not silently substitute a Full access reviewer. These flags follow the [official Codex approvals and security guidance](https://learn.chatgpt.com/docs/agent-approvals-security). They select shell sandbox policy and reject escalation requests; they do not prove private-read isolation or containment of every connected tool. Inspect available tools and effective policy before treating the review as read-only.

Provide the reviewer the task, base, artifact identity, exact diff and untracked files, and test evidence. Ask it to independently inspect the actual bytes, check scope and links/contracts, and return findings with file references, missing evidence, and an explicit recommendation tied to that artifact. It must not edit files, fix findings, install packages, run mutating tests, or perform external writes. Tests that write caches or fixtures belong to the builder's recorded check run. If more execution is needed, return it to the builder; any revision gets a new artifact identity, appropriate checks and fresh review.

### Reporting when the sandbox blocks delivery

Effective sandbox policy, assigned review scope, successful report delivery and human acceptance are separate facts. If an inbox or reporting command fails with `runtime_access_denied`/EPERM, preserve that failure as blocked delivery; it does not invalidate completed inspection or prove that findings reached the coordinator. Prefer a final report in the read-only reviewer's permitted terminal, captured by the authorized coordinator with explicit reviewer attribution, findings, limitations and exact patch/file hashes. If capture is unavailable, leave delivery blocked. Follow the [generated reviewer role](../template/.project/roles/reviewer.md) without expanding its permissions.

For an ordinary terminal review without an active Dispatch, the authorized coordinator can record the captured evidence and manually complete its review tracking task using the installed `orca orchestration task-update --help` contract, retaining the report location and artifact identity in the result. Label this coordinator-captured evidence, not reviewer `worker_done` or successful sandboxed reporting. Never forge lifecycle messages for a reviewer; a real dispatched worker follows its own live preamble, and an accepted `worker_done` already settles its task.

The [accepted M1 evidence](evidence/2026-11-01-m1-acceptance.json) records this capture path and distinguishes the earlier EPERM attempt from one specifically approved unsandboxed retry that successfully reported and ended. That exception is over: it is neither standing approval nor a default reporting path. The `--ask-for-approval never` launch above cannot authorize escalation; any broader retry requires fresh explicit human approval. Do not repair the runtime or change persistent reviewer settings to obtain delivery.

### Readiness and uncertain turn starts

A ready terminal or accepted input is not proof that the agent consumed the task, started a turn, completed review or delivered findings. A missing turn-start receipt is uncertain, not proof of a dead process. Inspect bounded terminal output and the relevant transcript around the submission before considering replay; do not blindly duplicate the prompt or infer exit from silence.

Check `orca skills get orchestration`, `orca terminal send --help` and `orca orchestration send --help` against the installed version before relying on their receipts. Current terminal-send help distinguishes input acceptance, observed submission and turn start: `--wait-submit` observes an accepted prompt without resending, while an ambiguous transport failure may return a `--retry-request` ID for the exact command and terminal process incarnation. Use only the supported recovery contract and returned ID; older hosts may lack these capabilities. These receipts establish neither effective sandbox policy nor review or reporting success.

## Human acceptance and independent projects

A reviewer recommendation is evidence, not acceptance. The human explicitly accepts or rejects the named artifact after seeing findings and actual check results, including limitations. Record that decision against the exact commit or patch/manifest hashes. Silence, worker completion, and a passing test do not count. Human acceptance of the change still grants no implicit push, merge, deployment, release or adoption authority.

Generated applications remain separate Git repositories with their own source, decisions and task records. This workflow adds nothing to the generated subtree. Preserve existing release tags, Copier source locations, `.copier-answers.yml` pins and provenance receipts; never silently upgrade another project. A new foundation release and each project's adoption are separate reviewed decisions using a pinned immutable release. No credentials, personal agent configuration, hooks, or Orca runtime state should be copied into the scaffold.
