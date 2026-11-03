"""Evaluation runner: asks the fixed question set and grades the answers."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

import anthropic
from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from harness import config, rag
from harness.agent import Agent, ToolCallRecord
from harness.logger import RunLogger
from harness.tools import DocTools


def normalize_for_match(s: str) -> str:
    s = rag.normalize(s)
    s = re.sub(r"\s*([.,])\s*", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def _display(item) -> str:
    return item if isinstance(item, str) else " / ".join(item)


def grade(answer: str, must_include: list) -> tuple[bool, list[str]]:
    norm = normalize_for_match(answer)
    missing: list[str] = []
    for item in must_include:
        alternatives = [item] if isinstance(item, str) else list(item)
        if not any(normalize_for_match(a) in norm for a in alternatives):
            missing.append(_display(item))
    return (not missing, missing)


def retrieval_hit(source: str | None, tool_calls: list[ToolCallRecord]) -> bool | None:
    if source is None:
        return None
    for rec in tool_calls:
        if source in json.dumps(rec.input, ensure_ascii=False) or source in rec.result:
            return True
    return False


def load_questions() -> list[dict]:
    path = config.EVAL_DIR / "questions.jsonl"
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass
    load_dotenv(config.ROOT / ".env")

    parser = argparse.ArgumentParser(description="Chạy bộ câu hỏi đánh giá")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default=config.DEFAULT_MODEL)
    parser.add_argument("--max-turns", type=int, default=config.DEFAULT_MAX_TURNS)
    args = parser.parse_args(argv)

    console = Console()
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        console.print(
            "[red]Chưa có ANTHROPIC_API_KEY. Tạo file .env từ .env.example rồi điền key.[/red]"
        )
        return 1

    questions = load_questions()
    if args.limit is not None:
        questions = questions[: args.limit]

    ts = f"{datetime.now():%Y%m%d-%H%M%S}"
    log_path = config.LOGS_DIR / f"eval-{ts}.jsonl"
    client = anthropic.Anthropic()
    rows: list[dict] = []

    for i, q in enumerate(questions, 1):
        console.print(
            f"[{i}/{len(questions)}] {q['id']}: {escape(q['question'])}", highlight=False
        )
        row: dict = {
            "id": q["id"],
            "question": q["question"],
            "source": q.get("source"),
            "must_include": q["must_include"],
        }
        try:
            agent = Agent(
                client,
                DocTools(config.DOCS_DIR, config.NOTES_DIR, approver=lambda *_: False),
                RunLogger(None, log_path, verbose=False),
                model=args.model,
                max_turns=args.max_turns,
            )
            result = agent.ask(q["question"])
            passed, missing = grade(result.text, q["must_include"])
            if result.error:
                passed = False
            row.update(
                passed=passed,
                missing=missing,
                retrieval=retrieval_hit(q.get("source"), result.tool_calls),
                turns=result.turns,
                tool_calls=len(result.tool_calls),
                cost_usd=result.cost_usd,
                answer=result.text,
                error=result.error,
            )
        except Exception as e:
            row.update(
                passed=False,
                missing=[_display(m) for m in q["must_include"]],
                retrieval=None if q.get("source") is None else False,
                turns=0,
                tool_calls=0,
                cost_usd=0.0,
                answer="",
                error=f"{type(e).__name__}: {e}",
            )
        rows.append(row)

    table = Table(title="Kết quả đánh giá")
    for col in ("ID", "Kết quả", "Retrieval", "Lượt", "Chi phí", "Thiếu"):
        table.add_column(col)
    for r in rows:
        retr = "–" if r["retrieval"] is None else ("✅" if r["retrieval"] else "❌")
        missing = ", ".join(r["missing"]) if r["missing"] else (r["error"] or "")
        table.add_row(
            r["id"],
            "✅" if r["passed"] else "❌",
            retr,
            str(r["turns"]),
            f"${r['cost_usd']:.4f}",
            escape(missing),
        )
    console.print(table)

    total = len(rows)
    passed = sum(1 for r in rows if r["passed"])
    retr_rows = [r for r in rows if r["retrieval"] is not None]
    retr_ok = sum(1 for r in retr_rows if r["retrieval"])
    pct = passed / total * 100 if total else 0
    avg_turns = sum(r["turns"] for r in rows) / total if total else 0
    console.print(f"Độ chính xác: {passed}/{total} ({pct:.0f}%)", highlight=False)
    console.print(f"Retrieval hit: {retr_ok}/{len(retr_rows)}", highlight=False)
    console.print(f"Tổng chi phí: ${sum(r['cost_usd'] for r in rows):.4f}", highlight=False)
    console.print(f"Trung bình lượt: {avg_turns:.1f}", highlight=False)

    config.EVAL_DIR.mkdir(parents=True, exist_ok=True)
    out = config.EVAL_DIR / f"results-{ts}.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"Đã ghi kết quả: {out}", highlight=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
