import pytest

from app.memory.models import MemoryType
from app.memory.repository import MemoryRepository
from app.tools.memory_tools import ForgetTool, RecallTool, RememberTool


@pytest.mark.asyncio
async def test_remember_tool_stores_permanent_memory(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    tool = RememberTool(repository=repo)

    result = await tool.execute(content="prefers morning meetings", type="profile", permanent=True)

    assert result.success is True
    assert result.metadata["permanent"] is True

    stored = repo.retrieve(type=MemoryType.PROFILE)
    assert len(stored) == 1
    assert stored[0].is_permanent is True


@pytest.mark.asyncio
async def test_remember_tool_stores_auto_expiring_memory(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    tool = RememberTool(repository=repo)

    result = await tool.execute(content="worked on report today", type="episodic", permanent=False)

    assert result.success is True
    assert result.metadata["permanent"] is False


@pytest.mark.asyncio
async def test_remember_tool_rejects_invalid_type(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    tool = RememberTool(repository=repo)

    result = await tool.execute(content="x", type="not_a_real_type", permanent=True)
    assert result.success is False
    assert "Invalid memory type" in result.error


@pytest.mark.asyncio
async def test_recall_tool_returns_matches(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    repo.remember("prefers dark mode", MemoryType.PROFILE, permanent=True)
    tool = RecallTool(repository=repo)

    result = await tool.execute(query="dark mode")

    assert result.success is True
    assert len(result.result) == 1


@pytest.mark.asyncio
async def test_forget_tool_by_id(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    memory = repo.remember("delete me", MemoryType.PROFILE, permanent=True)
    tool = ForgetTool(repository=repo)

    result = await tool.execute(memory_id=memory.id)

    assert result.success is True
    assert repo.retrieve(type=MemoryType.PROFILE) == []


@pytest.mark.asyncio
async def test_forget_tool_by_unique_query(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    repo.remember("prefers dark mode", MemoryType.PROFILE, permanent=True)
    tool = ForgetTool(repository=repo)

    result = await tool.execute(query="dark mode")

    assert result.success is True
    assert repo.retrieve(type=MemoryType.PROFILE) == []


@pytest.mark.asyncio
async def test_forget_tool_ambiguous_query_deletes_nothing(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    repo.remember("prefers dark mode UI", MemoryType.PROFILE, permanent=True)
    repo.remember("prefers dark roast coffee", MemoryType.PROFILE, permanent=True)
    tool = ForgetTool(repository=repo)

    result = await tool.execute(query="dark")

    assert result.success is False
    assert len(result.metadata["candidates"]) == 2
    assert len(repo.retrieve(type=MemoryType.PROFILE)) == 2


@pytest.mark.asyncio
async def test_forget_tool_no_match(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    tool = ForgetTool(repository=repo)

    result = await tool.execute(query="nonexistent")
    assert result.success is False
    assert "No memory found" in result.error


@pytest.mark.asyncio
async def test_forget_tool_requires_id_or_query(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    tool = ForgetTool(repository=repo)

    result = await tool.execute()
    assert result.success is False
