#!/usr/bin/env python3
"""AI colour code for the docs.

Reads docs/ai-terms.yaml and
  - puts a coloured square before the FIRST use of each AI term in every section (H1 or H2) of
    the target docs, skipping code, links' targets, headings and diagram text;
  - keeps a one-line legend before the first H2 of each target doc;
  - generates docs/ai-terms.md (the A to Z list).

    uv run --project apps/api-py python scripts/ai_terms.py write    # apply
    uv run --project apps/api-py python scripts/ai_terms.py check    # fail if anything is out of date
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TERMS_FILE = ROOT / "docs" / "ai-terms.yaml"
GLOSSARY_FILE = ROOT / "docs" / "ai-terms.md"
LEGEND_PREFIX = "**AI colour code:**"
MARKERS = "🟪🟦🟩🟧"
MASK = "\x00"


@dataclass(frozen=True)
class Term:
    id: str
    name: str
    category: str
    match: tuple[str, ...]
    ignore_case: bool
    meaning: str
    since: str
    learn: str | None


def load() -> tuple[dict, list[Term]]:
    data = yaml.safe_load(TERMS_FILE.read_text())
    terms = [
        Term(
            id=t["id"],
            name=t["name"],
            category=t["category"],
            match=tuple(t["match"]),
            ignore_case=bool(t.get("ignore_case", False)),
            meaning=t["meaning"],
            since=str(t["since"]),
            learn=t.get("learn"),
        )
        for t in data["terms"]
    ]
    return data, terms


def build_matcher(terms: list[Term]) -> tuple[re.Pattern[str], dict[str, Term]]:
    """One regex over every phrase, longest phrase first so 'LLM gateway' beats 'LLM'."""
    alternatives: list[tuple[int, str, Term]] = []
    for term in terms:
        for phrase in term.match:
            body = phrase[3:] if phrase.startswith("re:") else re.escape(phrase)
            flag = "(?i:" if term.ignore_case else "(?:"
            alternatives.append((len(phrase), f"{flag}{body})", term))
    alternatives.sort(key=lambda a: -a[0])
    groups: dict[str, Term] = {}
    parts = []
    for index, (_, pattern, term) in enumerate(alternatives):
        name = f"g{index}"
        groups[name] = term
        parts.append(f"(?P<{name}>{pattern})")
    return re.compile(r"(?<![\w@/-])(?:" + "|".join(parts) + r")(?![\w-])"), groups


_MASKS = [
    re.compile(r"`[^`\n]*`"),  # inline code
    re.compile(r"!\[[^\]]*\]"),  # image alt text
    re.compile(r"\]\([^)\n]*\)"),  # link and image targets
    re.compile(r"<code>.*?</code>"),
    re.compile(r"<[^>\n]+>"),  # html tags and autolinks
    re.compile(r"https?://[^\s)>]+"),
    re.compile(r"\[![A-Z]+\]"),  # GitHub call-out tags
]


def masked(line: str) -> str:
    out = line
    for pattern in _MASKS:
        out = pattern.sub(lambda m: MASK * len(m.group(0)), out)
    return out


def _skip_line(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped.startswith("#")
        or stripped.startswith("<sub>Diagram source")
        or stripped.startswith(LEGEND_PREFIX)
        or bool(re.match(r"^\|[\s:|-]+\|?$", stripped))
        or bool(re.match(r"^\[[^\]]+\]:\s", stripped))
    )


def legend_line(categories: dict, rel_to_glossary: str) -> str:
    keys = ["concept", "tool", "service", "model"]
    names = {
        "concept": "concept",
        "tool": "framework or tool",
        "service": "data store or service",
        "model": "model",
    }
    chips = " · ".join(f"{categories[k]['marker']} {names[k]}" for k in keys)
    return f"{LEGEND_PREFIX} {chips}. Unmarked technical terms are ordinary software. [A to Z list]({rel_to_glossary})"


def mark_document(text: str, path: Path, categories: dict, terms: list[Term]) -> str:
    matcher, groups = build_matcher(terms)
    marker_for = {t.id: categories[t.category]["marker"] for t in terms}
    rel = Path(__import__("os").path.relpath(GLOSSARY_FILE, path.parent)).as_posix()
    lines = text.split("\n")
    out: list[str] = []
    fenced = False
    seen: set[str] = set()
    legend_done = False
    legend = legend_line(categories, rel)
    for line in lines:
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            out.append(line)
            continue
        if fenced:
            out.append(line)
            continue
        if line.startswith(LEGEND_PREFIX):
            continue  # re-inserted (with its blank lines) before the first H2
        if re.match(r"^## ", line) and not legend_done:
            while out and out[-1] == "":  # exactly one blank line before the legend
                out.pop()
            out.extend(["", legend, ""])
            legend_done = True
        if re.match(r"^#{1,2} ", line):
            seen = set()
        if _skip_line(line):
            out.append(line)
            continue
        line = re.sub(rf"[{MARKERS}](?=[A-Za-z0-9])", "", line)  # drop old markers, then redo
        view = masked(line)
        # a term the doc already emphasises in **bold** (table row names, list headings) is always marked
        bold = [m.span() for m in re.finditer(r"\*\*[^*\n]+\*\*", view)]
        inserts: list[tuple[int, str]] = []
        for match in matcher.finditer(view):
            term = groups[match.lastgroup or ""]
            in_bold = any(start <= match.start() and match.end() <= end for start, end in bold)
            if term.id in seen and not in_bold:
                continue
            seen.add(term.id)
            inserts.append((match.start(), marker_for[term.id]))
        for position, marker in reversed(inserts):
            line = line[:position] + marker + line[position:]
        out.append(line)
    return "\n".join(out)


def target_files(data: dict) -> list[Path]:
    files: dict[Path, None] = {}
    for pattern in data["targets"]:
        for path in sorted(ROOT.glob(pattern)):
            files[path] = None
    return list(files)


def glossary_text(data: dict, terms: list[Term]) -> str:
    cats = data["categories"]
    lines = [
        "# AI terms, A to Z",
        "",
        "> Generated from [`ai-terms.yaml`](ai-terms.yaml) by `just ai-terms`. Do not edit by hand.",
        "",
        "Building with language models brings a lot of new words, mixed in with ordinary software words. "
        "This project marks the AI ones with a coloured square the first time they appear in each section "
        'of the main docs, so you can tell "this is the AI part" from "this is normal engineering" at a glance.',
        "",
        "| Marker | Meaning | Examples |",
        "| --- | --- | --- |",
    ]
    for key in ("concept", "tool", "service", "model"):
        examples = (
            ", ".join(t.name for t in terms if t.category == key)[:70].rsplit(",", 1)[0] + ", ..."
        )
        lines.append(
            f"| {cats[key]['marker']} | **{cats[key]['name']}**. {cats[key]['blurb']} | {examples} |"
        )
    lines += [
        "",
        "Anything **without** a marker is ordinary software (databases, web frameworks, build and delivery tools). "
        "Those are listed at the end of this page.",
        "",
    ]
    for key in ("concept", "tool", "service", "model"):
        category = cats[key]
        lines += [
            f"## {category['marker']} {category['name']}s",
            "",
            category["blurb"],
            "",
            "| Term | In plain words | Matters from | Read more |",
            "| --- | --- | --- | --- |",
        ]
        for term in sorted((t for t in terms if t.category == key), key=lambda t: t.name.lower()):
            if term.learn is None:
                more = ""
            elif term.learn.startswith("stages/"):
                more = f"[stage guide]({term.learn})"
            elif term.learn.startswith("v2-baseline/"):
                more = f"[V2 record]({term.learn})"
            else:
                more = f"[guide]({term.learn})"
            since = (
                "V2 seed"
                if term.since == "Seed"
                else f"sub-stage {term.since}"
                if term.since[0].isdigit()
                else term.since
            )
            lines.append(
                f"| {category['marker']} **{term.name}** | {term.meaning} | {since} | {more} |"
            )
        lines.append("")
    lines += [
        "## Ordinary software (not marked)",
        "",
        "These are common in any enterprise application, not specific to AI:",
        "",
    ]
    lines += [f"- {item}" for item in data["not_ai"]]
    lines += [
        "",
        "## Adding or changing a term",
        "",
        "1. Edit [`ai-terms.yaml`](ai-terms.yaml): one entry per term, with a plain-words meaning.",
        "2. Run `just ai-terms`. It re-marks every target doc and regenerates this page.",
        "3. Commit the result. CI runs `just ai-terms-check` and fails if anything is out of date.",
        "",
    ]
    return "\n".join(lines)


def render_all() -> dict[Path, str]:
    data, terms = load()
    results: dict[Path, str] = {}
    for path in target_files(data):
        results[path] = mark_document(path.read_text(), path, data["categories"], terms)
    results[GLOSSARY_FILE] = glossary_text(data, terms)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["write", "check"])
    args = parser.parse_args()
    results = render_all()
    stale = [p for p, new in results.items() if not p.exists() or p.read_text() != new]
    if args.command == "write":
        for path in stale:
            path.write_text(results[path])
        print(f"updated {len(stale)} file(s)" if stale else "already up to date")
        return 0
    for path in stale:
        old = path.read_text().splitlines() if path.exists() else []
        diff = list(difflib.unified_diff(old, results[path].splitlines(), lineterm="", n=0))
        print(f"STALE {path.relative_to(ROOT)} ({len(diff)} diff lines); first changes:")
        print("\n".join(diff[2:8]))
    if stale:
        print("\nRun `just ai-terms` and commit the result.")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
