# Contributing

This is a personal learning repo, but changes follow a small, strict flow so history stays readable.

1. Work is planned in [`docs/roadmap.md`](docs/roadmap.md). Each sub-stage (for example `0.1`) is one pull request.
2. Branch from `main`: `chore/0.1-short-name`, `feat/3.2-langgraph-nodes`, `docs/0.2-readme`.
3. Open a pull request. `main` is protected: no direct pushes, squash merge only, linear history.
4. Keep PRs small and focused, with the sub-stage number in the title and its exit criteria in the description.
5. Record tool choices as short decision records in `docs/adr/`.
6. Before pushing, run `just lint && just test` (see the [README](README.md#developer-commands)); `pre-commit install` runs the quick checks on each commit. CI runs the same checks plus link, secret and vulnerability scans ([ADR 0003](docs/adr/0003-ci-and-supply-chain-checks.md)); a PR merges only when they are green.
7. Never commit secrets or real personal data. Use synthetic data only.

Use the `dsailajakrishna0-ship-it` identity for commits and `gh` in this repo.
