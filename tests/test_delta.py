import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from sekr.delta import build_delta
from sekr.errors import StructuredError
from sekr.git_delta import GitDeltaSource


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _write(repo: Path, path: str, content: str) -> None:
    destination = repo / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")


def _commit(repo: Path, subject: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", subject)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def delta_history(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Delta Tester")
    _git(repo, "config", "user.email", "delta@example.test")
    _write(
        repo,
        "pkg/service.py",
        """class Service:
    def changed(self, value: int = 1) -> int:
        return value

    def removed(self) -> None:
        return None
""",
    )
    _write(repo, "z_deleted.py", "def obsolete(flag=False):\n    return flag\n")
    _write(repo, "unchanged.txt", "same\n")
    base = _commit(repo, "base commit")

    _write(
        repo,
        "pkg/service.py",
        """class Service:
    def changed(self, value: str) -> str:
        return value.upper()

    async def added(self, flag: bool = False) -> None:
        return None
""",
    )
    _write(
        repo,
        "consumer.py",
        """from pkg.service import Service

def use_service() -> str:
    return Service().changed("value")
""",
    )
    _write(repo, "a_added.txt", "added\n")
    (repo / "z_deleted.py").unlink()
    head = _commit(repo, "head commit")
    return repo, base, head


def test_delta_has_exact_contract_keys_sorted_files_and_preserved_commits(delta_history):
    repo, base, head = delta_history
    source = GitDeltaSource(repo)

    delta = build_delta(source, base, head)
    payload = delta.to_dict()

    assert list(payload) == ["base", "head", "files", "symbols", "impact", "commits"]
    assert payload["base"] == base
    assert payload["head"] == head
    assert payload["files"] == {
        "added": ["a_added.txt", "consumer.py"],
        "modified": ["pkg/service.py"],
        "deleted": ["z_deleted.py"],
    }
    assert payload["commits"] == source.commits_between(base, head)
    with pytest.raises(FrozenInstanceError):
        delta.base = "other"


def test_delta_classifies_nested_ast_symbols_and_signatures(delta_history):
    repo, base, head = delta_history

    symbols = build_delta(GitDeltaSource(repo), base, head).to_dict()["symbols"]

    assert symbols == {
        "added": [
            {
                "path": "consumer.py",
                "qualified_name": "use_service",
                "kind": "function",
                "signature": "() -> str",
            },
            {
                "path": "pkg/service.py",
                "qualified_name": "Service.added",
                "kind": "async_function",
                "signature": "(self, flag: bool=False) -> None",
            },
        ],
        "modified": [
            {
                "path": "pkg/service.py",
                "qualified_name": "Service",
                "kind": "class",
                "signature": "",
            },
            {
                "path": "pkg/service.py",
                "qualified_name": "Service.changed",
                "kind": "function",
                "signature": "(self, value: str) -> str",
            },
        ],
        "deleted": [
            {
                "path": "pkg/service.py",
                "qualified_name": "Service.removed",
                "kind": "function",
                "signature": "(self) -> None",
            },
            {
                "path": "z_deleted.py",
                "qualified_name": "obsolete",
                "kind": "function",
                "signature": "(flag=False)",
            },
        ],
    }


def test_delta_reports_sorted_import_and_call_impacts_for_changed_symbols(delta_history):
    repo, base, head = delta_history

    impact = build_delta(GitDeltaSource(repo), base, head).to_dict()["impact"]

    assert impact == [
        {
            "source": "consumer",
            "target": "Service",
            "relation": "imports",
            "path": "consumer.py",
        },
        {
            "source": "use_service",
            "target": "Service",
            "relation": "calls",
            "path": "consumer.py",
        },
        {
            "source": "use_service",
            "target": "Service.changed",
            "relation": "calls",
            "path": "consumer.py",
        },
    ]


def test_delta_detects_body_only_changes_and_impacts_in_unchanged_head_files(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Delta Tester")
    _git(repo, "config", "user.email", "delta@example.test")
    _write(repo, "target.py", "def changed():\n    return 1\n")
    _write(
        repo,
        "consumer.py",
        "from target import changed\n\ndef use():\n    return changed()\n",
    )
    base = _commit(repo, "base")
    _write(repo, "target.py", "def changed():\n    return 2\n")
    head = _commit(repo, "head")

    payload = build_delta(GitDeltaSource(repo), base, head).to_dict()

    assert payload["symbols"]["modified"] == [
        {
            "path": "target.py",
            "qualified_name": "changed",
            "kind": "function",
            "signature": "()",
        }
    ]
    assert payload["impact"] == [
        {
            "source": "consumer",
            "target": "changed",
            "relation": "imports",
            "path": "consumer.py",
        },
        {
            "source": "use",
            "target": "changed",
            "relation": "calls",
            "path": "consumer.py",
        },
    ]


def test_delta_maps_malformed_python_to_safe_stable_error(tmp_path: Path):
    repo = tmp_path / "private-root" / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.name", "Delta Tester")
    _git(repo, "config", "user.email", "delta@example.test")
    _write(repo, "module.py", "def valid():\n    return 1\n")
    base = _commit(repo, "base")
    _write(repo, "module.py", "def broken(:\n    token = 'secret-value'\n")
    head = _commit(repo, "broken")

    with pytest.raises(StructuredError) as captured:
        build_delta(GitDeltaSource(repo), base, head)

    error = captured.value
    assert error.code == "DELTA_PARSE_ERROR"
    assert error.message == "Python source could not be parsed: module.py"
    assert "private-root" not in str(error.to_dict())
    assert "secret-value" not in str(error.to_dict())
