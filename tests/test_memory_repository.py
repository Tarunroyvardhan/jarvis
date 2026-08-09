from datetime import datetime, timedelta

import pytest

from app.memory.models import MemoryType
from app.memory.repository import MemoryRepository


def test_remember_permanent_has_no_expiry(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    memory = repo.remember("likes morning meetings", MemoryType.PROFILE, permanent=True)
    assert memory.is_permanent is True
    assert memory.expires_at is None


def test_remember_auto_has_expiry_around_seven_days(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    memory = repo.remember("worked on project X today", MemoryType.EPISODIC, permanent=False)
    assert memory.is_permanent is False
    assert memory.expires_at is not None

    delta = memory.expires_at - datetime.now()
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, hours=1)


def test_remember_rejects_empty_content(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    with pytest.raises(ValueError):
        repo.remember("   ", MemoryType.PROFILE, permanent=True)


def test_retrieve_filters_by_type(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    repo.remember("prefers dark mode", MemoryType.PROFILE, permanent=True)
    repo.remember("worked on report", MemoryType.EPISODIC, permanent=False)

    profile_only = repo.retrieve(type=MemoryType.PROFILE)
    assert len(profile_only) == 1
    assert profile_only[0].content == "prefers dark mode"


def test_retrieve_filters_by_query(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    repo.remember("prefers dark mode", MemoryType.PROFILE, permanent=True)
    repo.remember("prefers morning meetings", MemoryType.PROFILE, permanent=True)

    results = repo.retrieve(query="morning")
    assert len(results) == 1
    assert "morning" in results[0].content


def test_retrieve_excludes_expired_by_default(tmp_path):
    db_path = tmp_path / "test.db"
    repo = MemoryRepository(db_path=db_path)
    memory = repo.remember("temp note", MemoryType.CONVERSATION, permanent=False)

    # Force it into the past directly via SQL to simulate expiry without waiting.
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE memories SET expires_at = ? WHERE id = ?",
        ((datetime.now() - timedelta(days=1)).isoformat(), memory.id),
    )
    conn.commit()
    conn.close()

    results = repo.retrieve(type=MemoryType.CONVERSATION)
    assert results == []

    results_incl = repo.retrieve(type=MemoryType.CONVERSATION, include_expired=True)
    assert len(results_incl) == 1


def test_forget_deletes_and_reports_success(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    memory = repo.remember("delete me", MemoryType.PROFILE, permanent=True)

    assert repo.forget(memory.id) is True
    assert repo.retrieve(type=MemoryType.PROFILE) == []


def test_forget_nonexistent_returns_false(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    assert repo.forget(9999) is False


def test_purge_expired_removes_only_expired(tmp_path):
    db_path = tmp_path / "test.db"
    repo = MemoryRepository(db_path=db_path)
    permanent = repo.remember("stays forever", MemoryType.PROFILE, permanent=True)
    expiring = repo.remember("goes away", MemoryType.CONVERSATION, permanent=False)

    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE memories SET expires_at = ? WHERE id = ?",
        ((datetime.now() - timedelta(days=1)).isoformat(), expiring.id),
    )
    conn.commit()
    conn.close()

    purged_count = repo.purge_expired()
    assert purged_count == 1

    remaining = repo.retrieve(include_expired=True, limit=100)
    remaining_ids = {m.id for m in remaining}
    assert permanent.id in remaining_ids
    assert expiring.id not in remaining_ids


def test_update_changes_content(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    memory = repo.remember("original", MemoryType.PROFILE, permanent=True)

    updated = repo.update(memory.id, "revised")
    assert updated.content == "revised"


def test_update_nonexistent_returns_none(tmp_path):
    repo = MemoryRepository(db_path=tmp_path / "test.db")
    assert repo.update(9999, "x") is None
