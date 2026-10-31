"""Editor-neutral entry point. The only production worker adapter is Codex."""
import argparse
import json
from pathlib import Path
import sys

from .codex import CodexAdapter, WorkerBlocked
from .contracts import PolicyError, schema_for
from .engine import Company


def read_json(path):
    file = Path(path)
    if file.is_symlink() or not file.is_file() or file.stat().st_size > 1024 * 1024:
        raise PolicyError("JSON input must be a regular file no larger than 1 MiB")
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise PolicyError("duplicate JSON field")
                result[key] = value
            return result
        return json.loads(file.read_text(), object_pairs_hook=unique)
    except PolicyError:
        raise
    except (ValueError, UnicodeError):
        raise PolicyError("invalid JSON input") from None


def project_adapter():
    options = read_json(Path(__file__).resolve().parents[1] / "config" / "review-workflow.json")
    return CodexAdapter(review_options=options)


def parser():
    command = argparse.ArgumentParser(description="Local bounded Codex task and improvement ledger")
    command.add_argument("--state", default=".company", help="local durable state directory")
    sub = command.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create a project catalog, without changing projects")
    init.add_argument("catalog")
    create = sub.add_parser("create", help="snapshot and plan a bounded task")
    create.add_argument("task")
    approve = sub.add_parser("approve", help="human approval of the exact task digest")
    approve.add_argument("id")
    approve.add_argument("--digest", required=True)
    for name in ("run", "review", "resume", "cancel"):
        child = sub.add_parser(name)
        child.add_argument("id")
    accept = sub.add_parser("accept", help="human acceptance of the exact reviewed artifact; does not merge it")
    accept.add_argument("id")
    accept.add_argument("--artifact", required=True)
    status = sub.add_parser("status")
    status.add_argument("id", nargs="?")
    improvement = sub.add_parser("improvements")
    improvement.add_argument("--process-pending", action="store_true", help="one bounded oversight pass; no polling")
    sub.add_parser("doctor", help="inspect CLI/auth presence and isolation gate; makes no model request")
    review_plan = sub.add_parser("review-plan", help="print configured review arguments; never launches a worker")
    review_plan.add_argument("--workspace", required=True, type=Path)
    review_plan.add_argument("--schema", type=Path)
    schema = sub.add_parser("schema")
    schema.add_argument("role", choices=("builder", "reviewer", "overseer"))
    sub.add_parser("demo", help="run a synthetic offline demonstration; no live Codex calls")
    trial = sub.add_parser("trial-addition", help="run exactly one real builder and independent reviewer on the fixed addition fixture")
    trial.add_argument("--output", required=True, type=Path, help="fresh receipt/artifact directory; never overwritten or replayed")
    trial.add_argument("--allow-standard-read-only", action="store_true",
                       help="acknowledge broader local reads are possible in standard Codex read-only for this trial only")
    return command


def main(argv=None):
    args = parser().parse_args(argv)
    company = None
    try:
        if args.command == "schema":
            result = schema_for(args.role)
        elif args.command == "doctor":
            result = CodexAdapter().preflight()
        elif args.command == "review-plan":
            result = project_adapter().invocation_plan("reviewer", args.workspace, args.schema)
        elif args.command == "demo":
            from .demo import run_demo
            result = run_demo(Path(args.state).absolute())
        elif args.command == "trial-addition":
            from .trial import run_addition_trial
            def progress(stage, message):
                print(json.dumps({"stage": stage, "message": message}), file=sys.stderr, flush=True)
            result = run_addition_trial(args.output, allow_standard_read_only=args.allow_standard_read_only, progress=progress)
        else:
            company = Company(args.state, project_adapter())
            if args.command == "init":
                result = company.initialize(read_json(args.catalog))
            elif args.command == "create":
                result = company.create(read_json(args.task))
            elif args.command == "approve":
                result = company.approve(args.id, args.digest)
            elif args.command == "accept":
                result = company.accept(args.id, args.artifact)
            elif args.command == "improvements":
                result = company.improvements(args.process_pending)
            else:
                result = getattr(company, args.command)(args.id)
        print(json.dumps(result, indent=2, sort_keys=True))
        if isinstance(result, dict) and result.get("state") in {"blocked", "failed", "interrupted", "stopped"}:
            return 2
        return 0
    except WorkerBlocked as exc:
        print(json.dumps({"status": "blocked", "reason": exc.reason, "evidence": exc.evidence}, indent=2))
        return 2
    except (PolicyError, OSError) as exc:
        from .engine import redact
        print(json.dumps({"status": "error", "reason": redact(exc)}, indent=2))
        return 2
    finally:
        if company is not None:
            company.close()


if __name__ == "__main__":
    raise SystemExit(main())
