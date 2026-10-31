# Orchestration component map

- This experimental component is retained for reference. Custom runtime development is closed; future coordination is intended to use Orca, which is not installed or validated here.
- Keep it outside the foundation's generated `template/` subtree; projects retain their own source and state. Do not expand or activate the runtime as part of routine foundation maintenance.
- Read `README.md`, `docs/decisions.md` and `docs/verification.md` before changing the execution boundary.
- `agent_company/contracts.py` owns strict schemas/path checks; `engine.py` owns transitions, checkpoints and evidence; `codex.py` owns the live gate.
- Run `python3 -m unittest discover -s tests -v`. No network, installation or model call is required.
- Workers never receive this repository or its durable database as writable roots. Review and oversight are independent invocations.
- A task review is not permission to merge, deploy, send a message or adopt a foundation release. Keep all such actions outside v0.1.
- Keep the live gate closed unless a real per-invocation capability and sandbox probe passes. Never weaken it to make a smoke test pass.
