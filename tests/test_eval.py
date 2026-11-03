import json

from harness import config
from harness.agent import ToolCallRecord
from harness.eval import grade, normalize_for_match, retrieval_hit


def test_normalize_for_match():
    assert normalize_for_match("Điểm  TB: 6 , 5 điểm .") == "diem tb: 6,5 diem."
    assert normalize_for_match("300 . 000 đồng") == "300.000 dong"


def test_grade_accents_and_case():
    ok, missing = grade("Học viên bị ĐÌNH CHỈ học.", ["đình chỉ"])
    assert ok and missing == []
    ok, _ = grade("Bi dinh chi hoc", ["đình chỉ"])
    assert ok


def test_grade_decimal_comma_alternatives():
    ok, missing = grade("Cần điểm trung bình tối thiểu 6,5.", [["6.5", "6,5"]])
    assert ok and missing == []
    ok, _ = grade("Cần tối thiểu 6.5 điểm", [["6.5", "6,5"]])
    assert ok
    ok, _ = grade("Phí là 300.000 đồng", [["300.000", "300 nghìn"]])
    assert ok


def test_grade_missing_items():
    ok, missing = grade("Cần 8,5 điểm.", [["8.5", "8,5"], "30%"])
    assert not ok
    assert missing == ["30%"]
    ok, missing = grade("Không rõ.", [["8.5", "8,5"], "30%"])
    assert not ok
    assert missing == ["8.5 / 8,5", "30%"]


def test_retrieval_hit():
    recs = [
        ToolCallRecord("search_documents", {"query": "x"}, "[quy-che-hoc-vu.md] ...", False),
        ToolCallRecord("read_document", {"filename": "noi-quy-lop-hoc.md"}, "ok", False),
    ]
    assert retrieval_hit("quy-che-hoc-vu.md", recs) is True
    assert retrieval_hit("noi-quy-lop-hoc.md", recs) is True
    assert retrieval_hit("quy-trinh-bao-luu.md", recs) is False
    assert retrieval_hit(None, recs) is None
    assert retrieval_hit("a.md", []) is False


def test_questions_file_valid():
    path = config.EVAL_DIR / "questions.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 10
    assert len({r["id"] for r in rows}) == 10
    for r in rows:
        assert set(r) == {"id", "question", "must_include", "source"}
        assert r["question"] and r["must_include"]
        if r["source"] is not None:
            assert (config.DOCS_DIR / r["source"]).exists(), r["source"]
