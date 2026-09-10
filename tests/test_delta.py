import ast
import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from sekr.delta import Symbol, _ImpactVisitor, build_delta
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


def _run_delta_cli(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path("src").resolve())
    return subprocess.run(
        [sys.executable, "-m", "sekr.cli", "delta", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        env=environment,
    )


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
            "target": "pkg/service.py:Service",
            "relation": "imports",
            "path": "consumer.py",
        },
        {
            "source": "use_service",
            "target": "pkg/service.py:Service",
            "relation": "calls",
            "path": "consumer.py",
        },
        {
            "source": "use_service",
            "target": "pkg/service.py:Service.changed",
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
            "target": "target.py:changed",
            "relation": "imports",
            "path": "consumer.py",
        },
        {
            "source": "use",
            "target": "target.py:changed",
            "relation": "calls",
            "path": "consumer.py",
        },
    ]


def test_delta_resolves_same_named_symbols_by_imported_module(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Delta Tester")
    _git(repo, "config", "user.email", "delta@example.test")
    _write(repo, "alpha.py", "def refresh():\n    return 1\n")
    _write(repo, "beta.py", "def refresh():\n    return 1\n")
    _write(
        repo,
        "consumer.py",
        "from alpha import refresh as refresh_alpha\n"
        "from beta import refresh as refresh_beta\n\n"
        "def use_both():\n"
        "    return refresh_alpha() + refresh_beta()\n",
    )
    base = _commit(repo, "base")
    _write(repo, "alpha.py", "def refresh():\n    return 2\n")
    _write(repo, "beta.py", "def refresh():\n    return 3\n")
    head = _commit(repo, "head")

    impact = build_delta(GitDeltaSource(repo), base, head).to_dict()["impact"]

    assert impact == [
        {
            "source": "consumer",
            "target": "alpha.py:refresh",
            "relation": "imports",
            "path": "consumer.py",
        },
        {
            "source": "consumer",
            "target": "beta.py:refresh",
            "relation": "imports",
            "path": "consumer.py",
        },
        {
            "source": "use_both",
            "target": "alpha.py:refresh",
            "relation": "calls",
            "path": "consumer.py",
        },
        {
            "source": "use_both",
            "target": "beta.py:refresh",
            "relation": "calls",
            "path": "consumer.py",
        },
    ]


def test_delta_does_not_link_same_named_symbol_imported_from_wrong_module(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Delta Tester")
    _git(repo, "config", "user.email", "delta@example.test")
    _write(repo, "changed_module.py", "def refresh():\n    return 1\n")
    _write(repo, "unchanged_module.py", "def refresh():\n    return 10\n")
    _write(
        repo,
        "consumer.py",
        "from unchanged_module import refresh\n\n"
        "def use_refresh():\n"
        "    return refresh()\n",
    )
    base = _commit(repo, "base")
    _write(repo, "changed_module.py", "def refresh():\n    return 2\n")
    head = _commit(repo, "head")

    impact = build_delta(GitDeltaSource(repo), base, head).to_dict()["impact"]

    assert impact == []


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


def test_delta_cli_matches_direct_build_for_a_two_commit_repository(delta_history):
    repo, base, head = delta_history

    result = _run_delta_cli(repo, "--base", base, "--head", head)

    assert result.returncode == 0
    assert result.stderr == b""
    assert json.loads(result.stdout) == build_delta(
        GitDeltaSource(repo), base, head
    ).to_dict()


def test_delta_cli_repeats_identical_comparisons_byte_for_byte(delta_history):
    repo, base, head = delta_history

    first = _run_delta_cli(repo, "--base", base, "--head", head)
    second = _run_delta_cli(repo, "--base", base, "--head", head)

    assert first.returncode == second.returncode == 0
    assert first.stderr == second.stderr == b""
    assert first.stdout == second.stdout


def test_delta_cli_invalid_ref_is_structured_without_traceback_or_repo_path(
    delta_history,
):
    repo, _, head = delta_history

    result = _run_delta_cli(repo, "--base", "does-not-exist", "--head", head)

    assert result.returncode == 1
    assert result.stderr == b""
    assert json.loads(result.stdout) == {
        "error": {
            "code": "DELTA_INVALID_REF",
            "message": "Git ref is invalid",
            "details": {},
        }
    }
    assert b"Traceback" not in result.stdout
    assert b"Traceback" not in result.stderr
    assert str(repo).encode("utf-8") not in result.stdout


@pytest.fixture
def impact_history(tmp_path):
    def create(files, changed_path="pkg/service.py"):
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.name", "Delta Tester")
        _git(repo, "config", "user.email", "delta@example.test")
        for path, content in files.items():
            _write(repo, path, content)
        _write(repo, changed_path, "def refresh():\n    return 1\n")
        base = _commit(repo, "base")
        _write(repo, changed_path, "def refresh():\n    return 2\n")
        head = _commit(repo, "head")
        return repo, base, head

    return create


def test_delta_resolves_src_layout_absolute_and_relative_imports(impact_history):
    repo, base, head = impact_history({
        "src/sekr/__init__.py": "from .delta import refresh\n",
        "src/sekr/consumer.py": "from sekr.delta import refresh\n"
        "def use():\n    return refresh()\n",
    }, changed_path="src/sekr/delta.py")

    assert build_delta(GitDeltaSource(repo), base, head).to_dict()["impact"] == [
        {"source": "sekr", "target": "src/sekr/delta.py:refresh",
         "relation": "imports", "path": "src/sekr/__init__.py"},
        {"source": "sekr.consumer", "target": "src/sekr/delta.py:refresh",
         "relation": "imports", "path": "src/sekr/consumer.py"},
        {"source": "use", "target": "src/sekr/delta.py:refresh",
         "relation": "calls", "path": "src/sekr/consumer.py"},
    ]


def test_delta_resolves_unaliased_dotted_import_without_duplicate_module(impact_history):
    repo, base, head = impact_history({
        "consumer.py": "import pkg.service\nimport pkg.service as service\n"
        "def dotted():\n    return pkg.service.refresh()\n"
        "def aliased():\n    return service.refresh()\n"
        "def wrong():\n    return pkg.refresh()\n",
    })

    assert build_delta(GitDeltaSource(repo), base, head).to_dict()["impact"] == [
        {"source": "aliased", "target": "pkg/service.py:refresh",
         "relation": "calls", "path": "consumer.py"},
        {"source": "dotted", "target": "pkg/service.py:refresh",
         "relation": "calls", "path": "consumer.py"},
    ]


@pytest.mark.parametrize("consumer, expected_calls", [
    ("def first():\n    from pkg.service import refresh\n    refresh()\n"
     "def sibling():\n    refresh()\n", ["first"]),
    ("from pkg.service import refresh\n"
     "def first():\n    from other import refresh\n    refresh()\n"
     "def sibling():\n    refresh()\n", ["sibling"]),
    ("from pkg.service import refresh\n"
     "def outer():\n"
     "    def inner():\n        from other import refresh\n        refresh()\n"
     "    refresh()\n", ["outer"]),
    ("from pkg.service import refresh\n"
     "def shadow(refresh, /):\n    refresh()\n"
     "async def keyword(*, refresh):\n    refresh()\n"
     "def variadic(*refresh):\n    refresh()\n"
     "def keywords(**refresh):\n    refresh()\n"
     "def sibling():\n    refresh()\n", ["sibling"]),
    ("from pkg.service import refresh\n"
     "def local():\n    refresh()\n    refresh = replacement\n"
     "def sibling():\n    refresh()\n", ["sibling"]),
    ("from pkg.service import refresh\n"
     "def local():\n    def refresh():\n        pass\n    refresh()\n"
     "def sibling():\n    refresh()\n", ["sibling"]),
    ("from pkg.service import refresh\n"
     "class Consumer:\n    from other import refresh\n"
     "    def method(self):\n        refresh()\n"
     "def sibling():\n    refresh()\n", ["Consumer.method", "sibling"]),
    ("from pkg.service import refresh\n"
     "def outer(refresh):\n    def inner():\n        refresh()\n"
     "def sibling():\n    refresh()\n", ["sibling"]),
    ("from pkg.service import refresh\n"
     "def use():\n    (lambda refresh: refresh())(replacement)\n"
     "    [refresh() for refresh in replacements]\n    refresh()\n", ["use"]),
    ("from pkg.service import refresh\n"
     "def shadow():\n    (lambda refresh: refresh())(replacement)\n"
     "    [refresh() for refresh in replacements]\n", []),
])
def test_delta_uses_lexical_bindings_without_scope_leaks(
    impact_history, consumer, expected_calls,
):
    repo, base, head = impact_history({"consumer.py": consumer})

    impact = build_delta(GitDeltaSource(repo), base, head).to_dict()["impact"]

    assert [edge for edge in impact if edge["relation"] == "calls"] == [
        {"source": caller, "target": "pkg/service.py:refresh",
         "relation": "calls", "path": "consumer.py"}
        for caller in expected_calls
    ]


def test_delta_cli_from_subdirectory_matches_root_bytes(delta_history):
    repo, base, head = delta_history
    # Even a repository configured for relative diffs must report root paths.
    _git(repo, "config", "diff.relative", "true")
    source = GitDeltaSource(repo / "pkg")
    assert source.read_tree(head, "consumer.py").startswith(b"from pkg.service")
    assert source.changed_files(base, head) == {
        "added": ["a_added.txt", "consumer.py"],
        "modified": ["pkg/service.py"],
        "deleted": ["z_deleted.py"],
    }
    root = _run_delta_cli(repo, "--base", base, "--head", head)
    nested = _run_delta_cli(repo / "pkg", "--base", base, "--head", head)

    assert root.returncode == nested.returncode == 0
    assert root.stderr == nested.stderr == b""
    assert root.stdout == nested.stdout
    assert json.loads(nested.stdout)["impact"]


@pytest.mark.parametrize("code, callers", [
    ("def use():\n    refresh()\ndef refresh():\n    pass\n", ["use"]),
    ("from target import refresh\nrefresh = refresh()\nrefresh()\n", ["consumer"]),
    ("from target import refresh\ndef outer(refresh):\n"
     "    def inner():\n        global refresh\n        refresh()\n",
     ["outer.inner"]),
    ("from target import refresh\ndef outer():\n"
     "    from target import refresh\n"
     "    def inner():\n        nonlocal refresh\n        refresh()\n"
     "        refresh = replacement\n"
     "    refresh()\n", ["outer", "outer.inner"]),
    ("from target import refresh\ndef use(value):\n"
     "    match value:\n        case {'callback': refresh}:\n            refresh()\n", []),
    ("from src import refresh\ndef use():\n    refresh()\n", ["use"]),
])
def test_impact_binding_resolution_preserves_lexical_calls(code, callers):
    # Direct AST coverage isolates binding semantics from the Git integration.
    targets = [Symbol("target.py", "refresh", "function", "()"),
               Symbol("src.py", "refresh", "function", "()"),
               Symbol("consumer.py", "refresh", "function", "()")]
    visitor = _ImpactVisitor("consumer.py", targets)
    visitor.visit(ast.parse(code))

    assert sorted(edge.source for edge in visitor.edges if edge.relation == "calls") == callers


def test_impact_resolves_a_closure_call_to_a_later_local_definition():
    visitor = _ImpactVisitor(
        "consumer.py", [Symbol("consumer.py", "outer.refresh", "function", "()")]
    )
    visitor.visit(ast.parse(
        "def outer():\n"
        "    def use():\n        refresh()\n"
        "    def refresh():\n        pass\n"
        "    return use\n"
    ))

    assert [edge.to_dict() for edge in sorted(visitor.edges)] == [
        {"source": "outer.use", "target": "consumer.py:outer.refresh",
         "relation": "calls", "path": "consumer.py"},
    ]


@pytest.mark.parametrize("scope, statement", [
    (scope, statement)
    for scope in ("module", "class", "function")
    for statement in (
    "refresh = refresh()",
    "other = refresh = refresh()",
    "refresh, other = refresh()",
    "refresh: object = refresh()",
    "refresh += refresh()",
    "(refresh := refresh())",
    "for refresh in refresh():\n    refresh()\nelse:\n    refresh()",
    "async for refresh in refresh():\n    refresh()\nelse:\n    refresh()",
    )
    if scope == "function" or not statement.startswith("async ")
])
def test_impact_evaluates_values_before_rebinding(statement, scope):
    body = "from target import refresh\n" + statement + "\n"
    # A separate source makes an accidental post-assignment edge observable.
    body += "def later():\n    refresh()\n"
    if scope == "module":
        code, caller = body, "consumer"
    else:
        prefix = "class Consumer:" if scope == "class" else "async def use():"
        code = prefix + "\n" + "\n".join("    " + line for line in body.splitlines())
        caller = "Consumer" if scope == "class" else "use"
    visitor = _ImpactVisitor(
        "consumer.py", [Symbol("target.py", "refresh", "function", "()")]
    )
    compile(code, "consumer.py", "exec")
    visitor.visit(ast.parse(code))

    assert [edge.to_dict() for edge in sorted(visitor.edges)] == [
        {"source": caller, "target": "target.py:refresh",
         "relation": "calls", "path": "consumer.py"},
        {"source": caller, "target": "target.py:refresh",
         "relation": "imports", "path": "consumer.py"},
    ]


@pytest.mark.parametrize("expression", [
    "[(refresh := replacement) for item in items]",
    "{(refresh := replacement) for item in items}",
    "{item: (refresh := replacement) for item in items}",
    "{(refresh := replacement): item for item in items}",
    "((refresh := replacement) for item in items)",
    "[item for item in items if (refresh := replacement)]",
    "[[(refresh := replacement) for inner in item] for item in items]",
])
@pytest.mark.parametrize("local_import", [False, True])
def test_impact_comprehension_walrus_shadows_enclosing_function(expression, local_import):
    code = "from target import refresh\ndef use():\n"
    if local_import:
        code += "    from target import refresh\n"
    code += f"    {expression}\n    refresh()\n"
    code += "def sibling():\n    refresh()\n"
    visitor = _ImpactVisitor(
        "consumer.py", [Symbol("target.py", "refresh", "function", "()")]
    )
    visitor.visit(ast.parse(code))

    assert [edge.to_dict() for edge in sorted(visitor.edges) if edge.relation == "calls"] == [
        {"source": "sibling", "target": "target.py:refresh",
         "relation": "calls", "path": "consumer.py"},
    ]


@pytest.mark.parametrize("expression, callers", [
    ("[(refresh := replacement) for item in items]", []),
    ("[(lambda: (refresh := replacement)) for item in items]", ["use"]),
    ("[refresh for refresh in items]", ["use"]),
])
def test_impact_comprehension_walrus_has_lexical_scope(expression, callers):
    visitor = _ImpactVisitor(
        "consumer.py", [Symbol("target.py", "refresh", "function", "()")]
    )
    visitor.visit(ast.parse(
        "from target import refresh\ndef use():\n"
        f"    refresh()\n    {expression}\n"
    ))

    assert sorted(edge.source for edge in visitor.edges if edge.relation == "calls") == callers


@pytest.mark.parametrize("decorator, parameters, receiver, resolves", [
    ("", "self", "self", True),
    ("", "self, /, value=None", "self", True),
    ("@classmethod", "cls", "cls", True),
    ("@classmethod", "cls, /, value=None", "cls", True),
    ("@builtins.classmethod", "cls", "cls", True),
    ("@staticmethod", "self", "self", False),
    ("@staticmethod", "cls", "cls", False),
    ("@builtins.staticmethod", "self", "self", False),
    ("", "other, self", "self", False),
    ("", "self, cls", "cls", False),
    ("", "other, /, self", "self", False),
    ("", "*, self", "self", False),
    ("", "*self", "self", False),
    ("", "**cls", "cls", False),
    ("", "cls", "cls", False),
    ("@classmethod", "self", "self", False),
    ("@classmethod", "other, cls", "cls", False),
    ("@classmethod", "*, cls", "cls", False),
])
@pytest.mark.parametrize("definition", ["def", "async def"])
def test_impact_only_infers_conventional_method_receivers(
    decorator, parameters, receiver, resolves, definition,
):
    code = "class Consumer:\n"
    if decorator:
        code += f"    {decorator}\n"
    code += f"    {definition} use({parameters}):\n        {receiver}.refresh()\n"
    visitor = _ImpactVisitor(
        "consumer.py", [Symbol("consumer.py", "Consumer.refresh", "function", "()")]
    )
    visitor.visit(ast.parse(code))

    assert [edge.to_dict() for edge in sorted(visitor.edges)] == ([
        {"source": "Consumer.use", "target": "consumer.py:Consumer.refresh",
         "relation": "calls", "path": "consumer.py"},
    ] if resolves else [])


def test_impact_does_not_infer_receivers_from_method_locals_or_nested_parameters():
    visitor = _ImpactVisitor(
        "consumer.py", [Symbol("consumer.py", "Consumer.refresh", "function", "()")]
    )
    visitor.visit(ast.parse(
        "class Consumer:\n"
        "    def use(other):\n"
        "        self.refresh()\n        self = other\n"
        "        cls.refresh()\n        cls = other\n"
        "    def method(self):\n"
        "        def nested(self):\n            self.refresh()\n"
    ))

    assert visitor.edges == set()


@pytest.mark.parametrize("code, callers", [
    ("from target import refresh\nrefresh: object\nrefresh()\n", ["consumer"]),
    ("def use():\n    from target import refresh\n"
     "    refresh: object\n    refresh()\n", ["use"]),
    ("from target import refresh\ndef use():\n"
     "    refresh: object\n    refresh()\n", []),
    ("from target import refresh\n"
     "[(refresh := replacement) for item in items]\n"
     "def later():\n    refresh()\n", []),
    ("from target import refresh\ndef use():\n    global refresh\n"
     "    [(refresh := replacement) for item in items]\n    refresh()\n"
     "def sibling():\n    refresh()\n", ["sibling"]),
    ("def outer():\n    from target import refresh\n"
     "    def use():\n        nonlocal refresh\n"
     "        [(refresh := replacement) for item in items]\n        refresh()\n"
     "    refresh()\n", ["outer"]),
    ("from target import refresh\ndef use():\n"
     "    return lambda: ([(refresh := replacement) for item in items], refresh())\n"
     "def sibling():\n    refresh()\n", ["sibling"]),
])
def test_impact_binding_updates_preserve_annotation_and_walrus_boundaries(code, callers):
    visitor = _ImpactVisitor(
        "consumer.py", [Symbol("target.py", "refresh", "function", "()")]
    )
    visitor.visit(ast.parse(code))

    assert sorted(edge.source for edge in visitor.edges if edge.relation == "calls") == callers
