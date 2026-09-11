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


class _LocalBindings(ast.NodeVisitor):
    """Collect lexical locals without descending into child scopes."""

    def __init__(self) -> None:
        self.names: set[str] = set()
        self.definitions: set[str] = set()
        self.globals: set[str] = set()
        self.nonlocals: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_arg(self, node: ast.arg) -> None:
        self.names.add(node.arg)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)
        self.definitions.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(alias.asname or alias.name for alias in node.names)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.globals.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.nonlocals.update(node.names)

    def visit_MatchAs(self, node: ast.MatchAs | ast.MatchStar) -> None:
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    visit_MatchStar = visit_MatchAs

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest:
            self.names.add(node.rest)
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    def visit_ListComp(
        self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
    ) -> None:
        # Iteration targets stay in the comprehension, but walrus targets in
        # its expressions bind in the enclosing scope (even when nested).
        for generator in node.generators:
            self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp


class _ImpactVisitor(ast.NodeVisitor):
    def __init__(self, path: str, targets: Sequence[Symbol]) -> None:
        self.path = path
        self.module = _module_name(path)
        self.names: list[str] = []
        # None marks a binding whose value is unknown, blocking outer aliases.
        self.scopes: list[tuple[str, dict[str, str | None]]] = [("module", {})]
        self._deferred_generator_depth = 0
        self.targets: dict[str, list[str]] = {}
        for target in targets:
            qualified_target = f"{_module_name(target.path)}.{target.qualified_name}"
            identity = f"{target.path}:{target.qualified_name}"
            self.targets.setdefault(qualified_target, []).append(identity)
        self.edges: set[Impact] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scope(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scope(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        imported_module = _resolve_import_module(self.path, self.module, node)
        for alias in node.names:
            local_name = alias.asname or alias.name
            imported_name = ".".join(
                part for part in (imported_module, alias.name) if part
            )
            self.scopes[-1][1][local_name] = imported_name
            target = self._resolve_target(imported_name)
            if target is not None:
                self._add(target, "imports")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".", 1)[0]
            self.scopes[-1][1][local_name] = alias.name if alias.asname else local_name

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.scopes[-1][1][node.id] = None

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self.visit(target)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
            self.visit(node.target)
        elif not isinstance(node.target, ast.Name):
            self.visit(node.target)
        self.visit(node.annotation)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        # Attribute/subscript targets are evaluated before the RHS; a name
        # retains its previous binding until the updated value is stored.
        if not isinstance(node.target, ast.Name):
            self.visit(node.target)
        self.visit(node.value)
        if isinstance(node.target, ast.Name):
            self.visit(node.target)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        # A walrus escapes all enclosing comprehension scopes, but stops at
        # a real function/lambda or module. Function scopes are analysis-local
        # snapshots, preserving global/nonlocal isolation from sibling bodies.
        if not self._deferred_generator_depth:
            for kind, bindings in reversed(self.scopes):
                if kind != "comprehension":
                    bindings[node.target.id] = None
                    break

    def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        self.visit(node.target)
        for statement in (*node.body, *node.orelse):
            self.visit(statement)

    visit_AsyncFor = visit_For

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name:
            target = self._resolve_call_target(name)
            if target is not None:
                self._add(target, "calls")
        self.generic_visit(node)

    def _visit_scope(
        self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        # Defaults, decorators and bases are evaluated in the enclosing scope.
        for decorator in node.decorator_list:
            self.visit(decorator)
        is_class = isinstance(node, ast.ClassDef)
        if is_class:
            for value in [*node.bases, *node.keywords]:
                self.visit(value)
        else:
            self.visit(node.args)
            if node.returns is not None:
                self.visit(node.returns)

        self.scopes[-1][1][node.name] = ".".join((self.module, *self.names, node.name))
        enclosing = self.scopes
        bindings: dict[str, str | None] = {}
        if not is_class:
            locals_ = _LocalBindings()
            locals_.visit(node.args)
            for statement in node.body:
                locals_.visit(statement)
            bindings = dict.fromkeys(locals_.names)
            for name in locals_.definitions:
                bindings[name] = ".".join((self.module, *self.names, node.name, name))
            # Analyze rebinding within this body without executing its effects
            # in enclosing scopes when the visitor returns to a sibling.
            for name in locals_.globals:
                bindings[name] = enclosing[0][1].get(name)
            for name in locals_.nonlocals:
                bindings[name] = next(
                    (scope[name] for kind, scope in reversed(enclosing)
                     if kind == "function" and name in scope),
                    None,
                )
            if enclosing[-1][0] == "class":
                decorators = {
                    self._resolve_decorator_name(item) for item in node.decorator_list
                }
                positional = [*node.args.posonlyargs, *node.args.args]
                receiver = (
                    "cls" if "builtins.classmethod" in decorators
                    else "self"
                )
                if (
                    "builtins.staticmethod" not in decorators
                    and positional and positional[0].arg == receiver
                ):
                    bindings[receiver] = ".".join((self.module, *self.names))
        # Class namespaces are not enclosing lexical scopes for child bodies.
        self.scopes = [scope for scope in enclosing if scope[0] != "class"]
        self.scopes.append(("class" if is_class else "function", bindings))
        self.names.append(node.name)
        try:
            for statement in node.body:
                self.visit(statement)
        finally:
            self.names.pop()
            self.scopes = enclosing

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.visit(node.args)
        locals_ = _LocalBindings()
        locals_.visit(node.args)
        locals_.visit(node.body)
        enclosing = self.scopes
        self.scopes = [scope for scope in enclosing if scope[0] != "class"]
        self.scopes.append(("function", dict.fromkeys(locals_.names)))
        try:
            self.visit(node.body)
        finally:
            self.scopes = enclosing

    def visit_ListComp(
        self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
    ) -> None:
        self.visit(node.generators[0].iter)
        enclosing = self.scopes
        locals_ = _LocalBindings()
        for generator in node.generators:
            locals_.visit(generator.target)
        self.scopes = [scope for scope in enclosing if scope[0] != "class"]
        self.scopes.append(("comprehension", dict.fromkeys(locals_.names)))
        if isinstance(node, ast.GeneratorExp):
            self._deferred_generator_depth += 1
        try:
            for index, generator in enumerate(node.generators):
                if index:
                    self.visit(generator.iter)
                for condition in generator.ifs:
                    self.visit(condition)
            if isinstance(node, ast.DictComp):
                self.visit(node.key)
                self.visit(node.value)
            else:
                self.visit(node.elt)
        finally:
            if isinstance(node, ast.GeneratorExp):
                self._deferred_generator_depth -= 1
            self.scopes = enclosing

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def _resolve_target(self, candidate: str) -> str | None:
        matches = self.targets.get(candidate, ())
        return matches[0] if len(matches) == 1 else None

    def _resolve_call_target(self, name: str) -> str | None:
        candidate = self._resolve_binding(name)
        return self._resolve_target(candidate) if candidate is not None else None

    def _resolve_binding(self, name: str) -> str | None:
        first, separator, remainder = name.partition(".")
        for _, bindings in reversed(self.scopes):
            if first in bindings:
                bound = bindings[first]
                if bound is None:
                    return None
                return f"{bound}.{remainder}" if separator else bound
        # Module functions may refer to definitions later in the same file.
        return f"{self.module}.{name}"

    def _resolve_decorator_name(self, node: ast.expr) -> str | None:
        name = _call_name(node)
        if name is None:
            return None
        if name in {"classmethod", "builtins.classmethod"}:
            return "builtins.classmethod"
        if name in {"staticmethod", "builtins.staticmethod"}:
            return "builtins.staticmethod"
        return self._resolve_binding(name)

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
        ["git", "ls-tree", "--full-tree", "-r", "-z", "--name-only", object_id, "--"],
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
    # The conventional src layout puts importable modules below the source root.
    if len(parts) > 1 and parts[0] == "src":
        parts.pop(0)
    if parts[-1:] == ["__init__"]:
        parts.pop()
    return ".".join(parts)


def _resolve_import_module(
    path: str, current_module: str, node: ast.ImportFrom
) -> str:
    if node.level == 0:
        return node.module or ""

    package_parts = current_module.split(".")
    if PurePosixPath(path).name != "__init__.py":
        package_parts.pop()
    parent_count = node.level - 1
    if parent_count:
        package_parts = package_parts[:-parent_count]
    if node.module:
        package_parts.extend(node.module.split("."))
    return ".".join(package_parts)
