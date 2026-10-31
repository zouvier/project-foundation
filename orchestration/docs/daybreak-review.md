# Scoped model selection

`config/review-workflow.json` selects `gpt-5.6-sol` and requests Daybreak. The general review invocation plan includes that selection but remains non-executable while the production gate is closed.

The separate addition trial is pinned to the tested Codex CLI 0.166.0 interface. It requests `cyberAccessProgram: "daybreakBlue"` for each of its two turns, reusing existing authentication. Account availability is required; the configuration does not grant entitlement, create credentials or enroll an account. A different CLI version fails closed pending compatibility review.

The observed fixture trial completed with the requested model/program selection, independent conversation identities and zero observed tool calls. Its protocol provided no separate effective-program echo. Full private-read confinement and arbitrary-project execution remain unverified.

The trial checks effective per-process capability settings before inference. It does not rewrite user/global configuration, retry refusals, grant requested permissions or activate general workers. See [the trial guide](../trials/addition/LIVE.md) and [official app-server protocol documentation](https://learn.chatgpt.com/docs/app-server).
