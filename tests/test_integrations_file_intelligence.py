import pytest

from app.integrations.file_intelligence import FileIntelligenceService
from app.security.path_guard import PathGuard


def _service(tmp_path):
    return FileIntelligenceService(path_guard=PathGuard(allowed_roots=[tmp_path]))


def test_find_files_matches_by_name(tmp_path):
    (tmp_path / "report_draft.txt").write_text("draft")
    (tmp_path / "notes.txt").write_text("notes")

    service = _service(tmp_path)
    result = service.find_files(query="report")

    assert result.success is True
    assert len(result.files) == 1
    assert result.files[0].name == "report_draft.txt"


def test_find_files_respects_limit(tmp_path):
    for i in range(5):
        (tmp_path / f"match_{i}.txt").write_text("x")

    service = _service(tmp_path)
    result = service.find_files(query="match", limit=2)

    assert len(result.files) == 2


def test_find_files_denies_directory_outside_allowed_roots(tmp_path):
    outside = tmp_path.parent / "definitely_outside_xyz"
    service = _service(tmp_path)

    result = service.find_files(query="x", directory=str(outside))

    assert result.success is False


def test_list_recent_files_sorted_newest_first(tmp_path):
    import os
    import time

    old_file = tmp_path / "old.txt"
    old_file.write_text("old")
    time.sleep(0.05)
    new_file = tmp_path / "new.txt"
    new_file.write_text("new")

    service = _service(tmp_path)
    result = service.list_recent_files(limit=10)

    assert result.success is True
    names = [f.name for f in result.files]
    assert names.index("new.txt") < names.index("old.txt")


def test_read_text_file(tmp_path):
    target = tmp_path / "hello.txt"
    target.write_text("Hello, world!")

    service = _service(tmp_path)
    result = service.read_file(str(target))

    assert result.success is True
    assert result.content == "Hello, world!"


def test_read_file_outside_allowed_root_denied(tmp_path):
    outside = tmp_path.parent / "outside_secret.txt"
    outside.write_text("secret")
    try:
        service = _service(tmp_path)
        result = service.read_file(str(outside))
        assert result.success is False
    finally:
        outside.unlink(missing_ok=True)


def test_read_file_unsupported_extension(tmp_path):
    target = tmp_path / "image.png"
    target.write_bytes(b"\x89PNG\r\n")

    service = _service(tmp_path)
    result = service.read_file(str(target))

    assert result.success is False
    assert "Unsupported file type" in result.error


def test_read_file_nonexistent(tmp_path):
    service = _service(tmp_path)
    result = service.read_file(str(tmp_path / "nope.txt"))
    assert result.success is False


def test_search_file_contents_finds_matching_lines(tmp_path):
    (tmp_path / "a.txt").write_text("line one\nsearch target here\nline three")
    (tmp_path / "b.txt").write_text("nothing relevant")

    service = _service(tmp_path)
    result = service.search_file_contents(query="search target")

    assert result.success is True
    assert len(result.matches) == 1
    assert result.matches[0]["line"] == 2
    assert "a.txt" in result.matches[0]["path"]


def test_search_file_contents_case_insensitive(tmp_path):
    (tmp_path / "a.txt").write_text("Hello World")

    service = _service(tmp_path)
    result = service.search_file_contents(query="hello world")

    assert len(result.matches) == 1


def test_delete_file_removes_it(tmp_path):
    target = tmp_path / "temp.txt"
    target.write_text("delete me")

    service = _service(tmp_path)
    result = service.delete_file(str(target))

    assert result.success is True
    assert not target.exists()


def test_delete_file_outside_allowed_root_denied(tmp_path):
    outside = tmp_path.parent / "outside_delete_me.txt"
    outside.write_text("should survive")
    try:
        service = _service(tmp_path)
        result = service.delete_file(str(outside))
        assert result.success is False
        assert outside.exists()  # never actually touched
    finally:
        outside.unlink(missing_ok=True)


def test_delete_file_nonexistent(tmp_path):
    service = _service(tmp_path)
    result = service.delete_file(str(tmp_path / "nope.txt"))
    assert result.success is False


def test_delete_directory_rejected_not_a_file(tmp_path):
    subdir = tmp_path / "subdir"
    subdir.mkdir()

    service = _service(tmp_path)
    result = service.delete_file(str(subdir))

    assert result.success is False
    assert "not a file" in result.error


def test_read_docx_file(tmp_path):
    docx = pytest.importorskip("docx")

    target = tmp_path / "doc.docx"
    document = docx.Document()
    document.add_paragraph("First paragraph.")
    document.add_paragraph("Second paragraph.")
    document.save(str(target))

    service = _service(tmp_path)
    result = service.read_file(str(target))

    assert result.success is True
    assert "First paragraph." in result.content
    assert "Second paragraph." in result.content


def test_read_pdf_file(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    target = tmp_path / "doc.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(target, "wb") as f:
        writer.write(f)

    service = _service(tmp_path)
    result = service.read_file(str(target))

    # A blank page has no extractable text, but this should still succeed
    # (empty string), not error — proves the PDF code path runs cleanly.
    assert result.success is True
    assert result.content == ""
