import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from sekr.errors import StructuredError
from sekr.git_delta import GitDeltaSource


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env
    )
    return completed.stdout.strip()


def _commit(repo: Path, subject: str, timestamp: str) -> str:
    environment = os.environ | {
        "GIT_AUTHOR_DATE": timestamp,
        "GIT_COMMITTER_DATE": timestamp,
    }
    _git(repo, "commit", "-m", subject, env=environment)
    return _git(repo, "rev-parse", "HEAD")


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


def test_reader_returns_commit_metadata_sorted_by_timestamp_then_id(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Delta Tester")
    _git(repo, "config", "user.email", "delta@example.test")
    (repo / "history.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "history.txt")
    base = _commit(repo, "base commit", "2024-01-01T00:00:00+00:00")

    (repo / "history.txt").write_text("first\n", encoding="utf-8")
    _git(repo, "add", "history.txt")
    later_commit = _commit(repo, "later commit", "2024-01-03T04:05:06+00:00")
    (repo / "history.txt").write_text("second\n", encoding="utf-8")
    _git(repo, "add", "history.txt")
    earlier_commit = _commit(repo, "earlier commit", "2024-01-02T04:05:06+00:00")

    assert GitDeltaSource(repo).commits_between(base, earlier_commit) == [
        {
            "id": earlier_commit,
            "author": "Delta Tester",
            "subject": "earlier commit",
            "timestamp": "2024-01-02T04:05:06Z",
        },
        {
            "id": later_commit,
            "author": "Delta Tester",
            "subject": "later commit",
            "timestamp": "2024-01-03T04:05:06Z",
        },
    ]


def test_reader_classifies_file_to_symlink_type_change_as_modified(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Delta Tester")
    _git(repo, "config", "user.email", "delta@example.test")
    (repo / "entry.txt").write_text("regular file\n", encoding="utf-8")
    _git(repo, "add", "entry.txt")
    _git(repo, "commit", "-m", "regular file")
    base = _git(repo, "rev-parse", "HEAD")

    (repo / "symlink-target.txt").write_text("target\n", encoding="utf-8")
    blob_id = _git(repo, "hash-object", "-w", "symlink-target.txt")
    _git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob_id},entry.txt")
    _git(repo, "commit", "-m", "replace file with symlink")
    head = _git(repo, "rev-parse", "HEAD")

    assert GitDeltaSource(repo).changed_files(base, head) == {
        "added": [],
        "modified": ["entry.txt"],
        "deleted": [],
    }


@pytest.mark.parametrize("ref", ("", "does-not-exist", "-unsafe-ref"))
def test_reader_rejects_invalid_and_option_like_refs(git_history, ref):
    repo, _, _ = git_history

    with pytest.raises(StructuredError) as error:
        GitDeltaSource(repo).validate_ref(ref)

    assert error.value.code == "DELTA_INVALID_REF"


def test_reader_rejects_non_repository_paths():
    with tempfile.TemporaryDirectory() as directory:
        with pytest.raises(StructuredError) as error:
            GitDeltaSource(Path(directory)).validate_ref("HEAD")

    assert error.value.code == "DELTA_NOT_REPOSITORY"


@pytest.mark.parametrize("path", ("", "../outside.txt", "/absolute.txt", "dir\\file.txt"))
def test_reader_rejects_unsafe_tree_paths(git_history, path):
    repo, _, head = git_history

    with pytest.raises(StructuredError) as error:
        GitDeltaSource(repo).read_tree(head, path)

    assert error.value.code == "DELTA_TREE_ERROR"
