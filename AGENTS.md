# Foundation maintenance map

- `copier.yml` chooses one profile and defines update ownership; `template/` is the only generated subtree.
- `README.md` documents generation and the explicit integration command. `docs/research.md` explains design choices; `docs/verification.md` records actual evidence.
- Change shared conventions in the template, then generate independent fixtures and verify them. Do not change another project or a user's global editor/agent settings.
- Keep source seeds separate from template-managed infrastructure. Test an update with edits, deletions and a conflict before releasing a tag.
- Do not assert agent productivity improvements from these deterministic smoke tests. No model API calls are needed for maintenance.
- `orchestration/` preserves the closed experimental Codex coordinator alongside the template. Read its `AGENTS.md` for its boundaries. Run its offline suite from that directory with `python3 -B -m unittest discover -s tests -v`; never run live trials as part of maintenance or CI.
- Future coordination is intended to use Orca; setup and validation are a separate task. Preserve the existing template path, release tags and generated-project independence.
