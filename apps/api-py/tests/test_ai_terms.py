"""The AI colour code: the term list is sound, the marker behaves, and the docs are up to date.

`test_docs_are_up_to_date` is the CI gate: it fails if someone edits a target doc or the term list
without running `just ai-terms`."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import ai_terms  # noqa: E402

DATA, TERMS = ai_terms.load()
CATEGORIES = DATA["categories"]
FAKE_DOC = ROOT / "docs" / "example.md"


def mark(text: str) -> str:
    return ai_terms.mark_document(text, FAKE_DOC, CATEGORIES, TERMS)


def body(text: str) -> str:
    """The marked text without the legend line (which itself shows every marker)."""
    return "\n".join(
        line for line in text.split("\n") if not line.startswith(ai_terms.LEGEND_PREFIX)
    )


# ------------------------------------------------------------------ term list


def test_every_term_is_well_formed():
    ids = [t.id for t in TERMS]
    names = [t.name for t in TERMS]
    assert len(ids) == len(set(ids)) and len(names) == len(set(names))
    for term in TERMS:
        assert term.category in CATEGORIES, term.id
        assert term.match and all(m.strip() for m in term.match), term.id
        assert len(term.meaning) >= 25, f"{term.id}: say what it is in plain words"


def test_each_category_has_its_own_marker():
    markers = [c["marker"] for c in CATEGORIES.values()]
    assert len(set(markers)) == len(markers) == 4
    assert set("".join(markers)) == set(ai_terms.MARKERS)


def test_read_more_links_point_at_real_files():
    for term in TERMS:
        if term.learn:
            assert (ROOT / "docs" / term.learn).resolve().exists(), f"{term.id}: {term.learn}"


def test_target_patterns_match_files():
    assert ai_terms.target_files(DATA), "no target docs found"


# --------------------------------------------------------------- the marker


def test_first_use_in_a_section_is_marked_and_later_uses_are_not():
    out = mark("## A\n\nRAG finds documents. RAG is useful.\n")
    assert "🟪RAG finds documents. RAG is useful." in out


def test_each_section_starts_fresh():
    out = mark("## One\n\nRAG here.\n\n## Two\n\nRAG again.\n")
    assert body(out).count("🟪RAG") == 2


def test_the_right_colour_for_each_kind():
    out = mark("## A\n\nLangGraph, Qdrant, Gemma and an agent.\n")
    assert "🟦LangGraph" in out and "🟩Qdrant" in out and "🟧Gemma" in out and "🟪agent" in out


def test_the_longest_phrase_wins():
    out = mark("## A\n\nAn LLM gateway helps.\n")
    assert "🟪LLM gateway" in out and body(out).count("🟪") == 1


def test_code_headings_link_targets_and_image_alt_text_are_left_alone():
    text = (
        "## RAG heading\n\n"
        "Use `RAG` in code.\n\n"
        "```python\nRAG = 1\n```\n\n"
        "See [the page](https://example.com/RAG) and ![an agent diagram](img/agent.png).\n"
    )
    out = mark(text)
    assert "## RAG heading" in out and "`RAG`" in out and "RAG = 1" in out
    assert "https://example.com/RAG" in out and "![an agent diagram](img/agent.png)" in out
    assert body(out).count("🟪") == 0


def test_a_term_in_bold_is_always_marked():
    out = mark("## A\n\nRAG first.\n\n| **RAG** | again |\n")
    assert "| **🟪RAG** |" in out


def test_words_inside_other_words_are_not_marked():
    out = mark("## A\n\nRagas scores, an enragement of RAGS, the word embeddedness.\n")
    assert "🟪" not in body(out)


def test_marking_twice_changes_nothing():
    once = mark("## A\n\nRAG and LangGraph and agents.\n\n## B\n\nRAG.\n")
    assert mark(once) == once


def test_a_legend_is_added_before_the_first_section_once():
    out = mark("# Title\n\nintro\n\n## First\n\ntext\n")
    assert out.count(ai_terms.LEGEND_PREFIX) == 1
    assert out.index(ai_terms.LEGEND_PREFIX) < out.index("## First")
    assert mark(out) == out


# ------------------------------------------------------------- the CI gate


def test_docs_are_up_to_date():
    stale = [
        str(path.relative_to(ROOT))
        for path, new in ai_terms.render_all().items()
        if not path.exists() or path.read_text() != new
    ]
    assert stale == [], "run `just ai-terms` and commit the result"


def test_the_glossary_lists_every_term():
    text = (ROOT / "docs" / "ai-terms.md").read_text()
    for term in TERMS:
        assert f"**{term.name}**" in text, term.id


@pytest.mark.parametrize("path", ai_terms.target_files(DATA), ids=lambda p: p.name)
def test_target_docs_carry_the_legend(path):
    assert ai_terms.LEGEND_PREFIX in path.read_text()
