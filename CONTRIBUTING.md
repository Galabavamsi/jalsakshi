# Contributing

## Workflow
- `main` is always deployable to the `demo` stage. Never push directly to it.
- Branch: `feat/<module>-<thing>`, `fix/<module>-<thing>`, `docs/<thing>`.
- Open a PR into `main`; the other person (or their Claude session) reviews. **Squash merge.**
- Keep PRs small and inside your own modules (see ownership in `CLAUDE.md`). If you must touch someone else's module, say so in `docs/HANDOVER.md` first.

## Commits
Conventional style, imperative mood: `feat(core): add reconciler rule r1`, `fix(voice): re-prompt on timeout`.

## Before you push
```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest -q
```
CI runs the same checks on every PR.

## Deploying
- Your own stage: `cd infra && uv run cdk deploy --all -c stage=dev-<you>`.
- `demo` stage: from `main` only, by whoever is recording. Announce it in `docs/HANDOVER.md`.

## Secrets
Never commit keys. Use `.env` locally (see `.env.example`) and SSM Parameter Store `/jalsakshi/<stage>/…` when deployed. If a key leaks, rotate it immediately.

## Working with Claude Code
Each person runs their own session in this repo. `CLAUDE.md` and `docs/` give every session the same context. Before starting, tell Claude which task from `docs/HANDOVER.md` you are taking, and have it update the status when done.
