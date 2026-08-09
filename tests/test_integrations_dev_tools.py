import subprocess

import pytest

from app.integrations.dev_tools_service import DevToolsService
from app.security.path_guard import PathGuard


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    (repo / "file.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)
    return repo


def _service(tmp_path):
    return DevToolsService(path_guard=PathGuard(allowed_roots=[tmp_path]))


@pytest.mark.asyncio
async def test_git_status_on_clean_repo(tmp_path):
    repo = _init_repo(tmp_path)
    service = _service(tmp_path)

    result = await service.git_status(str(repo))

    assert result.success is True
    assert "clean" in result.output.lower() or result.output.strip() != ""


@pytest.mark.asyncio
async def test_git_status_shows_modified_file(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.txt").write_text("changed content")

    service = _service(tmp_path)
    result = await service.git_status(str(repo))

    assert result.success is True
    assert "file.txt" in result.output


@pytest.mark.asyncio
async def test_git_diff_shows_changes(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "file.txt").write_text("modified line")

    service = _service(tmp_path)
    result = await service.git_diff(str(repo))

    assert result.success is True
    assert "modified line" in result.output


@pytest.mark.asyncio
async def test_git_diff_empty_when_no_changes(tmp_path):
    repo = _init_repo(tmp_path)
    service = _service(tmp_path)

    result = await service.git_diff(str(repo))

    assert result.success is True
    assert result.output.strip() == ""


@pytest.mark.asyncio
async def test_git_operations_denied_outside_allowed_root(tmp_path):
    repo = _init_repo(tmp_path)
    other_root = tmp_path.parent / "not_allowed_root_xyz"
    other_root.mkdir(exist_ok=True)
    try:
        service = DevToolsService(path_guard=PathGuard(allowed_roots=[other_root]))
        result = await service.git_status(str(repo))
        assert result.success is False
    finally:
        import shutil

        shutil.rmtree(other_root, ignore_errors=True)


@pytest.mark.asyncio
async def test_rejects_non_git_directory(tmp_path):
    not_a_repo = tmp_path / "plain_folder"
    not_a_repo.mkdir()

    service = _service(tmp_path)
    result = await service.git_status(str(not_a_repo))

    assert result.success is False
    assert "not a git repository" in result.error


@pytest.mark.asyncio
async def test_run_tests_executes_configured_command(tmp_path):
    repo = _init_repo(tmp_path)
    service = _service(tmp_path)

    # A trivial "test command" that just proves the subprocess pipeline
    # works end to end, without depending on pytest being importable in
    # a fresh subprocess environment.
    import sys

    result = await service.run_tests(
        str(repo), test_command=[sys.executable, "-c", "print('tests passed')"]
    )

    assert result.success is True
    assert "tests passed" in result.output


@pytest.mark.asyncio
async def test_run_tests_no_command_configured(tmp_path):
    repo = _init_repo(tmp_path)
    service = _service(tmp_path)

    result = await service.run_tests(str(repo), test_command=[])

    assert result.success is False
    assert "No test command configured" in result.error


def test_no_push_pull_merge_methods_exist(tmp_path):
    """Explicit safety assertion: this service must never grow methods
    for remote-touching git operations, per the design doc's prohibition.
    A future accidental addition should make this test fail loudly."""
    service = _service(tmp_path)
    forbidden = {"push", "pull", "merge", "force_push", "delete_branch", "publish"}
    actual_methods = {name for name in dir(service) if not name.startswith("_")}
    assert forbidden.isdisjoint(actual_methods)
