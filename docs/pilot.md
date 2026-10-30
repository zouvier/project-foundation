# Fresh-agent evaluation design

For further evaluation, create fresh projects from the chosen released template. Give a new agent only the generated repository instructions and one concrete task, without the implementation conversation. Do not use the foundation itself as the pilot application.

One small feature exercise: change the greeting domain to return a distinct message for a whitespace-only name, add regression coverage, and expose the existing behavior through the UI/API without changing architecture. The user specifies the expected text before the run. Record the task's base commit, allowed paths, checks and results. Independently verify behavior with checks the agent did not author.

Run separate exercises for a regression repair and an interrupted handoff. In the handoff, stop after a documented partial implementation, then give another fresh agent only the repository and its task record. Confirm it resumes the actual state. Seed one false-completion record with unrun checks and confirm the contract rejects it.

For a later comparative study, hold task/model/budget fixed across: A) ordinary README, B) shared commands without AGENTS.md, C) shared commands plus lean AGENTS.md. Keep task variants independent and score functional correctness separately from time, retries, context retrieval and tokens. Only report costs/tokens if captured by reliable telemetry; deterministic fixture tests are not an agent-performance benchmark. No model API spend or run is part of this setup.

Private pilot projects and their raw evidence are not published here. This design is not a performance or cost claim.
