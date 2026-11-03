from harness.config import DOCS_DIR
from harness.rag import BM25Index, build_index, chunk_markdown, normalize, tokenize

SAMPLE = """# Chính sách hoàn học phí

Giới thiệu chung.

## Mức hoàn phí

Hoàn 80% nếu rút trước khai giảng.

## Trống

## Thủ tục

### Hồ sơ

Nộp đơn rút học.
"""


def test_normalize():
    assert normalize("Học phí ĐÀO TẠO") == "hoc phi dao tao"


def test_tokenize_numbers_and_bigrams():
    toks = tokenize("Học phí 6.5 triệu, phạt 300.000 đồng")
    assert "6.5" in toks
    assert "300.000" in toks
    assert "hoc_phi" in toks
    assert tokenize("học phí") == ["hoc", "phi", "hoc_phi"]


def test_chunk_markdown_headings_ids_and_empty():
    chunks = chunk_markdown("a.md", SAMPLE)
    assert [c.id for c in chunks] == ["a.md#1", "a.md#2", "a.md#3"]
    assert chunks[0].heading == "Chính sách hoàn học phí"
    assert chunks[1].heading == "Chính sách hoàn học phí › Mức hoàn phí"
    assert chunks[2].heading == "Chính sách hoàn học phí › Thủ tục › Hồ sơ"
    assert chunks[1].text == "Hoàn 80% nếu rút trước khai giảng."
    assert all(c.doc == "a.md" for c in chunks)
    assert not any("Trống" in c.heading for c in chunks)


def test_chunk_markdown_splits_long_body():
    paras = [("đoạn %d " % i) * 20 for i in range(6)]
    text = "# T\n\n" + "\n\n".join(paras)
    chunks = chunk_markdown("b.md", text, max_chars=400)
    assert len(chunks) > 1
    assert all(len(c.text) <= 400 for c in chunks)
    assert all(c.heading == "T" for c in chunks)
    assert [c.id for c in chunks] == [f"b.md#{i}" for i in range(1, len(chunks) + 1)]


def test_chunk_markdown_oversized_paragraph_stays_whole():
    chunks = chunk_markdown("c.md", "# T\n\n" + "x" * 500, max_chars=100)
    assert len(chunks) == 1 and len(chunks[0].text) == 500


def _index():
    text = (
        "# Quy chế\n\n## Học phí\n\nHoàn học phí 80% khi rút trước khai giảng.\n\n"
        "## Điểm danh\n\nVắng quá 20% số buổi bị cấm thi.\n"
    )
    return BM25Index(chunk_markdown("q.md", text))


def test_bm25_ranks_matching_chunk_first():
    results = _index().search("điểm danh vắng")
    assert results[0][0].heading.endswith("Điểm danh")
    assert results[0][1] > 0


def test_bm25_no_match_returns_empty():
    assert _index().search("zzzz qqqq") == []


def test_bm25_unaccented_query():
    results = _index().search("hoan hoc phi")
    assert results[0][0].heading.endswith("Học phí")


def test_bm25_top_k():
    assert len(_index().search("quy che hoc phi diem danh", top_k=1)) == 1


def test_build_index_real_docs():
    index, full = build_index(DOCS_DIR)
    assert "chinh-sach-hoan-hoc-phi.md" in full
    assert list(full) == sorted(full)
    top = index.search("rút học trước khai giảng hoàn bao nhiêu")[0][0]
    assert top.doc == "chinh-sach-hoan-hoc-phi.md"
