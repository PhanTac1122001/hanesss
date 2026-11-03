import copy
import json
from types import SimpleNamespace

import anthropic
import httpx2 as httpx  # anthropic 2.x ships httpx2
import pytest
from rich.console import Console

from harness import config
from harness.agent import FALLBACK_BETA, FINAL_TURN_NOTICE, SYSTEM_PROMPT, Agent
from harness.logger import RunLogger
from harness.pricing import Usage, cost_usd
from harness.tools import TOOL_SCHEMAS, DocTools


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []  # (api, deep-copied kwargs)
        self.messages = SimpleNamespace(create=lambda **kw: self._create("plain", kw))
        self.beta = SimpleNamespace(
            messages=SimpleNamespace(create=lambda **kw: self._create("beta", kw))
        )

    def _create(self, api, kwargs):
        self.calls.append((api, copy.deepcopy(kwargs)))
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(id_, name, **inp):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=inp)


def resp(content, stop="end_turn", inp=100, out=50, cr=0, cw=0, stop_details=None):
    return SimpleNamespace(
        content=content,
        stop_reason=stop,
        usage=SimpleNamespace(
            input_tokens=inp,
            output_tokens=out,
            cache_read_input_tokens=cr,
            cache_creation_input_tokens=cw,
        ),
        model="claude-sonnet-5-5",
        stop_details=stop_details,
    )


def make_agent(tmp_path, script, **kw):
    tools = DocTools(config.DOCS_DIR, tmp_path / "notes", approver=lambda *_: False)
    logger = RunLogger(None, tmp_path / "log.jsonl")
    client = FakeClient(script)
    return Agent(client, tools, logger, **kw), client


def test_multi_turn_tool_loop(tmp_path):
    agent, client = make_agent(tmp_path, [
        resp([tool_use("t1", "search_documents", query="hoàn học phí")], "tool_use"),
        resp([text("đang tra"), tool_use("t2", "list_documents")], "tool_use"),
        resp([text("Kết luận [a.md › b]")]),
    ])
    r = agent.ask("Hoàn học phí thế nào?")
    assert r.turns == 3
    assert r.error is None
    assert r.text == "Kết luận [a.md › b]"
    assert [t.name for t in r.tool_calls] == ["search_documents", "list_documents"]
    assert not r.hit_turn_limit
    msgs = client.calls[1][1]["messages"]
    assert msgs[-1]["role"] == "user"
    tr = msgs[-1]["content"][0]
    assert tr["type"] == "tool_result" and tr["tool_use_id"] == "t1"
    assert tr["is_error"] is False
    assert msgs[-2]["role"] == "assistant"


def test_request_kwargs_with_fallbacks(tmp_path):
    agent, client = make_agent(tmp_path, [
        resp([tool_use("t1", "list_documents")], "tool_use"),
        resp([text("xong")]),
    ])
    agent.ask("q")
    for api, kw in client.calls:
        assert api == "beta"
        assert kw["betas"] == [FALLBACK_BETA] == ["server-side-fallback-2026-07-01"]
        assert kw["fallbacks"] == "default"
        assert kw["model"] == "claude-sonnet-5-5"
        assert kw["max_tokens"] == config.MAX_TOKENS
        assert kw["system"][0]["text"] == SYSTEM_PROMPT
        assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert kw["cache_control"] == {"type": "ephemeral"}
        assert kw["tools"] == TOOL_SCHEMAS
        assert kw["output_config"] == {"effort": "medium"}
        assert "tool_choice" not in kw


def test_request_kwargs_without_fallbacks(tmp_path):
    agent, client = make_agent(tmp_path, [resp([text("xong")])], use_fallbacks=False)
    agent.ask("q")
    api, kw = client.calls[0]
    assert api == "plain"
    assert "betas" not in kw and "fallbacks" not in kw
    assert "tool_choice" not in kw


def test_system_prompt_is_long_and_static():
    assert len(SYSTEM_PROMPT) >= 2500
    assert "không tìm thấy thông tin" in SYSTEM_PROMPT
    assert "save_note" in SYSTEM_PROMPT


def test_turn_limit_forces_final_answer(tmp_path):
    agent, client = make_agent(tmp_path, [
        resp([tool_use("t1", "search_documents", query="x")], "tool_use"),
        resp([text("trả lời cuối")]),
    ], max_turns=2)
    r = agent.ask("q")
    assert r.hit_turn_limit is True
    assert r.turns == 2
    assert "tool_choice" not in client.calls[0][1]
    kw2 = client.calls[1][1]
    assert kw2["tool_choice"] == {"type": "none"}
    last = kw2["messages"][-1]
    assert last["role"] == "user"
    assert last["content"][0]["type"] == "tool_result"
    assert last["content"][-1] == {
        "type": "text", "text": FINAL_TURN_NOTICE.format(max_turns=2),
    }


def test_single_turn_limit(tmp_path):
    agent, client = make_agent(tmp_path, [resp([text("ngay")])], max_turns=1)
    r = agent.ask("q")
    kw = client.calls[0][1]
    assert kw["tool_choice"] == {"type": "none"}
    content = kw["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "q"}
    assert content[1] == {"type": "text", "text": FINAL_TURN_NOTICE.format(max_turns=1)}
    assert r.hit_turn_limit is True


def test_tool_use_on_final_turn_aborts(tmp_path):
    agent, _ = make_agent(tmp_path, [
        resp([tool_use("t1", "list_documents")], "tool_use"),
    ], max_turns=1)
    r = agent.ask("q")
    assert r.error and r.hit_turn_limit is True
    assert r.text.startswith("⚠")


def test_history_is_append_only(tmp_path):
    agent, client = make_agent(tmp_path, [
        resp([tool_use("t1", "list_documents")], "tool_use"),
        resp([text("a1")]),
        resp([text("a2")]),
    ])
    agent.ask("q1")
    first = client.calls[1][1]["messages"]  # state sent on the last call of q1
    agent.ask("q2")
    second = client.calls[2][1]["messages"]
    # the first question's full exchange (incl. its final assistant reply) is a prefix
    assert second[: len(first)] == first
    assert len(second) == len(first) + 2  # + assistant a1 + user q2
    assert second[-2]["role"] == "assistant"
    assert second[-1]["content"][0]["text"] == "q2"


def test_reset_clears_messages_keeps_cost(tmp_path):
    agent, _ = make_agent(tmp_path, [resp([text("a")])])
    agent.ask("q")
    cost = agent.session_cost
    agent.reset()
    assert agent.messages == []
    assert agent.session_cost == cost > 0


def test_cost_and_cache_accounting(tmp_path):
    agent, _ = make_agent(tmp_path, [
        resp([tool_use("t1", "list_documents")], "tool_use", inp=100, out=20, cr=0, cw=1500),
        resp([text("a")], inp=130, out=60, cr=1500, cw=0),
        resp([text("b")], inp=10, out=5, cr=0, cw=0),
    ])
    r = agent.ask("q1")
    assert r.usage == Usage(230, 80, 1500, 1500)
    assert r.cost_usd == pytest.approx(cost_usd("claude-sonnet-5-5", Usage(230, 80, 1500, 1500)))
    assert r.cache_hit is True
    first_cost = r.cost_usd
    r2 = agent.ask("q2")
    assert r2.cache_hit is False
    assert agent.session_cost == pytest.approx(first_cost + r2.cost_usd)
    assert agent.session_usage == Usage(240, 85, 1500, 1500)
    assert agent.question_count == 2


def test_unknown_tool_is_error_and_loop_continues(tmp_path):
    agent, client = make_agent(tmp_path, [
        resp([tool_use("t1", "does_not_exist", x=1)], "tool_use"),
        resp([text("vẫn trả lời")]),
    ])
    r = agent.ask("q")
    assert r.text == "vẫn trả lời"
    assert r.tool_calls[0].is_error is True
    tr = client.calls[1][1]["messages"][-1]["content"][0]
    assert tr["is_error"] is True and tr["tool_use_id"] == "t1"


def test_max_tokens_without_tools_appends_marker(tmp_path):
    agent, _ = make_agent(tmp_path, [resp([text("dở dang")], "max_tokens")])
    r = agent.ask("q")
    assert r.error is None
    assert r.text == "dở dang\n\n(…câu trả lời bị cắt do giới hạn độ dài)"


def test_max_tokens_with_tool_use_aborts(tmp_path):
    agent, _ = make_agent(tmp_path, [
        resp([tool_use("t1", "list_documents")], "max_tokens"),
    ])
    r = agent.ask("q")
    assert r.error and "max_tokens" in r.error
    assert len(agent.messages) == 2


def test_thinking_blocks_passed_back_unchanged(tmp_path):
    think = SimpleNamespace(type="thinking", thinking="hmm", signature="sig")
    content = [think, tool_use("t1", "list_documents")]
    agent, client = make_agent(tmp_path, [
        resp(content, "tool_use"),
        resp([text("ok")]),
    ])
    agent.ask("q")
    assistant = agent.messages[1]
    assert assistant["content"] is content
    assert client.calls[1][1]["messages"][1]["content"][0].type == "thinking"


def test_api_error_result_fields(tmp_path):
    err = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
    agent, _ = make_agent(tmp_path, [
        resp([tool_use("t1", "list_documents")], "tool_use"),
        err,
        resp([text("ổn rồi")]),
    ])
    start_len = len(agent.messages)
    r = agent.ask("câu hỏi")
    assert r.error == "Không kết nối được tới API. Kiểm tra mạng rồi thử lại."
    assert r.text.startswith("⚠")
    assert r.turns == 1
    assert len(r.tool_calls) == 1
    assert len(agent.messages) == start_len + 2
    assert agent.messages[-2] == {"role": "user", "content": [{"type": "text", "text": "câu hỏi"}]}
    assert agent.messages[-1]["role"] == "assistant"
    assert "[Không trả lời được" in agent.messages[-1]["content"][0]["text"]
    r2 = agent.ask("tiếp")
    assert r2.error is None and r2.text == "ổn rồi"
    assert agent.session_usage.input_tokens == 200  # aborted turn's usage is counted


def _status_error(cls, status):
    request = httpx.Request("POST", "https://x")
    response = httpx.Response(status, request=request, json={"error": {"message": "boom"}})
    return cls("boom", response=response, body=None)


@pytest.mark.parametrize("cls,status,expected", [
    (anthropic.AuthenticationError, 401, "ANTHROPIC_API_KEY"),
    (anthropic.PermissionDeniedError, 403, "không có quyền"),
    (anthropic.NotFoundError, 404, "không tồn tại"),
    (anthropic.RateLimitError, 429, "rate limit"),
    (anthropic.BadRequestError, 400, "Yêu cầu không hợp lệ: boom"),
    (anthropic.InternalServerError, 500, "Lỗi máy chủ API (500)"),
])
def test_api_status_error_messages(tmp_path, cls, status, expected):
    agent, _ = make_agent(tmp_path, [_status_error(cls, status)])
    r = agent.ask("q")
    assert r.error and expected in r.error
    assert len(agent.messages) == 2


def test_refusal_aborts_with_category(tmp_path):
    agent, _ = make_agent(tmp_path, [
        resp([], "refusal", stop_details=SimpleNamespace(category="cyber")),
        resp([text("tiếp tục")]),
    ])
    r = agent.ask("q")
    assert "từ chối" in r.error and "cyber" in r.error
    assert r.text.startswith("⚠")
    assert len(agent.messages) == 2
    assert agent.messages[-1]["content"][0]["text"].startswith("[Không trả lời được")
    assert agent.ask("q2").text == "tiếp tục"


def test_refusal_without_category(tmp_path):
    agent, _ = make_agent(tmp_path, [resp([], "refusal")])
    r = agent.ask("q")
    assert r.error == "Mô hình từ chối trả lời yêu cầu này"


def test_jsonl_has_turn_and_tool_call_events(tmp_path):
    agent, _ = make_agent(tmp_path, [
        resp([tool_use("t1", "search_documents", query="hoàn học phí")], "tool_use"),
        resp([text("xong")], cr=1200),
    ])
    agent.ask("q")
    lines = [json.loads(x) for x in (tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    events = [e["event"] for e in lines]
    assert events.count("turn") == 2
    assert events.count("tool_call") == 1
    assert events[0] == "question_start" and events[-1] == "question_end"
    call = next(e for e in lines if e["event"] == "tool_call")
    assert call["name"] == "search_documents" and len(call["result"]) <= 2000
    assert all("ts" in e for e in lines)


def test_logger_console_output(tmp_path):
    console = Console(record=True, width=120, force_terminal=False)
    tools = DocTools(config.DOCS_DIR, tmp_path / "notes", approver=lambda *_: False)
    logger = RunLogger(console, tmp_path / "sub" / "log.jsonl")
    client = FakeClient([
        resp([tool_use("t1", "search_documents", query="hoàn học phí")], "tool_use"),
        resp([text("xong")], cr=1200),
    ])
    Agent(client, tools, logger, max_turns=2).ask("q")
    out = console.export_text()
    assert "Câu hỏi #1" in out
    assert "Lượt 1/2 · stop=tool_use" in out
    assert "↳ tool search_documents" in out
    assert "LƯỢT CUỐI" in out
    assert "Cache hit: có" in out
    assert "Chi phí câu hỏi: $" in out
    assert (tmp_path / "sub" / "log.jsonl").exists()


def test_logger_quiet_modes(tmp_path):
    console = Console(record=True, width=120, force_terminal=False)
    logger = RunLogger(console, tmp_path / "log.jsonl", verbose=False)
    logger.notice("im lặng")
    assert console.export_text() == ""
    assert "im lặng" in (tmp_path / "log.jsonl").read_text(encoding="utf-8")


def test_unmapped_api_error_still_aborts_cleanly(tmp_path):
    err = anthropic.APIError("lạ", httpx.Request("POST", "https://x"), body=None)
    agent, _ = make_agent(tmp_path, [
        resp([tool_use("t1", "list_documents")], "tool_use"),
        err,
        resp([text("vẫn chạy")]),
    ])
    start_len = len(agent.messages)
    r = agent.ask("câu hỏi")
    assert r.error and "APIError" in r.error and r.text.startswith("⚠")
    assert len(agent.messages) == start_len + 2
    assert agent.messages[-2]["role"] == "user"
    assert agent.messages[-1]["content"][0]["text"].startswith("[Không trả lời được")
    events = [json.loads(x)["event"] for x in
              (tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events[-1] == "question_end"
    assert agent.ask("tiếp").text == "vẫn chạy"


def test_unexpected_exception_truncates_history_and_reraises(tmp_path):
    agent, _ = make_agent(tmp_path, [
        resp([tool_use("t1", "list_documents")], "tool_use"),
        RuntimeError("hỏng"),
        resp([text("ổn")]),
    ])
    before = len(agent.messages)
    with pytest.raises(RuntimeError):
        agent.ask("câu hỏi")
    assert len(agent.messages) == before
    assert agent.ask("tiếp").text == "ổn"
    assert len(agent.messages) == before + 2


def test_keyboard_interrupt_truncates_history(tmp_path):
    agent, _ = make_agent(tmp_path, [KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        agent.ask("câu hỏi")
    assert agent.messages == []


def test_empty_final_text_uses_placeholder(tmp_path):
    thinking = SimpleNamespace(type="thinking", thinking="...", signature="s")
    agent, _ = make_agent(tmp_path, [resp([thinking])])
    r = agent.ask("câu hỏi")
    assert r.text == "(Mô hình không trả về nội dung văn bản.)"
    assert r.error is None
