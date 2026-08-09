import pytest

from app.security.path_guard import PathAccessError, PathGuard


def test_resolve_allows_path_inside_allowed_root(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "file.txt"
    target.write_text("hello")

    guard = PathGuard(allowed_roots=[allowed])
    resolved = guard.resolve(str(target))

    assert resolved == target.resolve()


def test_resolve_denies_path_outside_allowed_root(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "file.txt"
    target.write_text("hello")

    guard = PathGuard(allowed_roots=[allowed])

    with pytest.raises(PathAccessError):
        guard.resolve(str(target))


def test_resolve_denies_path_traversal_escape(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")

    guard = PathGuard(allowed_roots=[allowed])
    traversal_path = str(allowed / ".." / "outside" / "secret.txt")

    with pytest.raises(PathAccessError):
        guard.resolve(traversal_path)


def test_resolve_with_no_allowed_roots_denies_everything(tmp_path):
    guard = PathGuard(allowed_roots=[])
    with pytest.raises(PathAccessError) as exc_info:
        guard.resolve(str(tmp_path))
    assert "No allowed directories" in str(exc_info.value)


def test_resolve_must_exist_by_default(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    guard = PathGuard(allowed_roots=[allowed])

    with pytest.raises(PathAccessError):
        guard.resolve(str(allowed / "does_not_exist.txt"))


def test_resolve_can_allow_nonexistent_path(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    guard = PathGuard(allowed_roots=[allowed])

    # should not raise, even though the file doesn't exist yet
    resolved = guard.resolve(str(allowed / "new_file.txt"), must_exist=False)
    assert resolved.parent == allowed.resolve()


def test_check_readable_size_rejects_oversized_file(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    big_file = allowed / "big.txt"
    big_file.write_bytes(b"x" * 100)

    guard = PathGuard(allowed_roots=[allowed])

    import app.security.path_guard as path_guard_module

    original_limit = path_guard_module.MAX_READABLE_FILE_BYTES
    path_guard_module.MAX_READABLE_FILE_BYTES = 50
    try:
        with pytest.raises(PathAccessError):
            guard.check_readable_size(big_file)
    finally:
        path_guard_module.MAX_READABLE_FILE_BYTES = original_limit


def test_multiple_allowed_roots(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    (root_a / "file_a.txt").write_text("a")
    (root_b / "file_b.txt").write_text("b")

    guard = PathGuard(allowed_roots=[root_a, root_b])

    assert guard.resolve(str(root_a / "file_a.txt"))
    assert guard.resolve(str(root_b / "file_b.txt"))
