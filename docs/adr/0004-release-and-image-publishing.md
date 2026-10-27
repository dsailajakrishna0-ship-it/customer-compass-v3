# 0004 — Release and image publishing

- **Status:** Accepted
- **Date:** 2026-10-26
- **Roadmap sub-stage:** 0.5

## Context

V3 needs a repeatable way to turn a commit into runnable artifacts, without paid services or manual steps. CI runs on GitHub Actions ([ADR 0003](0003-ci-and-supply-chain-checks.md)); delivery uses the same platform.

## Decision

`.github/workflows/release.yml` runs when a tag matching `v*` is pushed:

1. Check the tagged commit is on `main`.
2. Build the API and web images, scan each with Trivy (HIGH and CRITICAL fixed findings fail the release), then push to **GitHub Container Registry**: `ghcr.io/dsailajakrishna0-ship-it/customer-compass-v3-api` and `-web`.
3. Tags: the exact version (`3.0.0-alpha.1`); stable tags (no `-` in the version) also get `major.minor` and `latest`.
4. Create a **GitHub Release** with notes generated from the merged pull requests; versions with a `-` are marked pre-release.

Versions follow [semantic versioning](https://semver.org/). Releases are cut by pushing a tag by hand, after CI is green on `main`:

```bash
git checkout main && git pull
git tag v3.0.0-alpha.1 && git push origin v3.0.0-alpha.1
```

The web image is new in this sub-stage: `apps/web/Dockerfile` builds the app and serves it with unprivileged nginx on port 8080 (single-page-app fallback). The workflow uses only the built-in `GITHUB_TOKEN`; no extra secrets.

## Alternatives considered

- **Docker Hub:** needs a separate account and token, and has pull limits. GHCR is built in and free for public images.
- **release-please or semantic-release:** automate version bumps from commit messages. Useful later, but they need a commit-message convention first; a hand-pushed tag keeps the flow visible while learning.
- **Release on every push to `main`:** too many releases while the code is still a seed.
- **Deploying somewhere:** out of scope. There is no hosting budget, so "delivery" means published images; running them is `docker compose` for now.

## Consequences

- The web image still calls the API at `http://localhost:8001` (hard-coded in `apps/web/src/api/client.ts`), so it works when API and browser are on the same machine. Making the API URL configurable is needed before any real deployment.
- The web image runs `apk upgrade` so Alpine fixes newer than the base image do not block the Trivy gate; builds are therefore not bit-for-bit reproducible.
- New GHCR packages start private even for a public repo; making them public is a manual step in the package settings after the first release.
- CI builds the web image on every pull request so a broken Dockerfile is found before tagging.
