# 0013 — A conflict-resolving helper (Phase 1: a script run by hand)

- **Status:** Accepted
- **Date:** 2026-10-31
- **Roadmap sub-stage:** tooling (between Stage 1 and Stage 2)

## Context

Each sub-stage is one PR, squash-merged. Stacked PRs and shared files (the ADR index, generated docs) conflict again and again, and the resolution is the same each time and needs no decision. Five times this was done by hand (the stacked-PR case: prove that `main`'s tree equals the parent branch's tip, then `git merge -s ours origin/main`).

## Decision

Add `scripts/resolve_conflicts.py` (`just resolve-conflicts`), run by a person on a PR branch. It merges the base in and fixes **only** these kinds, refusing everything else:

| Kind | Rule |
| --- | --- |
| Stacked PR | With `--parent <old parent branch>`: the parent must be inside this branch **and** `origin/main` must have exactly the parent's tree. Then `merge -s ours`. If `main` moved on, it refuses. |
| Generated file | `docs/ai-terms.md`, `apps/api-py/uv.lock`: take `main`'s copy, then run the generator. A failing generator aborts. |
| Table rows | Both sides only added rows to a Markdown table; all rows are kept, in ADR-number order. Two different rows with one ADR number is a decision, so it refuses. |
| Whitespace | The two sides differ only in whitespace; the branch's version is kept. |

**Safety rules (tested):** refuses on `main`/`master` and on a dirty working tree; dry run by default (`--apply` to commit); one unsafe file blocks the whole merge, which is aborted so the tree is as it was; unmerged files without conflict markers (binary, delete-versus-modify) are refused; it never pushes, force-pushes or comments.

**Left out on purpose:** diagram PNGs (re-rendering from a merged `.mmd` is a build step, not a merge), the root `package-lock.json` (npm workspaces: regenerating it is an install-and-verify step I have not tested; add it deliberately later), and Dependabot PRs (comment `@dependabot rebase` instead).

## Phase 2 (not started)

Running it automatically as a GitHub Action needs a fine-grained token stored as a repository secret, because pushes made with the default token do not trigger CI. That is a security decision for the repository owner and needs approval first.

## Alternatives considered

- **A full merge driver / rerere:** resolves by memory, with no proof and no report.
- **Let a model resolve conflicts:** the whole point is that these need no judgement; a script can be tested and a model could not be trusted with the cases it should refuse.
- **Avoid stacking:** worth doing where possible, but stacks are sometimes the clearest way to review.

## Consequences

- Safe conflicts take one command; unsafe ones are named in a report, not guessed at.
- Tested on small throw-away git repositories, never on a real conflict from this repository's history: the first real use is the real test.
- The generator list is a hard-coded allowlist and must be extended deliberately.
