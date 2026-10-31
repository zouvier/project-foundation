# Explicit two-turn live trial

From this component's root, choose a fresh output directory:

```sh
./company trial-addition --output .artifacts/addition-001 --allow-standard-read-only
```

This requests one real GPT-5.6 Sol builder and one independent reviewer with Daybreak Blue selected, using the existing Codex login. It requires the tested CLI 0.166.0 and authorized account access. The explicit flag acknowledges standard read-only scope for this trial: broader local reads, and disclosure to the model service, remain possible. It grants no standing worker permission. Use any required outer approval process; never bypass a denial.

The coordinator demonstrates the starter's known defect, requests a closed JSON edit, applies the permitted change and invokes a constant trusted checker. Only the exact arithmetic function AST can execute. The reviewer receives the exact artifact and genuine check receipts in a new ephemeral conversation. Success stops at `awaiting_acceptance`; acceptance is a separate human decision.

Progress is emitted on stderr and the final JSON on stdout. Local outputs include `report.json`, `status.json`, role receipts, effective controls and transport metadata. They may contain machine-specific details and are intentionally ignored by Git. Do not publish them without separate review and scrubbing.

Limits: two model-turn requests, independent thread IDs, 100 seconds per role, 240 seconds for the transport, 2 MiB combined output, no automatic retry and no automatic acceptance. An existing output path refuses replay. Inspect a stopped or uncertain attempt before authorizing another run. Oversight is deferred; no third model turn is made.

Per-invocation configuration disables inherited MCP/plugin/app entries and known execution/search capabilities. Environment access is deselected. A tool or server approval request stops execution without granting permission. These measures are not proof of complete private-read containment. The production adapter remains closed, and the fixed checker is not a general project sandbox.

A prior authorized trial completed two actual turns and ten candidate tests in 11.542 seconds. This is evidence for the fixed fixture only. The [scrubbed verification record](../../docs/verification.md) omits private machine paths, account/session identifiers, raw logs and transcripts.
