#!/usr/bin/env python3
"""Resolves the merge conflicts that need no decision, and refuses everything else.

Run it on a PR branch that conflicts with `main`. It merges the base into the branch, looks at every
conflict, and fixes only the kinds listed in docs/adr/0013-conflict-bot.md:

  * stacked PR   the parent branch was squash-merged: main's tree equals the parent's tip, so the
                 child already has all of main's content (needs --parent, proven before use)
  * generated    docs/ai-terms.md, uv.lock: take main's copy, then run the generator
  * table rows   both sides only added rows to a Markdown table (the ADR index): keep both
  * whitespace   both sides differ only in whitespace: keep the branch's version

Anything else (real code, prose, two different ADRs with one number, diagram PNGs) is left alone: the
merge is aborted, the working tree is clean again, and the report says what a person must decide.

    python scripts/resolve_conflicts.py                       # dry run: report only, changes nothing
    python scripts/resolve_conflicts.py --apply               # commit the merge if all of it is safe
    python scripts/resolve_conflicts.py --parent origin/feat/1.2-x --apply

Safety rules, enforced in code: refuses on main or master; refuses a dirty working tree; never pushes,
never force-pushes (pushing and commenting are for a person or, later, a workflow); an apply only
commits when every conflict was resolved.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROTECTED_BRANCHES = {"main", "master"}
BASE_DEFAULT = "origin/main"

# Files that are produced by a command: take main's copy, then regenerate and let the command decide.
REGENERATORS: dict[str, list[str]] = {
    "docs/ai-terms.md": [
        "uv",
        "run",
        "--project",
        "apps/api-py",
        "python",
        "scripts/ai_terms.py",
        "write",
    ],
    "apps/api-py/uv.lock": ["uv", "lock", "--project", "apps/api-py"],
}

ROW = re.compile(r"^\s*\|")
NUMBER = re.compile(r"\[(\d{4})\]")  # the ADR number in a table row such as "| [0011](...) | ..."


class Refused(Exception):
    """Raised when the situation is not one this tool may touch."""


@dataclass
class Outcome:
    path: str
    kind: str  # the class that resolved it, or "refused"
    detail: str

    @property
    def safe(self) -> bool:
        return self.kind != "refused"


@dataclass
class Report:
    branch: str
    base: str
    outcomes: list[Outcome] = field(default_factory=list)
    note: str = ""
    committed: bool = False

    @property
    def all_safe(self) -> bool:
        return all(o.safe for o in self.outcomes)

    def markdown(self) -> str:
        lines = [f"### Conflict check: `{self.branch}` with `{self.base}`", ""]
        if self.note:
            lines += [self.note, ""]
        if self.outcomes:
            lines += ["| File | Result | Why |", "| --- | --- | --- |"]
            lines += [f"| `{o.path}` | {o.kind} | {o.detail} |" for o in self.outcomes]
            lines.append("")
        if self.committed:
            lines.append("The merge was committed. Review the diff and push.")
        elif self.outcomes and self.all_safe:
            lines.append(
                "Every conflict is a safe kind. Run again with `--apply` to commit the merge."
            )
        elif self.outcomes:
            lines.append("Not resolved: at least one conflict needs a person. Nothing was changed.")
        return "\n".join(lines)


def git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result


# ---- conflict hunks -------------------------------------------------------------------------


@dataclass
class Hunk:
    ours: list[str]
    base: list[str]
    theirs: list[str]


def split_conflicts(text: str) -> list[str | Hunk]:
    """Splits a file with diff3 conflict markers into plain lines and Hunk objects.

    Raises Refused when the markers are not the well-formed diff3 shape."""
    parts: list[str | Hunk] = []
    state = "plain"
    ours: list[str] = []
    base: list[str] = []
    theirs: list[str] = []
    for line in text.splitlines(keepends=True):
        if state == "plain":
            if line.startswith("<<<<<<< "):
                state, ours, base, theirs = "ours", [], [], []
            else:
                parts.append(line)
        elif state == "ours":
            if line.startswith("||||||| "):
                state = "base"
            elif line.startswith("======="):
                raise Refused("conflict has no common-ancestor section (not diff3 style)")
            else:
                ours.append(line)
        elif state == "base":
            if line.startswith("======="):
                state = "theirs"
            else:
                base.append(line)
        elif state == "theirs":
            if line.startswith(">>>>>>> "):
                parts.append(Hunk(ours, base, theirs))
                state = "plain"
            else:
                theirs.append(line)
    if state != "plain":
        raise Refused("unterminated conflict markers")
    return parts


def row_key(line: str) -> str | None:
    found = NUMBER.search(line)
    return found.group(1) if found else None


def resolve_rows(hunk: Hunk) -> list[str] | None:
    """Both sides only added table rows to the common text: keep every row once, in ADR-number order."""
    if not all(ROW.match(x) for x in hunk.ours + hunk.theirs):
        return None
    base = hunk.base
    # each side must be the base plus added lines (nothing removed or edited)
    if hunk.ours[: len(base)] != base or hunk.theirs[: len(base)] != base:
        return None
    ours_added, theirs_added = hunk.ours[len(base) :], hunk.theirs[len(base) :]
    if not ours_added or not theirs_added:
        return None
    seen: dict[str, str] = {}
    for row in ours_added + theirs_added:
        key = row_key(row)
        if key is None:
            continue
        if key in seen and seen[key].strip() != row.strip():
            return None  # one number, two different rows: a decision
        seen[key] = row
    merged = list(base)
    for row in ours_added + theirs_added:
        if row not in merged:
            merged.append(row)
    if all(row_key(r) for r in merged):
        merged.sort(key=lambda r: row_key(r) or "")
    return merged


def resolve_whitespace(hunk: Hunk) -> list[str] | None:
    if "".join("".join(hunk.ours).split()) == "".join("".join(hunk.theirs).split()):
        return hunk.ours
    return None


def resolve_text(text: str) -> tuple[str, str] | None:
    """Resolves every hunk in a file, or returns None if any hunk needs a person."""
    kinds: list[str] = []
    out: list[str] = []
    parts = split_conflicts(text)
    if not any(isinstance(p, Hunk) for p in parts):
        raise Refused(
            "the file is unmerged but has no conflict markers (binary, or deleted on one side)"
        )
    for part in parts:
        if isinstance(part, str):
            out.append(part)
            continue
        for kind, fn in (("table rows", resolve_rows), ("whitespace only", resolve_whitespace)):
            resolved = fn(part)
            if resolved is not None:
                out.extend(resolved)
                kinds.append(kind)
                break
        else:
            return None
    return "".join(out), " + ".join(sorted(set(kinds)))


# ---- the run --------------------------------------------------------------------------------


def current_branch(repo: Path) -> str:
    return git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo).stdout.strip()


def stacked_squash(repo: Path, parent: str, base: str) -> str | None:
    """Returns a proof string if `base` already contains everything of `parent`, else None."""
    if git("merge-base", "--is-ancestor", parent, "HEAD", cwd=repo, check=False).returncode != 0:
        return None
    base_tree = git("rev-parse", f"{base}^{{tree}}", cwd=repo).stdout.strip()
    parent_tree = git("rev-parse", f"{parent}^{{tree}}", cwd=repo).stdout.strip()
    if base_tree != parent_tree:
        return None
    return f"{base} has the same tree ({base_tree[:10]}) as {parent}, which this branch contains"


def run(
    repo: Path, base: str = BASE_DEFAULT, parent: str | None = None, apply: bool = False
) -> Report:
    branch = current_branch(repo)
    if branch in PROTECTED_BRANCHES or branch == "HEAD":
        raise Refused(f"refusing to run on {branch!r}: check out the PR branch")
    if git("status", "--porcelain", "--untracked-files=no", cwd=repo).stdout.strip():
        raise Refused("the working tree has uncommitted changes: commit or stash them first")
    report = Report(branch, base)

    if git("merge-base", "--is-ancestor", base, "HEAD", cwd=repo, check=False).returncode == 0:
        report.note = f"`{base}` is already contained in this branch: nothing to merge."
        return report

    if parent:
        proof = stacked_squash(repo, parent, base)
        if proof is None:
            raise Refused(
                f"cannot prove the stacked-PR case for --parent {parent}: either it is not contained in "
                f"this branch or {base} has a different tree (main moved on). Resolve by hand."
            )
        report.outcomes.append(Outcome("(whole merge)", "stacked PR", proof))
        if apply:
            git(
                "merge",
                "-s",
                "ours",
                "-m",
                f"Merge {base} into {branch} (parent already squash-merged)",
                base,
                cwd=repo,
            )
            report.committed = True
        return report

    merged = git(
        "-c",
        "merge.conflictStyle=diff3",
        "merge",
        "--no-commit",
        "--no-ff",
        base,
        cwd=repo,
        check=False,
    )
    if merged.returncode == 0:
        report.note = "The merge has no conflicts."
        if apply:
            git("commit", "--no-edit", cwd=repo)
            report.committed = True
        else:
            git("merge", "--abort", cwd=repo, check=False)
        return report

    conflicted = git("diff", "--name-only", "--diff-filter=U", cwd=repo).stdout.split()
    if not conflicted:
        git("merge", "--abort", cwd=repo, check=False)
        raise RuntimeError(f"git merge failed without conflicts: {merged.stderr.strip()}")

    regenerate: list[str] = []
    fixes: dict[str, str] = {}
    for path in conflicted:
        if path in REGENERATORS:
            git("checkout", "--theirs", "--", path, cwd=repo)
            regenerate.append(path)
            report.outcomes.append(
                Outcome(path, "generated", "take main's copy, then run the generator")
            )
            continue
        try:
            resolved = resolve_text((repo / path).read_text())
        except (Refused, UnicodeDecodeError, FileNotFoundError) as exc:
            report.outcomes.append(
                Outcome(path, "refused", f"not a text conflict this tool understands ({exc})")
            )
            continue
        if resolved is None:
            report.outcomes.append(
                Outcome(path, "refused", "both sides changed the same lines: needs a decision")
            )
        else:
            fixes[path] = resolved[0]
            report.outcomes.append(
                Outcome(path, resolved[1], "both sides kept; nothing was removed")
            )

    if not report.all_safe or not apply:
        git("merge", "--abort", cwd=repo, check=False)
        return report

    for path, content in fixes.items():
        (repo / path).write_text(content)
        git("add", "--", path, cwd=repo)
    for path in regenerate:
        done = subprocess.run(REGENERATORS[path], cwd=repo, capture_output=True, text=True)
        if done.returncode != 0:
            git("merge", "--abort", cwd=repo, check=False)
            report.outcomes = [o for o in report.outcomes if o.path != path]
            report.outcomes.append(
                Outcome(path, "refused", f"the generator failed: {done.stderr.strip()[-200:]}")
            )
            return report
        git("add", "--", path, cwd=repo)
    git(
        "commit",
        "-m",
        f"Merge {base} into {branch} (conflicts resolved by scripts/resolve_conflicts.py)",
        cwd=repo,
    )
    report.committed = True
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--base", default=BASE_DEFAULT, help="what to merge in (default: origin/main)"
    )
    parser.add_argument(
        "--parent", help="the old parent branch of a stacked PR, to prove a squash-merge"
    )
    parser.add_argument(
        "--apply", action="store_true", help="commit the merge when every conflict is safe"
    )
    parser.add_argument(
        "--repo", default=".", help="repository to work in (default: current directory)"
    )
    args = parser.parse_args(argv)
    try:
        report = run(Path(args.repo).resolve(), args.base, args.parent, args.apply)
    except Refused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    print(report.markdown())
    return 0 if report.all_safe else 1


if __name__ == "__main__":
    raise SystemExit(main())
