# Foundation improvement proposals

This source-only ledger records bounded proposals for later foundation work. An independent overseer inspects an identified artifact and returns findings through a permitted channel; an authorized coordinator records the attributed proposal. Recording a proposal does not accept it or authorize implementation. Each entry needs evidence, uncertainty, a smallest change, alternatives, dependencies, owner, acceptance checks, compatibility risks and a human disposition: proposed, accepted, deferred or rejected. Attribute later decisions to a specific human instruction and artifact. No template edits, project upgrades or automatic promotion follow from this ledger.

## P2-001: Link historical verification status to its accepted disposition

**Disposition:** proposed, not accepted or implemented. Recorded 2026-11-01 UTC by the coordinator from a distinct independent Codex overseer. P2 task: `task_7ecda025c24e`; effective mode was verified as Read Only (Ask for approval). The overseer returned a final terminal report for coordinator capture, made no source or task-record edits, ran no tests, and requested no permission expansion.

**Observed gap:** the M1 section of [the verification record](verification.md) still states that fresh independent review and the human decision remain pending. That sentence correctly records the builder's historical handoff, but this entry point does not link to the later [M1 acceptance record](evidence/2026-11-01-m1-acceptance.json). A reader can miss its subsequent disposition. P1 already documents reporting fallback and readiness; this proposal concerns evidence navigation only.

**Artifact and dated evidence:** inspected base/HEAD `3b229eaa7db962129672627e94b83377622ecfba`, with uncommitted deliverables. The 2026-11-01 UTC acceptance record identifies the exact earlier six-file artifact and tracked-patch SHA-256 `820189203d3613386e92314ac42348a58640c19ef18e613b5040c7a2476a750d`. At inspection, all five non-workflow M1 files still matched their accepted hashes. P1 intentionally changed the workflow guide after acceptance.

| Directly inspected source | SHA-256 at proposal time |
| --- | --- |
| `docs/verification.md` | `b2a9faa72347697e3b5b8d307e074172fb243abe626cc604798e580fd1fc6ae3` |
| `docs/evidence/2026-11-01-m1-acceptance.json` | `cdd5b65f41afd978e33e52519a3049b8fb605763d9fa2044a249d5e92487a890` |
| `docs/orca-workflow.md` after P1 | `507197ad2c7e31b009c4f43056ca6bb5aa274c9721ddfc694ff1186fe5ad59e1` |

The verification record's dated M1 account reports 22 schema tests and 340 full-suite tests. The overseer inspected that evidence; it did not reproduce those executions. The acceptance record preserves summarized observations and explicitly does not attest or embed raw machine-local logs.

**Uncertainty and limits:** the historical pending statement is not false for its recorded time and must remain intact. The overseer did not reconstruct the old patch, inspect private transcripts, establish new P1 full-suite results, or demonstrate a schema defect. This observation supports a small documentation change, not a productivity or containment claim.

**Smallest future change:** in a separately authorized task, add one dated status paragraph immediately below the M1 heading in `docs/verification.md`. Link the sanitized acceptance JSON, state that its exact M1 artifact was subsequently accepted, and label the following builder account as historical. State that later revisions require their own identity and review. Preserve all historical text and the acceptance JSON unchanged. This change has not been applied here.

**Alternatives:** leaving resolution discoverable only through the workflow guide preserves the confusing entry point. Rewriting pending as accepted obscures chronology. Adding structured status/schema machinery is unnecessary for this demonstrated gap; P3 remains blocked.

**Dependencies and owner:** separate human disposition of this proposal and an explicitly bounded documentation task. The future owner is an authorized foundation documentation builder, followed by a separate independent read-only reviewer and human acceptance. Existing sanitized evidence suffices; no installation, runtime repair or schema design is needed.

**Future acceptance checks**, from the changed checkout:

```sh
git diff --check
git diff -- docs/verification.md
shasum -a 256 docs/verification.md docs/evidence/2026-11-01-m1-acceptance.json
```

Verify that the relative acceptance link resolves, the addition distinguishes historical pending status from subsequent acceptance, existing historical text is intact, and the acceptance JSON retains its recorded hash. Freeze the new verification-document hash for independent review. These prose checks do not imply a new full-suite run.

**Compatibility and release:** source documentation only. No template, role, schema, preflight, release tag or generated-project change. Updating the verification document creates a new artifact hash; the acceptance record must continue to identify its historical M1 bytes. Keep private raw logs and personal paths outside portable evidence. Publication and releases remain separate decisions.
