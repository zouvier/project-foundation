# Agent orchestration prototype

An experimental local coordinator for Codex workers, task checkpoints, independent reviews and an improvement ledger, preserved under `orchestration/` in the [project-foundation repository](https://github.com/zouvier/project-foundation). Generated applications remain independent repositories.

**Closed prototype:** custom runtime development has stopped. Future coordination is intended to use [Orca](https://github.com/stablyai/orca); it has not been installed, configured or validated here. The offline workflow is tested, and one previously authorized fixed addition trial completed with a real builder and independent reviewer. General production workers remain disabled. Automatic generation/registration of foundation projects is unfinished. See [the handoff](docs/integration-plan.md) and [verification scope](docs/verification.md).

There is no daemon, scheduler, hosted orchestration service, dashboard, automatic deployment or new credential store. Use a source checkout; package installation is not a verified distribution workflow.

## Try the offline workflow

From this component's directory, with Python 3.9 or later and Git:

```sh
python3 -B -m unittest discover -s tests -v
./company --state .artifacts/demo-001 demo
./company --state .artifacts/demo-001/state status
./company --state .artifacts/demo-001/state improvements
```

Choose a fresh output directory. The demo uses fixed simulated workers and explicitly simulated human gates. It makes no model request. The [functional rehearsal](trials/addition/README.md) also runs the known arithmetic tests and stops before acceptance.

## Run the explicit fixed live trial

With the already configured Codex CLI **0.166.0**, existing authentication and authorized access to GPT-5.6 Sol/Daybreak Blue:

```sh
./company trial-addition --output .artifacts/addition-001 --allow-standard-read-only
```

This is a real two-turn request. The flag acknowledges that standard read-only mode can allow broader local reads, potentially exposing personal data to the model service. Scope is this trial only. The command uses per-invocation restrictions, refuses unexpected tool/approval actions and stops for **human acceptance** after successful checks/review. It never enables the general production adapter. If an outer execution environment requires approval, use its supported approval process; the command does not escalate itself.

The builder returns structured edit data; the coordinator applies the edit and runs a constant trusted checker. Only the exact addition/subtraction function AST can execute. The reviewer receives the exact artifact and actual check receipts in a separate conversation. This checker is not a sandbox for arbitrary project code. See [the complete trial guide](trials/addition/LIVE.md).

## Task lifecycle

```text
human task → approve task digest → builder → checks → independent reviewer
           → accept exact artifact → completed

failure → recorded failure + bounded oversight proposal
uncertain interruption → inspect; never replay automatically
cancel → prevent further work
```

`init`, `create`, `approve`, `run`, `review`, `accept`, `resume`, `status`, `improvements` and `cancel` manage local records. `schema`, `review-plan`, `doctor`, `demo` and `trial-addition` expose contracts and diagnostics. Commands return JSON; the trial also prints stage progress on stderr.

The [catalog](examples/catalog.json) and [task](examples/task.json) examples show bounded project paths, explicit check argv and exact revisions. The catalog declares the public `v0.1.2` commit. It does **not** verify generated-project provenance or create a foundation project. New catalogs can name independently generated repositories; `init` records the catalog and `create` records a task at an exact clean Git revision. General `run`/`review` stop at the closed live gate. `doctor` reports that gate and is not a way to enable it.

The private prototype used a different audit commit. This public source snapshot imports no private history or durable state. Keep existing private workspaces with their original checkout; no automatic state or pin migration is supplied.

Checks must actually pass, the reviewer must be independent, and artifact hashes must remain consistent. A review is not permission to merge, send, publish, deploy or adopt a foundation release. Acceptance records a local decision and leaves the source repository unchanged.

## Limits and improvement governance

The coordinator permits one active worker, one builder and reviewer attempt per task, and no repair loop. Inputs are bounded to 100 files/1 MiB; proposed edits are bounded to 20 files. The fixed live trial makes at most two model-turn requests, uses a 100-second role deadline and 240-second transport deadline, and captures at most 2 MiB of combined output. Existing output directories are never replayed or overwritten automatically.

SQLite records approvals, attempts, hashes, checks and events. After a finished or failed run, an overseer can propose improvements supported by that task's evidence. Conflicting issue descriptions cannot silently share evidence. The fixed live trial defers oversight to stay within its two-turn scope; the general overseer path remains subject to the closed production gate.

Proposals cannot alter policy, budgets, active templates or project pins. Foundation changes need a separate reviewed candidate, regression evidence and human acceptance. Existing projects do not silently upgrade. There is no perpetual polling or automatic background improvement service.

## Boundaries

Standard read-only is not private-read confinement. Disabled capability settings and zero observed tool calls in one trial do not prove a general sandbox. Git process/transport controls do not cap native Git memory or contain deliberately detached children. A worktree and an argv allowlist are not security boundaries.

The local owner and reviewed coordinator are trusted. Project source and worker text are data. No arbitrary-project production check runner is provided; before/after hashes alone cannot prevent a hostile process changing and restoring a check input. Credential-pattern rejection and redaction cannot find every secret, so do not register secret-bearing or personal-data repositories.

Observed token counts are retained when available. Dollar costs and billing-enforced caps are not claimed. This component is editor-neutral; no IDE installation or global configuration change is required. No license has been selected or declared.
