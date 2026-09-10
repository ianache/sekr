"""Safe, deterministic readers for Git trees used by knowledge deltas."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path, PurePosixPath
import re
import subprocess

from sekr.errors import StructuredError


_OBJECT_ID = re.compile(r"^[0-9a-f]{40,64}$")


class GitDeltaSource:
    """Read Git history without executing repository content or shell commands."""

    def __init__(self, repo: Path) -> None:
        self.repo = Path(repo)

    def validate_ref(self, ref: str) -> None:
        """Raise a stable error unless *ref* names a commit in this repository."""
        self._resolve_ref(ref)

    def changed_files(self, base: str, head: str) -> dict[str, list[str]]:
        """Return sorted repository-relative paths grouped by Git change status."""
        base_id = self._resolve_ref(base)
        head_id = self._resolve_ref(head)
        output = self._run(
            [
                "git",
                "diff",
                "--name-status",
                "-z",
                "--no-renames",
                base_id,
                head_id,
                "--",
            ],
            "DELTA_TREE_ERROR",
            "Git tree could not be read",
        )
        fields = output.split(b"\0")
        if fields[-1:] != [b""]:
            raise self._tree_error()
        fields.pop()
        if len(fields) % 2:
            raise self._tree_error()

        changes = {"added": [], "modified": [], "deleted": []}
        statuses = {"A": "added", "M": "modified", "T": "modified", "D": "deleted"}
        for status_raw, path_raw in zip(fields[::2], fields[1::2], strict=True):
            status = self._decode(status_raw, "DELTA_TREE_ERROR", "Git status was malformed")
            category = statuses.get(status)
            if category is None:
                raise self._tree_error()
            changes[category].append(self._safe_path(path_raw))
        return {category: sorted(paths) for category, paths in changes.items()}

    def read_tree(self, ref: str, path: str) -> bytes:
        """Read one repository-relative blob from *ref*."""
        object_id = self._resolve_ref(ref)
        safe_path = self._validate_path(path)
        return self._run(
            ["git", "cat-file", "blob", f"{object_id}:{safe_path}"],
            "DELTA_TREE_ERROR",
            "Git tree could not be read",
        )

    def commits_between(self, base: str, head: str) -> list[dict[str, str]]:
        """Return deterministic commit metadata reachable from head but not base."""
        base_id = self._resolve_ref(base)
        head_id = self._resolve_ref(head)
        output = self._run(
            [
                "git",
                "log",
                "-z",
                "--format=%H%x00%an%x00%s%x00%aI",
                "--reverse",
                f"{base_id}..{head_id}",
            ],
            "DELTA_TREE_ERROR",
            "Git commit metadata could not be read",
        )
        if not output:
            return []
        fields = output.split(b"\0")
        if fields[-1:] != [b""]:
            raise self._metadata_error()
        fields.pop()
        if len(fields) % 4:
            raise self._metadata_error()

        commits: list[dict[str, str]] = []
        for record in zip(fields[::4], fields[1::4], fields[2::4], fields[3::4], strict=True):
            commit_id, author, subject, timestamp = (
                self._decode(field, "DELTA_TREE_ERROR", "Git commit metadata was malformed")
                for field in record
            )
            if not _OBJECT_ID.fullmatch(commit_id) or not author or not timestamp:
                raise self._metadata_error()
            try:
                datetime.fromisoformat(timestamp)
            except ValueError as error:
                raise self._metadata_error() from error
            commits.append(
                {
                    "id": commit_id,
                    "author": author,
                    "subject": subject,
                    "timestamp": timestamp,
                }
            )
        return sorted(commits, key=lambda record: (record["timestamp"], record["id"]))

    def _resolve_ref(self, ref: str) -> str:
        self._ensure_repository()
        if not isinstance(ref, str) or not ref or "\0" in ref:
            raise StructuredError("DELTA_INVALID_REF", "Git ref is invalid")
        output = self._run(
            ["git", "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}"],
            "DELTA_INVALID_REF",
            "Git ref is invalid",
        )
        try:
            object_id = output.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise StructuredError("DELTA_INVALID_REF", "Git ref is invalid") from error
        if not _OBJECT_ID.fullmatch(object_id):
            raise StructuredError("DELTA_INVALID_REF", "Git ref is invalid")
        return object_id

    def _ensure_repository(self) -> None:
        output = self._run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            "DELTA_NOT_REPOSITORY",
            "Path is not a Git repository",
        )
        if output != b"true\n":
            raise StructuredError("DELTA_NOT_REPOSITORY", "Path is not a Git repository")

    def _run(self, args: list[str], code: str, message: str) -> bytes:
        try:
            completed = subprocess.run(
                args,
                cwd=self.repo,
                check=False,
                capture_output=True,
                shell=False,
            )
        except OSError as error:
            raise StructuredError(code, message) from error
        if completed.returncode != 0:
            raise StructuredError(code, message)
        return completed.stdout

    def _safe_path(self, raw_path: bytes) -> str:
        return self._validate_path(
            self._decode(raw_path, "DELTA_TREE_ERROR", "Git tree path was malformed")
        )

    @staticmethod
    def _validate_path(path: str) -> str:
        if not isinstance(path, str) or not path or "\0" in path or "\\" in path:
            raise StructuredError("DELTA_TREE_ERROR", "Git tree path is unsafe")
        parsed = PurePosixPath(path)
        normalized = parsed.as_posix()
        if parsed.is_absolute() or ".." in parsed.parts or normalized != path:
            raise StructuredError("DELTA_TREE_ERROR", "Git tree path is unsafe")
        return normalized

    @staticmethod
    def _decode(raw: bytes, code: str, message: str) -> str:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise StructuredError(code, message) from error

    @staticmethod
    def _tree_error() -> StructuredError:
        return StructuredError("DELTA_TREE_ERROR", "Git tree status was malformed")

    @staticmethod
    def _metadata_error() -> StructuredError:
        return StructuredError("DELTA_TREE_ERROR", "Git commit metadata was malformed")
