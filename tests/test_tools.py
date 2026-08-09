import pytest

from app.tools.notes import CreateNoteTool, DeleteNoteTool, ListNotesTool
from app.tools.tasks import CompleteTaskTool, CreateTaskTool, DeleteTaskTool, ListTasksTool
from app.tools.time_tool import GetCurrentTimeTool


@pytest.mark.asyncio
async def test_get_current_time_returns_a_string():
    tool = GetCurrentTimeTool()
    result = await tool.execute()
    assert result.success is True
    assert isinstance(result.result, str)
    assert len(result.result) > 0


@pytest.mark.asyncio
async def test_create_and_list_notes(tmp_path):
    db_path = tmp_path / "test.db"
    create_tool = CreateNoteTool(db_path=db_path)
    list_tool = ListNotesTool(db_path=db_path)

    create_result = await create_tool.execute(content="buy milk")
    assert create_result.success is True

    list_result = await list_tool.execute()
    assert list_result.success is True
    assert len(list_result.result) == 1
    assert list_result.result[0]["content"] == "buy milk"


@pytest.mark.asyncio
async def test_create_note_rejects_empty_content(tmp_path):
    tool = CreateNoteTool(db_path=tmp_path / "test.db")
    result = await tool.execute(content="   ")
    assert result.success is False
    assert "empty" in result.error


@pytest.mark.asyncio
async def test_create_and_list_tasks(tmp_path):
    db_path = tmp_path / "test.db"
    create_tool = CreateTaskTool(db_path=db_path)
    list_tool = ListTasksTool(db_path=db_path)

    create_result = await create_tool.execute(title="submit assignment", priority="high")
    assert create_result.success is True

    list_result = await list_tool.execute()
    assert list_result.success is True
    assert len(list_result.result) == 1
    assert list_result.result[0]["title"] == "submit assignment"
    assert list_result.result[0]["priority"] == "high"
    assert list_result.result[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_create_task_rejects_invalid_priority(tmp_path):
    tool = CreateTaskTool(db_path=tmp_path / "test.db")
    result = await tool.execute(title="x", priority="urgent-ish")
    assert result.success is False
    assert "Invalid priority" in result.error


@pytest.mark.asyncio
async def test_list_tasks_filters_by_status(tmp_path):
    db_path = tmp_path / "test.db"
    create_tool = CreateTaskTool(db_path=db_path)
    list_tool = ListTasksTool(db_path=db_path)

    await create_tool.execute(title="task one")
    pending = await list_tool.execute(status="pending")
    completed = await list_tool.execute(status="completed")

    assert len(pending.result) == 1
    assert len(completed.result) == 0


@pytest.mark.asyncio
async def test_delete_note_removes_it(tmp_path):
    db_path = tmp_path / "test.db"
    create_tool = CreateNoteTool(db_path=db_path)
    delete_tool = DeleteNoteTool(db_path=db_path)
    list_tool = ListNotesTool(db_path=db_path)

    created = await create_tool.execute(content="temporary note")
    note_id = created.metadata["id"]

    delete_result = await delete_tool.execute(note_id=note_id)
    assert delete_result.success is True

    remaining = await list_tool.execute()
    assert remaining.result == []


@pytest.mark.asyncio
async def test_delete_note_nonexistent_id(tmp_path):
    tool = DeleteNoteTool(db_path=tmp_path / "test.db")
    result = await tool.execute(note_id=9999)
    assert result.success is False
    assert "No note found" in result.error


@pytest.mark.asyncio
async def test_delete_note_describe_includes_content_preview(tmp_path):
    db_path = tmp_path / "test.db"
    create_tool = CreateNoteTool(db_path=db_path)
    delete_tool = DeleteNoteTool(db_path=db_path)

    created = await create_tool.execute(content="buy milk and eggs")
    note_id = created.metadata["id"]

    description = await delete_tool.describe(note_id=note_id)
    assert str(note_id) in description
    assert "buy milk and eggs" in description


@pytest.mark.asyncio
async def test_delete_note_describe_handles_missing_id_gracefully(tmp_path):
    tool = DeleteNoteTool(db_path=tmp_path / "test.db")
    description = await tool.describe(note_id=9999)
    assert "not found" in description.lower()


@pytest.mark.asyncio
async def test_complete_task_marks_it_completed(tmp_path):
    db_path = tmp_path / "test.db"
    create_tool = CreateTaskTool(db_path=db_path)
    complete_tool = CompleteTaskTool(db_path=db_path)
    list_tool = ListTasksTool(db_path=db_path)

    created = await create_tool.execute(title="finish report")
    task_id = created.metadata["id"]

    complete_result = await complete_tool.execute(task_id=task_id)
    assert complete_result.success is True

    completed = await list_tool.execute(status="completed")
    assert len(completed.result) == 1
    assert completed.result[0]["id"] == task_id
    assert completed.result[0]["completed_at"] is not None


@pytest.mark.asyncio
async def test_complete_task_nonexistent_or_already_completed(tmp_path):
    db_path = tmp_path / "test.db"
    create_tool = CreateTaskTool(db_path=db_path)
    complete_tool = CompleteTaskTool(db_path=db_path)

    created = await create_tool.execute(title="one-shot")
    task_id = created.metadata["id"]

    first = await complete_tool.execute(task_id=task_id)
    assert first.success is True

    second = await complete_tool.execute(task_id=task_id)  # already completed
    assert second.success is False


@pytest.mark.asyncio
async def test_delete_task_removes_it(tmp_path):
    db_path = tmp_path / "test.db"
    create_tool = CreateTaskTool(db_path=db_path)
    delete_tool = DeleteTaskTool(db_path=db_path)
    list_tool = ListTasksTool(db_path=db_path)

    created = await create_tool.execute(title="temporary task")
    task_id = created.metadata["id"]

    delete_result = await delete_tool.execute(task_id=task_id)
    assert delete_result.success is True

    remaining = await list_tool.execute()
    assert remaining.result == []


@pytest.mark.asyncio
async def test_delete_task_describe_includes_title(tmp_path):
    db_path = tmp_path / "test.db"
    create_tool = CreateTaskTool(db_path=db_path)
    delete_tool = DeleteTaskTool(db_path=db_path)

    created = await create_tool.execute(title="submit assignment")
    task_id = created.metadata["id"]

    description = await delete_tool.describe(task_id=task_id)
    assert str(task_id) in description
    assert "submit assignment" in description


@pytest.mark.asyncio
async def test_delete_task_nonexistent_id(tmp_path):
    tool = DeleteTaskTool(db_path=tmp_path / "test.db")
    result = await tool.execute(task_id=9999)
    assert result.success is False
    assert "No task found" in result.error
