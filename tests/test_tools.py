from harness.config import DOCS_DIR
from harness.tools import TOOL_SCHEMAS, DocTools


def make(tmp_path, approve=True):
    return DocTools(DOCS_DIR, tmp_path / "notes", lambda name, inp: approve)


def test_schemas_order_and_strict():
    assert [s["name"] for s in TOOL_SCHEMAS] == [
        "list_documents", "search_documents", "read_document", "save_note",
    ]
    for s in TOOL_SCHEMAS:
        assert set(s) == {"name", "description", "input_schema"}
        assert s["input_schema"]["additionalProperties"] is False


def test_list_documents(tmp_path):
    r = make(tmp_path).execute("list_documents", {})
    assert not r.is_error
    assert r.content.startswith("Có 6 tài liệu:")
    assert r.content.count("\n- ") == 6
    assert r.duration_ms >= 0


def test_search_finds_refund_doc(tmp_path):
    r = make(tmp_path).execute("search_documents", {"query": "hoàn học phí"})
    assert not r.is_error
    assert "chinh-sach-hoan-hoc-phi.md" in r.content


def test_search_empty_query_is_error(tmp_path):
    r = make(tmp_path).execute("search_documents", {"query": "   "})
    assert r.is_error


def test_search_top_k_clamped_and_no_hits(tmp_path):
    t = make(tmp_path)
    assert not t.execute("search_documents", {"query": "học phí", "top_k": 100}).is_error
    r = t.execute("search_documents", {"query": "zzzqqq"})
    assert not r.is_error and "Không tìm thấy" in r.content


def test_read_document_full_and_section(tmp_path):
    t = make(tmp_path)
    full = t.execute("read_document", {"filename": "chinh-sach-hoan-hoc-phi.md"})
    assert not full.is_error and "Chính sách hoàn học phí" in full.content
    first_heading = next(
        c.heading for c in t.index.chunks if c.doc == "chinh-sach-hoan-hoc-phi.md" and c.heading
    )
    sec = t.execute(
        "read_document",
        {"filename": "chinh-sach-hoan-hoc-phi.md", "section": first_heading.split(" › ")[-1].upper()},
    )
    assert not sec.is_error and sec.content.startswith("## ")
    bad = t.execute("read_document", {"filename": "chinh-sach-hoan-hoc-phi.md", "section": "zzz"})
    assert bad.is_error and "Các mục hiện có" in bad.content


def test_read_document_missing_and_traversal(tmp_path):
    t = make(tmp_path)
    r = t.execute("read_document", {"filename": "khong-co.md"})
    assert r.is_error and "Không tìm thấy" in r.content
    r = t.execute("read_document", {"filename": "../x.md"})
    assert r.is_error and "không hợp lệ" in r.content


def test_unknown_tool_and_missing_param(tmp_path):
    t = make(tmp_path)
    r = t.execute("nope", {})
    assert r.is_error and "không tồn tại" in r.content
    r = t.execute("search_documents", {})
    assert r.is_error and "query" in r.content
    r = t.execute("search_documents", {"query": "x", "top_k": "4"})
    assert r.is_error and "top_k" in r.content


def test_fault_next_resets(tmp_path):
    t = make(tmp_path)
    t.fault_next = True
    r = t.execute("list_documents", {})
    assert r.is_error and "Lỗi giả lập" in r.content
    assert t.fault_next is False
    assert not t.execute("list_documents", {}).is_error


def test_approver_exception_is_caught(tmp_path):
    def boom(name, inp):
        raise ValueError("hỏng")

    t = DocTools(DOCS_DIR, tmp_path / "notes", boom)
    r = t.execute("save_note", {"title": "a", "content": "b"})
    assert r.is_error and "Lỗi nội bộ" in r.content


def test_save_note_denied(tmp_path):
    t = make(tmp_path, approve=False)
    r = t.execute("save_note", {"title": "Tiêu đề", "content": "nội dung"})
    assert not r.is_error and "TỪ CHỐI" in r.content
    assert not (tmp_path / "notes").exists() or not list((tmp_path / "notes").iterdir())


def test_save_note_approved_and_duplicate(tmp_path):
    t = make(tmp_path)
    r = t.execute("save_note", {"title": "Hoàn học phí", "content": "70%"})
    assert not r.is_error and "notes/hoan-hoc-phi.md" in r.content
    f = tmp_path / "notes" / "hoan-hoc-phi.md"
    assert f.read_text(encoding="utf-8") == "# Hoàn học phí\n\n70%\n"
    r2 = t.execute("save_note", {"title": "Hoàn học phí", "content": "x"})
    assert "hoan-hoc-phi-2.md" in r2.content
    assert (tmp_path / "notes" / "hoan-hoc-phi-2.md").exists()


def test_save_note_fallback_name(tmp_path):
    r = make(tmp_path).execute("save_note", {"title": "!!!", "content": "x"})
    assert "notes/ghi-chu.md" in r.content


def test_none_optional_param_is_dropped(tmp_path):
    r = make(tmp_path).execute("search_documents", {"query": "hoàn học phí", "top_k": None})
    assert not r.is_error
    assert "chinh-sach-hoan-hoc-phi.md" in r.content


def test_unknown_param_rejected(tmp_path):
    r = make(tmp_path).execute("search_documents", {"query": "hoàn học phí", "extra": 1})
    assert r.is_error
    assert "Tham số không hợp lệ" in r.content and "'extra'" in r.content
    assert "query, top_k" in r.content


def test_unknown_param_on_no_arg_tool(tmp_path):
    r = make(tmp_path).execute("list_documents", {"x": 1})
    assert r.is_error and "không có" in r.content
