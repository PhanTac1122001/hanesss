"""Run logger: rich console output plus a JSONL event log."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markup import escape

from harness.pricing import Usage
from harness.tools import ToolResult

if TYPE_CHECKING:  # avoid a circular import at runtime
    from harness.agent import AnswerResult

_LEVEL_STYLES = {"info": "cyan", "warn": "yellow", "error": "red"}


class RunLogger:
    def __init__(
        self,
        console: Console | None,
        jsonl_path: Path | None,
        verbose: bool = True,
    ):
        self.console = console
        self.verbose = verbose
        self.jsonl_path = Path(jsonl_path) if jsonl_path else None
        if self.jsonl_path:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    # -- internals ---------------------------------------------------------
    def _write(self, event: str, **data) -> None:
        if not self.jsonl_path:
            return
        record = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **data}
        with self.jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _print(self, *args, **kwargs) -> None:
        if self.console is not None and self.verbose:
            self.console.print(*args, **kwargs)

    # -- events ------------------------------------------------------------
    def question_start(self, index: int, question: str) -> None:
        self._write("question_start", index=index, question=question)
        if self.console is not None and self.verbose:
            self.console.rule(f"Câu hỏi #{index}")

    def turn(
        self,
        turn: int,
        max_turns: int,
        stop_reason: str,
        usage: Usage,
        cost: float,
        model: str,
        final_turn: bool,
    ) -> None:
        self._write(
            "turn",
            turn=turn,
            max_turns=max_turns,
            stop_reason=stop_reason,
            model=model,
            final_turn=final_turn,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read=usage.cache_read,
            cache_write=usage.cache_write,
            cost_usd=cost,
        )
        cache_read = f"cache_read={usage.cache_read}"
        if usage.cache_read > 0:
            cache_read = f"[green]{cache_read}[/green]"
        line = (
            f"Lượt {turn}/{max_turns} · stop={escape(str(stop_reason))} · "
            f"in={usage.input_tokens} out={usage.output_tokens} "
            f"{cache_read} cache_write={usage.cache_write} · ${cost:.5f}"
        )
        if final_turn:
            line += " · LƯỢT CUỐI"
        self._print(line, highlight=False)

    def tool_call(self, name: str, tool_input: dict, result: ToolResult) -> None:
        self._write(
            "tool_call",
            name=name,
            input=tool_input,
            result=result.content[:2000],
            is_error=result.is_error,
            duration_ms=round(result.duration_ms, 1),
        )
        if self.console is None or not self.verbose:
            return
        args = json.dumps(tool_input, ensure_ascii=False, separators=(",", ":"), default=str)
        self.console.print(f"  ↳ tool [bold]{escape(name)}[/bold] {escape(args)}", highlight=False)
        snippet = escape(result.content[:300])
        if result.is_error:
            snippet = f"[red]LỖI: {snippet}[/red]"
        self.console.print(f"    {snippet} ({result.duration_ms:.0f} ms)", highlight=False)

    def notice(self, message: str, level: str = "info") -> None:
        self._write("notice", level=level, message=message)
        style = _LEVEL_STYLES.get(level, "cyan")
        self._print(f"[{style}]{escape(message)}[/{style}]", highlight=False)

    def question_end(self, result: "AnswerResult") -> None:
        u = result.usage
        self._write(
            "question_end",
            turns=result.turns,
            tool_calls=len(result.tool_calls),
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read=u.cache_read,
            cache_write=u.cache_write,
            cost_usd=result.cost_usd,
            cache_hit=result.cache_hit,
            hit_turn_limit=result.hit_turn_limit,
            error=result.error,
        )
        if self.console is None or not self.verbose:
            return
        self.console.print(
            f"Số lượt: {result.turns} · Số tool call: {len(result.tool_calls)} · "
            f"Tokens: in={u.input_tokens} out={u.output_tokens} "
            f"cache_read={u.cache_read} cache_write={u.cache_write}",
            highlight=False,
        )
        self.console.print(
            f"Chi phí câu hỏi: ${result.cost_usd:.5f} · "
            f"Cache hit: {'có' if result.cache_hit else 'không'}",
            highlight=False,
        )
