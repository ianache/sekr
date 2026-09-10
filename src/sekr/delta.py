"""Deterministic knowledge deltas for two Git trees."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, Sequence

from sekr.errors import StructuredError
from sekr.git_delta import GitDeltaSource


@dataclass(frozen=True, order=True)
class Symbol:
    path: str
    qualified_name: str
    kind: str
    signature: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "qualified_name": self.qualified_name,
            "kind": self.kind,
            "signature": self.signature,
        }


@dataclass(frozen=True, order=True)
class Impact:
    source: str
    target: str
    relation: str
    path: str

    def to_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "path": self.path,
        }


@dataclass(frozen=True)
class FileChanges:
    added: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "added": list(self.added),
            "modified": list(self.modified),
            "deleted": list(self.deleted),
        }


@dataclass(frozen=True)
class SymbolChanges:
    added: tuple[Symbol, ...] = ()
    modified: tuple[Symbol, ...] = ()
    deleted: tuple[Symbol, ...] = ()

    def to_dict(self) -> dict[str, list[dict[str, str]]]:
        return {
            "added": [symbol.to_dict() for symbol in self.added],
            "modified": [symbol.to_dict() for symbol in self.modified],
            "deleted": [symbol.to_dict() for symbol in self.deleted],
        }


@dataclass(frozen=True)
class Commit:
    id: str
    author: str
    subject: str
    timestamp: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "author": self.author,
            "subject": self.subject,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class KnowledgeDelta:
    base: str
    head: str
    files: FileChanges
    symbols: SymbolChanges
    impact: tuple[Impact, ...]
    commits: tuple[Commit, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical JSON-compatible delta contract."""
        return {
            "base": self.base,
            "head": self.head,
            "files": self.files.to_dict(),
            "symbols": self.symbols.to_dict(),
            "impact": [record.to_dict() for record in self.impact],
            "commits": [commit.to_dict() for commit in self.commits],
        }


@dataclass(frozen=True)
class _ExtractedSymbol:
    symbol: Symbol
    fingerprint: str


class _SymbolVisitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.names: list[str] = []
        self.symbols: list[_ExtractedSymbol] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._record(node, "class", _class_signature(node))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record(node, "function", _function_signature(node))

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record(node, "async_function", _function_signature(node))

    def _record(
        self,
        node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
        kind: str,
        signature: str,
    ) -> None:
        self.names.append(node.name)
        self.symbols.append(
            _ExtractedSymbol(
                Symbol(self.path, ".".join(self.names), kind, signature),
                ast.dump(node, annotate_fields=True, include_attributes=False),
            )
        )
        self.generic_visit(node)
        self.names.pop()


class _ImpactVisitor(ast.NodeVisitor):
    def __init__(self, path: str, targets: Sequence[Symbol]) -> None:
        self.path = path
        self.module = _module_name(path)
        self.names: list[str] = []
        self.aliases: dict[str, str] = {}
        self.targets = tuple(target.qualified_name for target in targets)
        self.edges: set[Impact] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scope(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scope(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            local_name = alias.asname or alias.name
            self.aliases[local_name] = alias.name
            target = self._resolve_target(alias.name)
            if target is not None:
                self._add(target, "imports")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".", 1)[0]
            self.aliases[local_name] = alias.name

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name:
            first, separator, remainder = name.partition(".")
            expanded = self.aliases.get(first, first)
            if separator:
                expanded = f"{expanded}.{remainder}"
            target = self._resolve_target(expanded)
            if target is not None:
                self._add(target, "calls")
        self.generic_visit(node)

    def _visit_scope(
        self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        self.names.append(node.name)
        self.generic_visit(node)
        self.names.pop()

    def _resolve_target(self, candidate: str) -> str | None:
        exact = [target for target in self.targets if target == candidate]
        if exact:
            return exact[0]
        suffix = [
            target
            for target in self.targets
            if candidate.endswith(f".{target}")
            or target.endswith(f".{candidate}")
            or target.rsplit(".", 1)[-1] == candidate.rsplit(".", 1)[-1]
        ]
        return suffix[0] if len(suffix) == 1 else None

    def _add(self, target: str, relation: str) -> None:
        self.edges.add(
            Impact(
                source=".".join(self.names) if self.names else self.module,
                target=target,
                relation=relation,
                path=self.path,
            )
        )


def build_delta(source: GitDeltaSource, base: str, head: str) -> KnowledgeDelta:
    """Build an immutable, deterministic delta between two Git refs."""
    changed = source.changed_files(base, head)
    files = FileChanges(
        added=tuple(sorted(changed["added"])),
        modified=tuple(sorted(changed["modified"])),
        deleted=tuple(sorted(changed["deleted"])),
    )

    base_symbols = _symbols_for_tree(
        source, base, (*files.modified, *files.deleted)
    )
    head_symbols = _symbols_for_tree(source, head, (*files.added, *files.modified))
    symbol_changes = _compare_symbols(base_symbols, head_symbols)
    changed_targets = (*symbol_changes.added, *symbol_changes.modified)

    impacts: set[Impact] = set()
    if changed_targets:
        for path in _head_python_paths(source, head):
            tree = _parse_python(source.read_tree(head, path), path)
            visitor = _ImpactVisitor(path, changed_targets)
            visitor.visit(tree)
            impacts.update(visitor.edges)

    commits = tuple(
        Commit(
            id=record["id"],
            author=record["author"],
            subject=record["subject"],
            timestamp=record["timestamp"],
        )
        for record in source.commits_between(base, head)
    )
    return KnowledgeDelta(
        base=base,
        head=head,
        files=files,
        symbols=symbol_changes,
        impact=tuple(sorted(impacts)),
        commits=commits,
    )


def _symbols_for_tree(
    source: GitDeltaSource, ref: str, paths: Iterable[str]
) -> dict[str, _ExtractedSymbol]:
    symbols: dict[str, _ExtractedSymbol] = {}
    for path in sorted(path for path in paths if path.endswith(".py")):
        tree = _parse_python(source.read_tree(ref, path), path)
        visitor = _SymbolVisitor(path)
        visitor.visit(tree)
        for extracted in visitor.symbols:
            identity = f"{path}:{extracted.symbol.qualified_name}"
            symbols[identity] = extracted
    return symbols


def _compare_symbols(
    base: dict[str, _ExtractedSymbol], head: dict[str, _ExtractedSymbol]
) -> SymbolChanges:
    base_ids = set(base)
    head_ids = set(head)
    return SymbolChanges(
        added=tuple(sorted(head[identity].symbol for identity in head_ids - base_ids)),
        modified=tuple(
            sorted(
                head[identity].symbol
                for identity in base_ids & head_ids
                if base[identity].fingerprint != head[identity].fingerprint
            )
        ),
        deleted=tuple(sorted(base[identity].symbol for identity in base_ids - head_ids)),
    )


def _parse_python(content: bytes, path: str) -> ast.Module:
    try:
        return ast.parse(content, filename=path)
    except (SyntaxError, UnicodeError, ValueError) as error:
        raise StructuredError(
            "DELTA_PARSE_ERROR", f"Python source could not be parsed: {path}"
        ) from error


def _head_python_paths(source: GitDeltaSource, head: str) -> tuple[str, ...]:
    object_id = source._resolve_ref(head)
    output = source._run(
        ["git", "ls-tree", "-r", "-z", "--name-only", object_id, "--"],
        "DELTA_TREE_ERROR",
        "Git tree could not be read",
    )
    fields = output.split(b"\0")
    if fields[-1:] != [b""]:
        raise StructuredError("DELTA_TREE_ERROR", "Git tree paths were malformed")
    return tuple(
        sorted(
            source._safe_path(raw_path)
            for raw_path in fields[:-1]
            if raw_path.endswith(b".py")
        )
    )


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    signature = f"({ast.unparse(node.args)})"
    if node.returns is not None:
        signature += f" -> {ast.unparse(node.returns)}"
    return signature


def _class_signature(node: ast.ClassDef) -> str:
    arguments = [ast.unparse(base) for base in node.bases]
    arguments.extend(
        f"{keyword.arg}={ast.unparse(keyword.value)}"
        if keyword.arg is not None
        else f"**{ast.unparse(keyword.value)}"
        for keyword in node.keywords
    )
    return f"({', '.join(arguments)})" if arguments else ""


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    return None


def _module_name(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts[-1:] == ["__init__"]:
        parts.pop()
    return ".".join(parts)
