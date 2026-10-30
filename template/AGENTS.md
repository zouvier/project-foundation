# Project map

1. Read `README.md` for setup and the command contract; read `docs/architecture.md` before changing dependencies between layers.
2. Use a task record in `.project/tasks/` for goal, allowed paths, base commit, acceptance checks, evidence and handoff. Keep project context here; do not copy unrelated project memory.
3. Run `./project doctor`; install dependencies only with the explicit `./project bootstrap` step. Use `./project check` and `./project build` for acceptance. Record failures and unrun checks as they are.
4. `.project/roles/` contains optional coordinator, builder, reviewer and researcher prompts. The task owns scope; role names do not grant permissions.
5. For template updates read `docs/upgrading.md`. Never edit `.copier-answers.yml` manually. Never mark an unresolved conflict or unrun check as passed.

These instructions coordinate work; executable checks enforce the supported contract. They do not isolate secrets, network access or actions.
