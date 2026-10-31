"""The conflict-resolving script, tested on small real git repositories.

Every safe class has a test that it is resolved; every unsafe situation has a test that it is
refused and leaves the working tree exactly as it was."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import resolve_conflicts as rc  # noqa: E402

ADR_HEAD = "| ADR | Title |\n| --- | --- |\n"


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def write(repo: Path, path: str, text: str, message: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository whose `origin/main` is a local ref (no network, no remote needed)."""
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.name", "test")
    git(tmp_path, "config", "user.email", "test@example.com")
    write(tmp_path, "README.md", "hello\n", "init")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", "main")
    return tmp_path


def advance_main(repo: Path, path: str, text: str, message: str) -> None:
    """Commit on main, publish it as origin/main, and return to the previous branch."""
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    git(repo, "checkout", "-q", "main")
    write(repo, path, text, message)
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    git(repo, "checkout", "-q", branch)


def snapshot(repo: Path) -> tuple[str, str]:
    return git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain")


# ---- refusals before anything happens -------------------------------------------------------


def test_refuses_to_run_on_main(repo):
    with pytest.raises(rc.Refused, match="main"):
        rc.run(repo)


def test_refuses_a_dirty_working_tree(repo):
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "README.md").write_text("edited\n")
    with pytest.raises(rc.Refused, match="uncommitted"):
        rc.run(repo)


def test_nothing_to_merge_when_base_is_already_inside(repo):
    git(repo, "checkout", "-q", "-b", "feature")
    report = rc.run(repo)
    assert "nothing to merge" in report.note and report.outcomes == []


# ---- table rows ------------------------------------------------------------------------------


def adr_conflict(repo: Path, ours_row: str, theirs_row: str) -> None:
    write(repo, "docs/adr/README.md", ADR_HEAD + "| [0001](a.md) | One |\n", "adr index")
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    git(repo, "checkout", "-q", "-b", "feature")
    write(
        repo, "docs/adr/README.md", ADR_HEAD + "| [0001](a.md) | One |\n" + ours_row, "feature adds"
    )
    advance_main(
        repo, "docs/adr/README.md", ADR_HEAD + "| [0001](a.md) | One |\n" + theirs_row, "main adds"
    )


def test_two_added_adr_rows_are_both_kept_in_order(repo):
    adr_conflict(repo, "| [0003](c.md) | Three |\n", "| [0002](b.md) | Two |\n")
    report = rc.run(repo, apply=True)
    assert report.committed and report.all_safe
    text = (repo / "docs/adr/README.md").read_text()
    assert (
        text
        == ADR_HEAD + "| [0001](a.md) | One |\n| [0002](b.md) | Two |\n| [0003](c.md) | Three |\n"
    )
    assert git(repo, "rev-list", "--parents", "-n1", "HEAD").count(" ") == 2, "a real merge commit"


def test_one_adr_number_with_two_different_rows_is_refused(repo):
    adr_conflict(repo, "| [0002](x.md) | Ours |\n", "| [0002](y.md) | Theirs |\n")
    before = snapshot(repo)
    report = rc.run(repo, apply=True)
    assert not report.all_safe and not report.committed
    assert snapshot(repo) == before


# ---- whitespace, generated files -------------------------------------------------------------


def test_whitespace_only_difference_keeps_the_branch_version(repo):
    write(repo, "notes.md", "alpha beta\n", "notes")
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "notes.md", "alpha  beta\n", "feature spacing")
    advance_main(repo, "notes.md", "alpha\tbeta\n", "main spacing")
    report = rc.run(repo, apply=True)
    assert report.committed
    assert (repo / "notes.md").read_text() == "alpha  beta\n"


def test_generated_file_is_taken_from_main_then_regenerated(repo, monkeypatch):
    monkeypatch.setitem(
        rc.REGENERATORS, "docs/ai-terms.md", ["sh", "-c", "echo regenerated > docs/ai-terms.md"]
    )
    write(repo, "docs/ai-terms.md", "one\n", "generated")
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "docs/ai-terms.md", "ours\n", "feature")
    advance_main(repo, "docs/ai-terms.md", "theirs\n", "main")
    report = rc.run(repo, apply=True)
    assert report.committed and [o.kind for o in report.outcomes] == ["generated"]
    assert (repo / "docs/ai-terms.md").read_text() == "regenerated\n"


def test_a_failing_generator_aborts_cleanly(repo, monkeypatch):
    monkeypatch.setitem(rc.REGENERATORS, "docs/ai-terms.md", ["sh", "-c", "echo boom >&2; exit 3"])
    write(repo, "docs/ai-terms.md", "one\n", "generated")
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "docs/ai-terms.md", "ours\n", "feature")
    advance_main(repo, "docs/ai-terms.md", "theirs\n", "main")
    before = snapshot(repo)
    report = rc.run(repo, apply=True)
    assert not report.committed and not report.all_safe
    assert snapshot(repo) == before


# ---- real conflicts are refused --------------------------------------------------------------


def code_conflict(repo: Path) -> None:
    write(repo, "app.py", "def f():\n    return 1\n", "app")
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "app.py", "def f():\n    return 2\n", "feature change")
    advance_main(repo, "app.py", "def f():\n    return 3\n", "main change")


def test_a_real_code_conflict_is_refused_and_left_untouched(repo):
    code_conflict(repo)
    before = snapshot(repo)
    report = rc.run(repo, apply=True)
    assert not report.committed and [o.kind for o in report.outcomes] == ["refused"]
    assert snapshot(repo) == before
    assert "<<<<<<<" not in (repo / "app.py").read_text()


def test_one_unsafe_file_blocks_the_whole_merge_even_if_others_are_safe(repo):
    code_conflict(repo)
    write(repo, "notes.md", "a b\n", "notes on feature")
    advance_main(repo, "notes.md", "a  b\n", "notes on main")  # adds on both sides: also conflicts
    before = snapshot(repo)
    report = rc.run(repo, apply=True)
    assert not report.committed and not report.all_safe
    assert snapshot(repo) == before


def test_dry_run_changes_nothing_even_when_everything_is_safe(repo):
    adr_conflict(repo, "| [0003](c.md) | Three |\n", "| [0002](b.md) | Two |\n")
    before = snapshot(repo)
    report = rc.run(repo)  # no apply
    assert report.all_safe and not report.committed
    assert "--apply" in report.markdown()
    assert snapshot(repo) == before


def test_binary_conflict_is_refused(repo):
    (repo / "pic.png").write_bytes(b"\x89PNG\x00\x01")
    git(repo, "add", "-A"), git(repo, "commit", "-q", "-m", "png")
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "pic.png", "\x89PNG\x00ours", "feature png")
    advance_main(repo, "pic.png", "\x89PNG\x00theirs", "main png")
    before = snapshot(repo)
    report = rc.run(repo, apply=True)
    assert not report.committed and not report.all_safe
    assert snapshot(repo) == before


# ---- stacked PR after a squash merge ----------------------------------------------------------


def stacked(repo: Path, main_moves_on: bool = False) -> None:
    """main <- parent (squash-merged into main) <- child."""
    git(repo, "checkout", "-q", "-b", "parent")
    write(repo, "feature.txt", "parent work\n", "parent commit 1")
    write(repo, "feature.txt", "parent work v2\n", "parent commit 2")
    git(repo, "checkout", "-q", "-b", "child")
    write(repo, "feature.txt", "parent work v2\nchild work\n", "child commit")
    git(repo, "checkout", "-q", "main")
    git(repo, "checkout", "parent", "--", ".")  # the squash: one new commit with the parent's tree
    git(repo, "commit", "-q", "-m", "squash of parent")
    if main_moves_on:
        write(repo, "other.txt", "later\n", "unrelated main work")
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    git(repo, "checkout", "-q", "child")


def test_stacked_pr_is_resolved_by_proof_and_keeps_the_childs_files(repo):
    stacked(repo)
    assert (
        rc.run(repo).committed is False
    )  # the plain merge would conflict; dry run reports nothing safe to claim
    report = rc.run(repo, parent="parent", apply=True)
    assert report.committed and report.outcomes[0].kind == "stacked PR"
    assert (repo / "feature.txt").read_text() == "parent work v2\nchild work\n"
    assert git(repo, "merge-base", "--is-ancestor", "origin/main", "HEAD") == ""


def test_stacked_pr_is_refused_when_main_moved_on(repo):
    stacked(repo, main_moves_on=True)
    before = snapshot(repo)
    with pytest.raises(rc.Refused, match="cannot prove"):
        rc.run(repo, parent="parent", apply=True)
    assert snapshot(repo) == before


def test_stacked_pr_is_refused_when_the_parent_is_not_in_this_branch(repo):
    stacked(repo)
    git(repo, "checkout", "-q", "-b", "other", "main~1")
    with pytest.raises(rc.Refused, match="cannot prove"):
        rc.run(repo, parent="parent", apply=True)


# ---- the pure hunk logic ---------------------------------------------------------------------


def test_split_conflicts_rejects_two_way_markers():
    with pytest.raises(rc.Refused):
        rc.split_conflicts("<<<<<<< a\nx\n=======\ny\n>>>>>>> b\n")


def test_table_rows_never_drop_a_changed_base_row():
    hunk = rc.Hunk(
        ours=["| [0001](a) | Changed |\n"],
        base=["| [0001](a) | One |\n"],
        theirs=["| [0001](a) | One |\n", "| [0002](b) | Two |\n"],
    )
    assert rc.resolve_rows(hunk) is None


def test_main_cli_exit_codes(repo, capsys):
    code_conflict(repo)
    assert rc.main(["--repo", str(repo), "--apply"]) == 1
    git(repo, "checkout", "-q", "main")
    assert rc.main(["--repo", str(repo)]) == 2
    assert "Refused" in capsys.readouterr().err
