import subprocess
from pathlib import Path

import pytest

from sekr.errors import StructuredError
from sekr.git_delta import GitDeltaSource


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


@pytest.fixture
def git_history(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Delta Tester")
    _git(repo, "config", "user.email", "delta@example.test")
    (repo / "changed.txt").write_text("before\n", encoding="utf-8")
    (repo / "deleted.txt").write_text("delete me\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base commit")
    base = _git(repo, "rev-parse", "HEAD")

    (repo / "changed.txt").write_text("after\n", encoding="utf-8")
    (repo / "deleted.txt").unlink()
    (repo / "added.txt").write_text("new file\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "head commit")
    head = _git(repo, "rev-parse", "HEAD")
    return repo, base, head


def test_reader_reports_sorted_add_modify_delete_and_reads_tree(git_history):
    repo, base, head = git_history
    source = GitDeltaSource(repo)

    assert source.changed_files(base, head) == {
        "added": ["added.txt"],
        "modified": ["changed.txt"],
        "deleted": ["deleted.txt"],
    }
    assert source.read_tree(base, "changed.txt") == b"before\n"
    assert source.read_tree(head, "changed.txt") == b"after\n"


def test_reader_returns_deterministic_commit_metadata(git_history):
    repo, base, head = git_history

    assert GitDeltaSource(repo).commits_between(base, head) == [
        {
            "id": head,
            "author": "Delta Tester",
            "subject": "head commit",
            "timestamp": GitDeltaSource(repo).commits_between(base, head)[0]["timestamp"],
        }
    ]


@pytest.mark.parametrize("ref", ("", "does-not-exist", "-unsafe-ref"))
def test_reader_rejects_invalid_and_option_like_refs(git_history, ref):
    repo, _, _ = git_history

    with pytest.raises(StructuredError) as error:
        GitDeltaSource(repo).validate_ref(ref)

    assert error.value.code == "DELTA_INVALID_REF"


def test_reader_rejects_non_repository_paths(tmp_path):
    with pytest.raises(StructuredError) as error:
        GitDeltaSource(tmp_path).validate_ref("HEAD")

    assert error.value.code == "DELTA_NOT_REPOSITORY"


@pytest.mark.parametrize("path", ("", "../outside.txt", "/absolute.txt", "dir\\file.txt"))
def test_reader_rejects_unsafe_tree_paths(git_history, path):
    repo, _, head = git_history

    with pytest.raises(StructuredError) as error:
        GitDeltaSource(repo).read_tree(head, path)

    assert error.value.code == "DELTA_TREE_ERROR"
