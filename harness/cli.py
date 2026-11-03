"""Interactive CLI for the policy Q&A agent."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

import anthropic
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from harness import config
from harness.agent import Agent
from harness.logger import RunLogger
from harness.tools import Approver, DocTools

HELP_TEXT = """Các lệnh:
  /help        Xem danh sách lệnh
  /exit, /quit Thoát và hiển thị chi phí phiên
  /reset       Xóa lịch sử hội thoại
  /maxturns N  Đặt số lượt tối đa cho mỗi câu hỏi (N >= 1)
  /fault       Làm tool kế tiếp bị lỗi giả lập
  /cost        Xem token và chi phí của phiên"""

_YES = {"y", "yes", "c", "co", "có"}


def console_approver(console: Console) -> Approver:
    """Return an approver that asks the user on the console."""

    def approve(tool_name: str, tool_input: dict) -> bool:
        content = str(tool_input.get("content", ""))[:500]
        title = tool_input.get("title", "")
        console.print(
            Panel(
                f"Tool: {tool_name}\nTiêu đề: {title}\n\n{content}",
                title="Yêu cầu duyệt thao tác GHI",
                border_style="yellow",
            )
        )
        answer = console.input("Cho phép? (y/n) ")
        return answer.strip().lower() in _YES

    return approve


def _setup_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def _print_cost(console: Console, agent: Agent) -> None:
    u = agent.session_usage
    console.print(
        f"Phiên: in={u.input_tokens} out={u.output_tokens} "
        f"cache_read={u.cache_read} cache_write={u.cache_write} · "
        f"${agent.session_cost:.5f}",
        highlight=False,
    )


def _handle_command(text: str, console: Console, agent: Agent, tools: DocTools) -> bool:
    """Handle a slash command. Return True when the REPL should exit."""
    parts = text.split()
    cmd = parts[0].lower()
    if cmd in ("/exit", "/quit"):
        _print_cost(console, agent)
        return True
    if cmd == "/help":
        console.print(HELP_TEXT, highlight=False)
    elif cmd == "/reset":
        agent.reset()
        console.print("Đã xóa lịch sử hội thoại.")
    elif cmd == "/maxturns":
        try:
            n = int(parts[1]) if len(parts) == 2 else 0
        except ValueError:
            n = 0
        if n >= 1:
            agent.max_turns = n
            console.print(f"Số lượt tối đa: {n}")
        else:
            console.print("[yellow]Cách dùng: /maxturns N (N là số nguyên >= 1)[/yellow]")
    elif cmd == "/fault":
        tools.fault_next = True
        console.print("Lần gọi tool kế tiếp sẽ bị lỗi giả lập.")
    elif cmd == "/cost":
        _print_cost(console, agent)
    else:
        console.print("Lệnh không hợp lệ. Gõ /help.")
    return False


def main(argv: list[str] | None = None) -> int:
    _setup_utf8()
    load_dotenv(config.ROOT / ".env")

    parser = argparse.ArgumentParser(description="Trợ lý tra cứu quy chế nội bộ")
    parser.add_argument("--model", default=config.DEFAULT_MODEL)
    parser.add_argument("--max-turns", type=int, default=config.DEFAULT_MAX_TURNS)
    parser.add_argument("--no-fallbacks", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="Ẩn log từng lượt")
    args = parser.parse_args(argv)

    console = Console()
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        console.print(
            "[red]Chưa có ANTHROPIC_API_KEY. Tạo file .env từ .env.example rồi điền key.[/red]"
        )
        return 1

    log_path = config.LOGS_DIR / f"session-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    logger = RunLogger(console, log_path, verbose=not args.quiet)
    tools = DocTools(config.DOCS_DIR, config.NOTES_DIR, approver=console_approver(console))
    agent = Agent(
        anthropic.Anthropic(),
        tools,
        logger,
        model=args.model,
        max_turns=args.max_turns,
        use_fallbacks=not args.no_fallbacks,
    )

    console.print(
        Panel(
            f"Model: {args.model}\n"
            f"Số lượt tối đa: {args.max_turns}\n"
            f"Số tài liệu: {len(tools.docs)}\n"
            f"File log: {log_path}\n"
            "Gõ /help để xem lệnh.",
            title="Trợ lý tra cứu quy chế nội bộ — Học viện HanesVip",
            border_style="cyan",
        )
    )

    while True:
        try:
            text = console.input("[bold cyan]Bạn> [/]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nTạm biệt!")
            return 0
        if not text:
            continue
        if text.startswith("/"):
            if _handle_command(text, console, agent, tools):
                return 0
            continue
        try:
            result = agent.ask(text)
        except Exception as e:  # keep the session alive
            console.print(
                f"[red]Lỗi không mong muốn: {type(e).__name__}: {e}. Phiên vẫn tiếp tục.[/red]",
                highlight=False,
            )
            continue
        border = "red" if result.error else "yellow" if result.hit_turn_limit else "green"
        console.print(Panel(Markdown(result.text), title="Trợ lý", border_style=border))
        console.print(
            f"[dim]{result.turns} lượt · {len(result.tool_calls)} tool call · "
            f"${result.cost_usd:.5f} · cache hit: {'có' if result.cache_hit else 'không'}[/dim]",
            highlight=False,
        )


if __name__ == "__main__":
    raise SystemExit(main())
