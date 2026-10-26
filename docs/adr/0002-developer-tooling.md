# 0002 — Developer tooling

- **Status:** Accepted
- **Date:** 2026-10-26
- **Roadmap sub-stage:** 0.3

## Context

The V2 seed had tests but no linter, formatter, type checker, web tests or one-command workflow. Every later stage ports code, so quality checks must exist first. All tools must be open source and free (see [ADR 0001](0001-v3-goals-and-tooling-rule.md)).

## Decision

| Area | Tool | Pinned | Notes |
| --- | --- | --- | --- |
| Python lint and format | [ruff](https://docs.astral.sh/ruff/) | 0.17.2 (`uv.lock`) | Rules `E W F I UP B`; `E501` left to the formatter, line length 100 |
| Python types | [mypy](https://mypy.readthedocs.io/) | 2.4.0 (`uv.lock`) | Non-strict (`check_untyped_defs`), `app/` only; 25 baseline errors fixed with narrowing guards |
| Python tests | pytest + pytest-cov | 7.1.0 cov | Coverage is reported (63% at the seed), no threshold yet |
| Web lint | ESLint 10 + typescript-eslint + react-hooks | `package-lock.json` | 3 fast-refresh warnings left as warnings |
| Web tests | Vitest + Testing Library + jsdom | `package-lock.json` | Two starter test files; coverage grows with each stage |
| Hooks | [pre-commit](https://pre-commit.com/) | hook revs in `.pre-commit-config.yaml` | Whitespace, YAML and ruff; logos are excluded |
| Commands | [just](https://just.systems/) | any 1.x | `justfile`: `up`, `down`, `db`, `lint`, `fmt`, `test`, `build`, `seed`, `eval` |
| Environment | Dev Container | `.devcontainer/` | Python 3.12, Node 22, Docker; untested in CI |
| Images | Pinned tags | `docker-compose.yml` | pgvector `0.8.6-pg17`, Qdrant `v1.19.2`, Ollama `0.13.5` (the versions the seed was verified with) |

## Alternatives considered

- `black` + `flake8` + `isort`: three tools for what ruff does alone.
- `pyright`: a good option; mypy chosen first because most framework docs show it. Revisit if mypy slows.
- `make`: no Windows story and awkward quoting; `just` is a plain command runner.
- Strict mypy now: hundreds of errors in code that is about to be rewritten; tightening happens per stage.

## Consequences

- One command, `just lint && just test`, is the local definition of "green"; CI (0.4) runs the same recipes.
- Compose profiles (`obs`, `eval`) are not added yet: there are no services to put in them. They arrive with Langfuse (5.1) and the eval runner (5.2); core services stay un-profiled so `docker compose up` behaves as in V2.
- Pinned image tags will be bumped by Dependabot from 0.4.
