"""
PathGuard — the filesystem equivalent of the permission-level system.

Every file/folder operation must resolve its target path through this
before touching disk. It enforces that the resolved, real path (symlinks
followed, `..` collapsed) lands inside one of the configured allowed
roots — this is what "restricted directories rather than unrestricted
filesystem access" from the design doc actually means in code, not just
in a config file nobody checks.
"""

from __future__ import annotations

from pathlib import Path

MAX_READABLE_FILE_BYTES = 10 * 1024 * 1024  # 10MB — plenty for text/PDF/DOCX, guards against accidents


class PathAccessError(Exception):
    """Raised when a requested path falls outside every allowed root, or
    otherwise fails validation (doesn't exist when it must, too large to
    read, etc.)."""


class PathGuard:
    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = [root.resolve() for root in allowed_roots]

    @property
    def allowed_roots(self) -> list[Path]:
        return list(self._allowed_roots)

    def resolve(self, path: str | Path, must_exist: bool = True) -> Path:
        """Resolve `path` (absolute or relative) and verify it's inside an
        allowed root. Raises PathAccessError otherwise — callers should
        treat this as a normal, expected failure mode (convert to a
        ToolResult), not a crash.
        """
        if not self._allowed_roots:
            raise PathAccessError(
                "No allowed directories are configured — file access is disabled "
                "until ALLOWED_DIRECTORIES is set."
            )

        candidate = Path(path)
        try:
            resolved = candidate.resolve()
        except OSError as exc:
            raise PathAccessError(f"Could not resolve path '{path}': {exc}") from exc

        if must_exist and not resolved.exists():
            raise PathAccessError(f"Path does not exist: {resolved}")

        for root in self._allowed_roots:
            try:
                resolved.relative_to(root)
                return resolved
            except ValueError:
                continue

        raise PathAccessError(
            f"'{resolved}' is outside all allowed directories. "
            f"Allowed: {[str(r) for r in self._allowed_roots]}"
        )

    def check_readable_size(self, path: Path) -> None:
        size = path.stat().st_size
        if size > MAX_READABLE_FILE_BYTES:
            raise PathAccessError(
                f"'{path}' is {size} bytes, larger than the {MAX_READABLE_FILE_BYTES}-byte "
                "limit for reading."
            )
