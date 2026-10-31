# Verification scope

The imported prototype previously passed 169 offline tests. These exercise strict worker schemas, source boundaries, safe Git inspection, exact-artifact checks, independent review, cancellation, restart behavior, bounded subprocess transport, duplicate/conflicting improvement evidence and CLI/trial failure paths. Mock worker success is not live model evidence.

The public closeout snapshot passed all 169 tests again on macOS arm64, including a run on Python 3.13.5 matching the CI configuration (52.588 seconds, no failures or skips). This verification made zero live model requests.

The full foundation suite passed 340 tests in 406.87 seconds, with no skips. Its two new combined-layout cases cover both generated profiles, manual catalog registration, task assignment/tracking, an independent simulated reviewer, genuine fixed-byte check receipts and exact-artifact acceptance. They exercise no model and execute no generated application code. Other foundation cases separately run the real project command and upgrade matrix.

Run this component's complete offline suite from `orchestration/`:

```sh
python3 -B -m unittest discover -s tests -v
```

Run the foundation and combined-layout suite from the repository root using the command in [foundation verification](../../docs/verification.md). It requires the pinned development tools. Its opt-in integration tests install dependencies in disposable projects and briefly start loopback servers. The combined-layout cases themselves make no network or model requests and execute no generated application code.

## Historical live fixture evidence

One previously authorized fixed addition trial completed with Codex CLI 0.166.0 and model `gpt-5.6-sol`. Both turns explicitly requested Daybreak Blue; the protocol did not provide a separate effective-program echo. There was one builder conversation and a separately invoked reviewer, two completed model turns, zero observed tool calls, and no overseer turn.

The coordinator observed eight expected failing baseline cases among ten tests, then ten passing candidate cases. The reviewer approved the exact artifact. Total recorded duration was 11.542 seconds: builder 8.375 seconds and reviewer 2.330 seconds. These single-run measurements are not performance or cost estimates.

The reviewed artifact manifest hash was `f4ae899f7a46f2b1803f2f685c9532d70f27c6847275d0e72a8c6753cffda9f0`. The candidate was the fixed function `def add(a, b): return a + b`. The trial stopped at `awaiting_acceptance`; it did not merge changes or record human acceptance. Source remained unchanged. No new live calls are made for this publication.

Raw model transcripts, account/session IDs, local paths, logs, credentials and private Git history are excluded. This summary preserves only the fixture's minimal historical evidence. The live harness is retained for inspection and requires fresh explicit scope for any future execution.

## Limits

Production workers stay disabled. Standard read-only mode does not establish private-read isolation. An argv allowlist, process group and worktree do not contain arbitrary project code. Before/after hashes cannot prevent a hostile checker from changing and restoring inputs. No billing-enforced dollar cap, general project runner, automatic foundation release, or Orca integration is claimed. See the [handoff](integration-plan.md).
