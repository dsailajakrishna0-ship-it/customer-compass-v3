# 0003 — CI and supply-chain checks

- **Status:** Accepted
- **Date:** 2026-10-26
- **Roadmap sub-stage:** 0.4

## Context

`main` is protected but had no automated checks. From Stage 1 on, every change must show it did not break the seed's behaviour. The checks must be free for a public repo and use open-source tools (see [ADR 0001](0001-v3-goals-and-tooling-rule.md)).

## What CI/CD is, and which platform

CI (continuous integration) runs the same checks on every change automatically, so a broken change is caught before it reaches `main`. CD (continuous delivery) turns a tagged version into publishable artifacts, here container images and a release (sub-stage 0.5). Both are described as code in the repository.

**Platform chosen: GitHub Actions** on GitHub-hosted runners. The repo is public, so minutes are free; there is no server to run; and it integrates with branch protection, required checks, Dependabot, GHCR and Releases.

| Platform | Why not here |
| --- | --- |
| Jenkins | Open source and very flexible, but you host, patch and secure the server and plugins yourself. Too much operations work for a learning project. |
| CircleCI | Good hosted CI that works across Git providers; free tier is limited and needs a separate account and token. Worth a separate comparison later, not as the gate. |
| GitLab CI | Excellent, but built into GitLab; the code lives on GitHub. |
| Azure Pipelines, Bitbucket Pipelines, Buildkite | Tied to other ecosystems, or need self-hosted agents. |

The ideas (pipeline, job, runner, cache, secret, required check) are the same everywhere; only the configuration syntax differs.

## Decision

One workflow, `.github/workflows/ci.yml`, with five jobs that run on every pull request and on pushes to `main`:

| Job | Runs | Tool |
| --- | --- | --- |
| `api` | ruff, ruff format, mypy, `just test-api` (Postgres through Compose) | uv, just |
| `web` | ESLint, `tsc`, Vitest, production build | Node 22 |
| `docs` | relative links and anchors in all `*.md` (offline, so external sites cannot flake the gate) | lychee |
| `smoke` | `docker compose up --build --wait` for db, qdrant, ollama, api, then `GET /health` | Docker Compose |
| `security` | secret scan of full history; `pip-audit`; `npm audit` (high and up); Trivy on repo files and Dockerfile; Trivy on the built API image (unfixed findings ignored) | gitleaks, pip-audit, Trivy |

- Every third-party action is pinned to a commit SHA with its version in a comment. Dependabot (`.github/dependabot.yml`) bumps actions, Python, npm and Docker weekly, grouped to keep PR count low.
- Workflow permissions are read-only (`contents: read`).
- `.github/CODEOWNERS`, issue templates and the PR template are added; the owner is the only reviewer.
- After this PR merges, the five job names become required status checks on `main`.

## Alternatives considered

- Renovate: more configurable, but needs an extra app install; Dependabot is built in.
- CodeQL: useful later for the Python and TypeScript code; deferred so Stage 0 stays small.
- Checking external links in CI: rejected, third-party outages would block unrelated PRs.

## Consequences

- The first run found and fixed real issues: `certifi` (critical), `vite` and `source-map-js` (high), and the API container running as root. The container now runs as an unprivileged user and starts uvicorn from the virtualenv instead of `uv run`.
- `api-py` has a Compose healthcheck, so `--wait` and the smoke test wait for a ready API.
- The smoke test does not call a model, so it needs no API keys.
- Free GitHub Actions minutes are generous for public repos; if the repo goes private they are capped (see the roadmap risks).
