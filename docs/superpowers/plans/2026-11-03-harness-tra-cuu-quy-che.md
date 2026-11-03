# Implementation Plan — Harness tra cứu quy chế nội bộ

Spec: `docs/superpowers/specs/2026-11-03-harness-tra-cuu-quy-che-design.md`

## Global Constraints

- Python 3.12. Virtualenv already exists at `.venv` with `anthropic==2.4.0`, `rich`, `python-dotenv`, `pytest` installed. Run tests with `.venv/Scripts/python.exe -m pytest -q` from the repo root (`C:\Users\Admin\Desktop\HanesVip`). Install anything extra with `uv pip install --python .venv/Scripts/python.exe <pkg>` (avoid extras unless the task says so).
- Tests NEVER call the real Anthropic API. Use fake clients built from `types.SimpleNamespace`.
- All user-facing strings (console output, tool results, error messages) are Vietnamese. Code identifiers, docstrings and comments are English, short.
- All file I/O uses `encoding="utf-8"`.
- Model ids are exact strings, never date-suffixed: default model `claude-sonnet-5-5`.
- Conversation history is append-only. Never mutate or delete earlier messages, except the documented rollback (truncate to the pre-question length, then append a synthetic user/assistant pair).
- Never use `tool_choice` `{"type": "any"}` or `{"type": "tool"}` (400 on Sonnet 5.5). Only omit it (auto) or send `{"type": "none"}`.
- Package layout: `harness/` package at repo root; tests in `tests/`; `pytest.ini` at repo root with `testpaths = tests`.
- Commit after each task with a message `feat(<area>): ...` / `test: ...` / `docs: ...`, ending with the line `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

---

### Task 1: Scaffold, config, pricing, sample documents

Create:

- `requirements.txt`:
  ```
  anthropic>=2.4.0
  rich>=13
  python-dotenv>=1.0
  pytest>=8
  ```
- `.gitignore`: `.venv/`, `__pycache__/`, `*.pyc`, `.env`, `logs/`, `notes/`, `eval/results-*.json`, `.pytest_cache/`, `.superpowers/`.
- `.env.example`:
  ```
  ANTHROPIC_API_KEY=sk-ant-...
  # HARNESS_MODEL=claude-sonnet-5-5
  # HARNESS_MAX_TURNS=6
  ```
- `pytest.ini`: `[pytest]\ntestpaths = tests`
- `harness/__init__.py` (empty docstring only).
- `harness/config.py`:
  - `ROOT = Path(__file__).resolve().parent.parent`
  - `DOCS_DIR = ROOT / "docs_noibo"`, `NOTES_DIR = ROOT / "notes"`, `LOGS_DIR = ROOT / "logs"`, `EVAL_DIR = ROOT / "eval"`
  - `DEFAULT_MODEL = os.getenv("HARNESS_MODEL", "claude-sonnet-5-5")`
  - `DEFAULT_MAX_TURNS = int(os.getenv("HARNESS_MAX_TURNS", "6"))`
  - `MAX_TOKENS = 16000`
  - `EFFORT = "medium"`
- `harness/pricing.py`:
  - `PRICES: dict[str, dict[str, float]]` in USD per million tokens, keys `input`, `output`, `cache_read`, `cache_write`:
    - `claude-sonnet-5-5`: 2.00, 10.00, 0.20, 2.50
    - `claude-sonnet-5`: 2.00, 10.00, 0.20, 2.50
    - `claude-opus-5-5`: 4.00, 20.00, 0.20, 5.00
    - `claude-haiku-5-5`: 0.10, 0.50, 0.01, 0.125
  - `@dataclass class Usage: input_tokens:int=0; output_tokens:int=0; cache_read:int=0; cache_write:int=0` with `__add__` returning a new Usage, and `@classmethod from_api(cls, u)` reading `u.input_tokens`, `u.output_tokens`, `getattr(u, "cache_read_input_tokens", 0) or 0`, `getattr(u, "cache_creation_input_tokens", 0) or 0`.
  - `def cost_usd(model: str, usage: Usage) -> float`: unknown model → use `claude-sonnet-5-5` prices. Formula: sum(tokens × price) / 1_000_000.
- `tests/test_pricing.py`: Usage addition; `from_api` with `None` cache fields → 0; cost for sonnet with (1_000_000 in, 1_000_000 out, 1_000_000 read, 1_000_000 write) == 2+10+0.2+2.5 = 14.7 (use `pytest.approx`); unknown model falls back to sonnet price.
- `docs_noibo/` — six Markdown files for the fictional "Học viện HanesVip". Each file starts with `# <title>` and has several `##` sections written as realistic Vietnamese policy text (each file ~1500–3000 characters). They MUST contain these exact facts (wording can vary, the numbers/keywords must appear verbatim):
  1. `quy-che-hoc-vu.md` — "Quy chế học vụ": tốt nghiệp khi điểm trung bình tích lũy từ **6.5**/10 trở lên và hoàn thành dự án cuối khóa; xếp loại Giỏi ≥ 8.5, Khá ≥ 7.0, Trung bình ≥ 5.0; mỗi môn được thi lại tối đa **2 lần**, phí thi lại **300.000đ**/lần; cảnh báo học vụ khi điểm trung bình dưới 5.0 hai kỳ liên tiếp.
  2. `chinh-sach-hoan-hoc-phi.md` — "Chính sách hoàn học phí": rút trước khai giảng từ 7 ngày trở lên: hoàn **100%** (trừ phí giữ chỗ **500.000đ**); rút trong vòng 7 ngày trước khai giảng: hoàn **70%**; rút trong 2 tuần đầu của khóa học: hoàn **50%**; sau 2 tuần: **không hoàn**. Hồ sơ: đơn đề nghị hoàn phí, biên lai/hóa đơn đóng học phí, CCCD bản sao. Xử lý trong **10 ngày làm việc**.
  3. `quy-dinh-diem-danh.md` — "Quy định điểm danh": vắng quá **20%** tổng số buổi của môn thì không được dự thi cuối môn; đi muộn quá 15 phút tính **0.5 buổi vắng** (nửa buổi); xin phép nghỉ trên hệ thống LMS trước **24 giờ**.
  4. `quy-trinh-bao-luu.md` — "Quy trình bảo lưu": bảo lưu tối đa **6 tháng**, chỉ **1 lần** trong toàn khóa; miễn phí bảo lưu nếu có lý do sức khỏe/giấy xác nhận, ngược lại phí **1.000.000đ**; nộp đơn trước ít nhất **5 ngày làm việc**; khi quay lại học viên vào lớp khai giảng gần nhất.
  5. `chinh-sach-hoc-bong.md` — "Chính sách học bổng": học bổng khuyến học **30%** học phí cho học viên có điểm trung bình từ **8.5** và không vắng buổi nào không phép; học bổng tài năng **50%** cho **3** học viên có điểm đầu vào cao nhất mỗi khóa; các học bổng **không được cộng dồn**; bị thu hồi học bổng nếu bị cảnh báo học vụ.
  6. `noi-quy-lop-hoc.md` — "Nội quy lớp học": ca sáng 8:30–11:30, ca chiều 13:30–16:30, ca tối 18:30–21:30; không ăn uống trong phòng lab; đạo văn bài tập: lần 1 nhận điểm 0 cho bài đó, lần 2 bị **đình chỉ** môn học.
  None of the documents mention ký túc xá (dormitory) — this is the eval's unanswerable question.

Verify: `pytest -q` passes. Commit.

---

### Task 2: RAG index (`harness/rag.py`)

Implement, with no third-party dependencies:

- `def normalize(text: str) -> str`: lowercase; replace `đ`→`d`; Unicode NFD and drop combining marks (`unicodedata.category(c) == "Mn"`); return the result.
- `def tokenize(text: str) -> list[str]`: `normalize`, then `re.findall(r"[a-z0-9]+(?:[.,][0-9]+)?", ...)` (so `6.5`, `300.000` stay one token); return unigrams plus bigrams joined by `_` of consecutive unigrams (e.g. `["hoc","phi","hoc_phi"]` for "học phí").
- `@dataclass(frozen=True) class Chunk: id: str; doc: str; heading: str; text: str`
  - `id` = `f"{doc}#{n}"`, n starting at 1 per document.
  - `heading` = heading path joined with ` › ` (e.g. `Chính sách hoàn học phí › Mức hoàn phí`).
- `def chunk_markdown(doc: str, text: str, max_chars: int = 1200) -> list[Chunk]`: split at lines starting with `#`, `##`, `###`; track the heading path by level; the chunk text is the section body (heading line excluded), stripped; skip empty bodies; when a body exceeds `max_chars`, split at blank-line paragraph boundaries into pieces of ≤ `max_chars` (a single oversized paragraph stays whole), each piece its own Chunk sharing the heading.
- `class BM25Index`:
  - `__init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75)`: index tokens of `heading + "\n" + text` per chunk.
  - `search(self, query: str, top_k: int = 4) -> list[tuple[Chunk, float]]`: standard BM25 with idf = `log(1 + (N - df + 0.5) / (df + 0.5))`; return only score > 0, sorted descending, at most `top_k`.
- `def build_index(docs_dir: Path) -> tuple[BM25Index, dict[str, str]]`: read all `*.md` (sorted by name) → returns the index and a dict `{filename: full_text}`.

Tests `tests/test_rag.py` (use `tmp_path` fixtures with small Markdown strings, not the real docs, except one test):
- `normalize("Học phí ĐÀO TẠO")` == `"hoc phi dao tao"`.
- tokenize keeps `6.5` and `300.000` and produces the bigram `hoc_phi`.
- chunk_markdown builds heading paths with ` › `, numbers ids from 1, skips empty sections, splits a long body.
- BM25: the chunk containing the query term ranks first; a query with no matching terms returns `[]`; unaccented query `"hoan hoc phi"` finds the accented chunk.
- Against the real `docs_noibo/` (built in Task 1): `search("rút học trước khai giảng hoàn bao nhiêu")` top result's `doc` == `chinh-sach-hoan-hoc-phi.md`.

Commit.

---

### Task 3: Tools (`harness/tools.py`)

- `class ToolError(Exception)`: expected, user-explainable failure.
- `@dataclass class ToolResult: content: str; is_error: bool; duration_ms: float`
- `TOOL_SCHEMAS: list[dict]` — a module-level constant in this exact order: `list_documents`, `search_documents`, `read_document`, `save_note`. Each has `name`, `description` (Vietnamese, 1–3 sentences saying when to use it), and `input_schema` (`type: object`, `properties`, `required`, `additionalProperties: false`):
  - `list_documents`: no properties, `required: []`.
  - `search_documents`: `query` (string, required), `top_k` (integer, optional, 1–8, default 4). Description says it searches by BM25 over document sections and should be used first.
  - `read_document`: `filename` (string, required, e.g. `quy-che-hoc-vu.md`), `section` (string, optional; heading keyword to read only matching sections).
  - `save_note`: `title` (string, required), `content` (string, required). Description says it WRITES a file to `notes/`, only use it when the user explicitly asks to save, and requires user approval.
- `Approver = Callable[[str, dict], bool]`
- `class DocTools`:
  - `__init__(self, docs_dir: Path, notes_dir: Path, approver: Approver)`: builds the index via `rag.build_index(docs_dir)`; stores `self.docs: dict[str,str]`; `self.fault_next = False`.
  - `execute(self, name: str, tool_input: dict) -> ToolResult`: measures duration with `time.perf_counter`. Order:
    1. If `self.fault_next`: reset it to False and raise `RuntimeError("Lỗi giả lập (fault injection) — dùng để kiểm thử xử lý lỗi")` inside the try so it is caught by step 4.
    2. Unknown name → `ToolResult(f"Tool '{name}' không tồn tại. Các tool hợp lệ: list_documents, search_documents, read_document, save_note.", True, …)`.
    3. Validate input: required keys present and of the right type (str / int); bad input → is_error with a message naming the field, e.g. `"Thiếu tham số bắt buộc 'query' (kiểu string)."`.
    4. Dispatch to `_list_documents`, `_search_documents`, `_read_document`, `_save_note`. `ToolError` → `ToolResult(str(e), True)`. Any other exception → `ToolResult(f"Lỗi nội bộ khi chạy tool {name}: {type(e).__name__}: {e}", True)`. Never raise.
  - `_list_documents()`: one line per doc, `- {filename}: {title from first '# ' line} ({len} ký tự)`; header line `Có {n} tài liệu:`.
  - `_search_documents(query, top_k=4)`: clamp top_k into 1..8; empty/whitespace query → `ToolError("Câu truy vấn rỗng.")`; no hits → plain (non-error) `"Không tìm thấy đoạn nào khớp với '{query}'. Thử từ khóa khác hoặc dùng list_documents."`; else a block per hit: `[{chunk.id}] {chunk.doc} › {chunk.heading} (điểm {score:.2f})\n{text[:500]}` separated by blank lines.
  - `_read_document(filename, section=None)`: accept only a plain filename present in `self.docs` (reject anything containing `/`, `\\` or `..` with ToolError `"Tên file không hợp lệ: '{filename}'."`); missing → `ToolError(f"Không tìm thấy tài liệu '{filename}'. Dùng list_documents để xem danh sách.")`. With `section`: return chunks of that doc whose `normalize(heading)` contains `normalize(section)`, formatted `## {heading}\n{text}`; none match → ToolError listing available headings. Without section: full text; if longer than 8000 chars, truncate and append `\n…(đã cắt bớt, dùng tham số section để đọc từng mục)`.
  - `_save_note(title, content)`: call `self.approver("save_note", {"title": title, "content": content})`. False → return (non-error) `"Người dùng đã TỪ CHỐI lưu ghi chú. Không có file nào được ghi."`. True → `notes_dir.mkdir(parents=True, exist_ok=True)`; filename = `normalize(title)` with non `[a-z0-9]` runs replaced by `-`, stripped of `-`, max 60 chars, fallback `ghi-chu`, plus `.md`; if it exists append `-2`, `-3`…; write `# {title}\n\n{content}\n`; return `f"Đã lưu ghi chú vào notes/{fname}"`.

Tests `tests/test_tools.py` (use the real `docs_noibo/` for docs, `tmp_path` for notes):
- schemas: names in the exact order above; every schema has `additionalProperties: False`.
- list_documents lists 6 docs.
- search finds `chinh-sach-hoan-hoc-phi.md` for "hoàn học phí"; empty query → is_error.
- read_document full, by section, missing file → is_error with "Không tìm thấy", path traversal `../x.md` → is_error.
- unknown tool → is_error; missing required param → is_error mentioning the param.
- fault_next → is_error containing "Lỗi giả lập", and the flag is reset (next call succeeds).
- an approver that raises → is_error "Lỗi nội bộ" (execute never raises).
- save_note denied → no file written; approved → file exists with content; duplicate title → `-2` suffix.

Commit.

---

### Task 4: Logger and agent loop (`harness/logger.py`, `harness/agent.py`)

**`harness/logger.py`**

- `class RunLogger`:
  - `__init__(self, console: rich.console.Console | None, jsonl_path: Path | None, verbose: bool = True)`; creates the parent dir of `jsonl_path` when given. `console=None` or `verbose=False` → nothing printed to the console (still writes JSONL).
  - `_write(event: str, **data)`: append one JSON line `{"ts": iso8601, "event": event, ...}` (`ensure_ascii=False`, `default=str`).
  - `question_start(index: int, question: str)`: rule line `Câu hỏi #{index}`.
  - `turn(turn: int, max_turns: int, stop_reason: str, usage: Usage, cost: float, model: str, final_turn: bool)`: one line like `Lượt 2/6 · stop=tool_use · in=120 out=85 cache_read=1830 cache_write=0 · $0.00123` — highlight `cache_read` in green when > 0; append `· LƯỢT CUỐI` when `final_turn`.
  - `tool_call(name: str, tool_input: dict, result: ToolResult)`: prints `↳ tool {name}` + input as compact JSON + result first 300 chars (red and prefixed `LỖI:` when `is_error`) + `({duration_ms:.0f} ms)`. JSONL stores the result truncated to 2000 chars.
  - `notice(message: str, level: str = "info")`: level `info` cyan, `warn` yellow, `error` red. Always printed when the console is set (even if `verbose=False`)? — No: only when verbose; the CLI prints user-facing notices itself.
  - `question_end(result: "AnswerResult")`: summary table/line: số lượt, số tool call, tokens (in/out/cache_read/cache_write), `Chi phí câu hỏi: ${cost:.5f}`, `Cache hit: có/không`.

**`harness/agent.py`**

- `SYSTEM_PROMPT`: a module constant, Vietnamese, at least 2,500 characters (so that system + tools exceed the 512-token minimum cacheable prefix). Must be static (no dates, no random values). Content: role (trợ lý tra cứu quy chế nội bộ của Học viện HanesVip); working method (search_documents first, read_document for full detail when needed, may make several tool calls, at most a few searches); answer rules (only from documents, cite sources as `[tên-file › mục]`, never invent numbers, say clearly when the documents do not contain the answer — use the phrase "không tìm thấy thông tin" — answer in concise Vietnamese with bullet points when helpful); follow-up questions use earlier conversation; save_note only when the user explicitly asks, and the user may refuse; when a tool returns an error, try another approach (different keywords, list_documents) or explain to the user; when told it is the last turn, answer immediately with the information collected and state what is missing.
- `FINAL_TURN_NOTICE = "[HỆ THỐNG] Đây là lượt cuối cùng (giới hạn {max_turns} lượt). Không gọi thêm tool. Hãy trả lời ngay bằng thông tin đã thu thập; nếu chưa đủ, nói rõ phần nào còn thiếu."`
- `FALLBACK_BETA = "server-side-fallback-2026-07-01"`
- `@dataclass class ToolCallRecord: name: str; input: dict; result: str; is_error: bool`
- `@dataclass class AnswerResult: text: str; turns: int; usage: Usage; cost_usd: float; tool_calls: list[ToolCallRecord]; hit_turn_limit: bool = False; error: str | None = None` and property `cache_hit -> bool` (`usage.cache_read > 0`).
- `class Agent`:
  - `__init__(self, client, tools: DocTools, logger: RunLogger, model: str = config.DEFAULT_MODEL, max_turns: int = config.DEFAULT_MAX_TURNS, use_fallbacks: bool = True)`; `self.messages: list = []`; `self.question_count = 0`; `self.session_usage = Usage()`; `self.session_cost = 0.0`.
  - `reset()`: clears `messages` (new list), keeps session cost.
  - `_create(self, final_turn: bool)`: builds kwargs:
    ```python
    kwargs = dict(
        model=self.model,
        max_tokens=config.MAX_TOKENS,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=TOOL_SCHEMAS,
        messages=self.messages,
        cache_control={"type": "ephemeral"},
        output_config={"effort": config.EFFORT},
    )
    if final_turn:
        kwargs["tool_choice"] = {"type": "none"}
    if self.use_fallbacks:
        return self.client.beta.messages.create(**kwargs, betas=[FALLBACK_BETA], fallbacks="default")
    return self.client.messages.create(**kwargs)
    ```
  - `ask(self, question: str) -> AnswerResult`:
    1. `max_turns = max(1, self.max_turns)`; `self.question_count += 1`; `logger.question_start(...)`; `start_len = len(self.messages)`.
    2. Append `{"role": "user", "content": [{"type": "text", "text": question}]}`; if `max_turns == 1` also append a second text block `FINAL_TURN_NOTICE.format(max_turns=1)` to that same content list.
    3. For `turn` in `1..max_turns`: `final = turn == max_turns`. Call `_create(final)` inside try/except for, in this order: `anthropic.AuthenticationError` → "API key không hợp lệ hoặc chưa được cấu hình (ANTHROPIC_API_KEY)."; `anthropic.PermissionDeniedError` → "API key không có quyền dùng model này."; `anthropic.NotFoundError` → f"Model '{model}' không tồn tại hoặc không khả dụng."; `anthropic.RateLimitError` → "Bị giới hạn tốc độ (rate limit). Vui lòng thử lại sau ít phút."; `anthropic.BadRequestError` → f"Yêu cầu không hợp lệ: {e.message}"; `anthropic.APIStatusError` → f"Lỗi máy chủ API ({e.status_code}). Vui lòng thử lại."; `anthropic.APIConnectionError` (covers timeouts) → "Không kết nối được tới API. Kiểm tra mạng rồi thử lại.". On error: `logger.notice(msg, "error")` and return `self._abort(start_len, question, msg, ...)`.
    4. Per response: `usage = Usage.from_api(resp.usage)`; `cost = cost_usd(resp.model or self.model, usage)`; accumulate into question totals and `self.session_usage` / `self.session_cost`; `logger.turn(...)`.
    5. `stop_reason == "refusal"`: msg = "Mô hình từ chối trả lời yêu cầu này" + (f" (loại: {category})" when `getattr(resp, "stop_details", None)` has a category) → `_abort`.
    6. Append `{"role": "assistant", "content": resp.content}` (the content list unchanged — includes thinking/fallback blocks).
    7. `tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]`.
    8. If `stop_reason == "max_tokens"` and `tool_uses` → `_abort(... "Câu trả lời bị cắt do vượt giới hạn max_tokens.")` (the abort truncates the appended assistant message too).
    9. If no `tool_uses` (end_turn, max_tokens without tools, pause_turn, …): text = join of `b.text` for text blocks (`"\n".join`, stripped); if `stop_reason == "max_tokens"` append `"\n\n(…câu trả lời bị cắt do giới hạn độ dài)"`; build the result with `hit_turn_limit = final and turn > 1 or (final and max_turns == 1)` — i.e. True whenever the final turn's forcing was applied; when `hit_turn_limit`, `logger.notice(f"Đã dùng hết {max_turns} lượt — câu trả lời dựa trên thông tin đã thu thập, có thể chưa đầy đủ.", "warn")`. Return.
    10. If `tool_uses` and `final` (should not happen because of `tool_choice: none`): `_abort(... "Mô hình vẫn muốn gọi tool ở lượt cuối; dừng lại theo giới hạn.")`, with `hit_turn_limit=True`.
    11. Otherwise execute each tool_use in order: `res = self.tools.execute(b.name, dict(b.input or {}))`; `logger.tool_call(...)`; record a `ToolCallRecord` (result truncated to 2000 chars); build `{"type": "tool_result", "tool_use_id": b.id, "content": res.content, "is_error": res.is_error}`. If `turn + 1 == max_turns`, append one more block `{"type": "text", "text": FINAL_TURN_NOTICE.format(max_turns=max_turns)}` after the tool_result blocks. Append `{"role": "user", "content": blocks}` and continue.
  - `_abort(self, start_len, question, message, turns, usage, cost, tool_calls, hit_turn_limit=False) -> AnswerResult`: `del self.messages[start_len:]`; append `{"role": "user", "content": [{"type": "text", "text": question}]}` and `{"role": "assistant", "content": [{"type": "text", "text": f"[Không trả lời được: {message}]"}]}`; return `AnswerResult(text=f"⚠ {message}", ..., error=message)`. `logger.question_end` is called for every return path (normal and abort).

Tests `tests/test_agent.py` — build a `FakeClient` whose `messages.create` and `beta.messages.create` pop scripted responses from a list and record a deep copy (`copy.deepcopy`) of each call's kwargs; responses are `SimpleNamespace(content=[...], stop_reason=..., usage=SimpleNamespace(input_tokens=..., output_tokens=..., cache_read_input_tokens=..., cache_creation_input_tokens=...), model="claude-sonnet-5-5", stop_details=None)`; blocks are `SimpleNamespace(type="text", text=...)` / `SimpleNamespace(type="tool_use", id=..., name=..., input={...})`. A fake raising error can be scripted by putting an exception instance in the list. Use a real `DocTools` (real docs, tmp notes dir, deny approver) and `RunLogger(None, tmp_path/"log.jsonl")`. Cover:
- multi-turn: tool_use → tool_use → end_turn gives `turns == 3`, two tool records, final text; request #2 messages contain the tool_result with the matching `tool_use_id`.
- kwargs: system block has `cache_control`; top-level `cache_control` present; `tools` is `TOOL_SCHEMAS`; `output_config == {"effort": "medium"}`; with `use_fallbacks=True` the beta create is used with `betas=["server-side-fallback-2026-07-01"]` and `fallbacks="default"`; with `use_fallbacks=False` plain create without those keys; no `tool_choice` on non-final turns.
- turn limit: `max_turns=2`, scripted tool_use then end_turn → request #2 has `tool_choice == {"type": "none"}`, its last user message ends with the FINAL_TURN_NOTICE text block, `hit_turn_limit` True. `max_turns=1` → first request has `tool_choice none` and the notice block.
- history: two `ask` calls → the second request's messages start with the exact messages of the first question (prefix equality on deep copies), i.e. append-only.
- cost: usage summed across turns; `cost_usd` matches `pricing.cost_usd` of the sum; `cache_hit` True when any turn had cache_read > 0; `session_cost` accumulates across asks.
- tool error: unknown tool name scripted → tool_result `is_error True`, loop continues to the end_turn answer.
- API error: scripted `anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))` on turn 2 → result.error set, text starts with "⚠", messages rolled back to start_len + synthetic pair (len == start_len + 2, last is assistant text with "[Không trả lời được"), and a following `ask` still works.
- refusal → error result with "từ chối", history rolled back + pair.
- logger: the JSONL file contains `turn` and `tool_call` events.

Commit.

---

### Task 5: CLI and eval runner

**`harness/cli.py`** + **`harness/__main__.py`** (`from harness.cli import main; main()` guarded by `if __name__ == "__main__"`)

- `main(argv=None)`:
  - On Windows call `sys.stdout.reconfigure(encoding="utf-8")` and the same for stderr (guard with `hasattr`).
  - `load_dotenv(config.ROOT / ".env")`.
  - argparse: `--model` (default `config.DEFAULT_MODEL`), `--max-turns` (int, default `config.DEFAULT_MAX_TURNS`), `--no-fallbacks` (store_true), `--quiet` (store_true: hide per-turn logs).
  - If neither `ANTHROPIC_API_KEY` nor `ANTHROPIC_AUTH_TOKEN` is set: print a red message "Chưa có ANTHROPIC_API_KEY. Tạo file .env từ .env.example rồi điền key." and return exit code 1.
  - Build `Console()`, `RunLogger(console, config.LOGS_DIR / f"session-{datetime.now():%Y%m%d-%H%M%S}.jsonl", verbose=not args.quiet)`, `DocTools(config.DOCS_DIR, config.NOTES_DIR, approver=console_approver(console))`, `anthropic.Anthropic()`, `Agent(...)`.
  - Banner panel: title "Trợ lý tra cứu quy chế nội bộ — Học viện HanesVip", lines: model, max turns, số tài liệu, đường dẫn file log, and "Gõ /help để xem lệnh."
  - REPL: `console.input("[bold cyan]Bạn> [/]")`; `EOFError`/`KeyboardInterrupt` → goodbye and exit 0. Empty → continue. Commands:
    - `/help`: list the commands.
    - `/exit` or `/quit`: print session cost, exit 0.
    - `/reset`: `agent.reset()`, print "Đã xóa lịch sử hội thoại."
    - `/maxturns N`: set `agent.max_turns` (int ≥ 1; invalid → yellow usage message).
    - `/fault`: set `tools.fault_next = True`, print "Lần gọi tool kế tiếp sẽ bị lỗi giả lập."
    - `/cost`: print `session_usage` and `session_cost` (5 decimals).
    - unknown `/x` → "Lệnh không hợp lệ. Gõ /help."
  - Otherwise: `result = agent.ask(text)` wrapped in `try/except Exception as e` → red "Lỗi không mong muốn: {type}: {e}. Phiên vẫn tiếp tục." Print the answer in a `Panel(Markdown(result.text), title="Trợ lý")` (border red when `result.error`, yellow when `hit_turn_limit`, green otherwise), then one dim line `{turns} lượt · {n} tool call · ${cost:.5f} · cache hit: có/không`.
- `console_approver(console) -> Approver`: prints a yellow panel "Yêu cầu duyệt thao tác GHI" showing the tool name, title and the first 500 chars of content, asks `console.input("Cho phép? (y/n) ")`, returns True only for `y`/`yes`/`c`/`co`/`có` (case-insensitive, stripped).

**`harness/eval.py`** (`python -m harness.eval`)

- `def normalize_for_match(s: str) -> str`: `rag.normalize(s)`, then remove spaces before/after `.` and `,` and collapse whitespace.
- `def grade(answer: str, must_include: list) -> tuple[bool, list[str]]`: each item is a string or a list of alternative strings; an item matches when any alternative (normalized) is a substring of the normalized answer; returns (all matched, list of missing items as display strings).
- `def retrieval_hit(source: str | None, tool_calls: list[ToolCallRecord]) -> bool | None`: None when source is None; else True if `source` appears in any record's `input` (json-dumped) or `result`.
- `main(argv=None)`: UTF-8 stdout fix + `load_dotenv` + key check as in CLI; args `--limit N`, `--model`, `--max-turns`; load `config.EVAL_DIR / "questions.jsonl"`; for each question create a fresh `Agent` (new history) with `DocTools(..., approver=lambda *_: False)` and `RunLogger(None, config.LOGS_DIR / "eval-<ts>.jsonl", verbose=False)`; print progress line per question; collect rows; print a rich Table (ID, Kết quả ✅/❌, Retrieval ✅/❌/–, Lượt, Chi phí, Thiếu); then summary: `Độ chính xác: {passed}/{total} ({pct:.0f}%)`, `Retrieval hit: x/y`, `Tổng chi phí: ${:.4f}`, `Trung bình lượt: {:.1f}`; write `config.EVAL_DIR / f"results-{ts}.json"` with all rows. Exceptions per question are caught and recorded as failures.
- `eval/questions.jsonl` — exactly these 10 lines (JSON, UTF-8, `ensure_ascii=False`), fields `id`, `question`, `must_include`, `source`:
  1. `q01` "Muốn tốt nghiệp cần điểm trung bình tích lũy tối thiểu bao nhiêu?" `[["6.5","6,5"]]` `quy-che-hoc-vu.md`
  2. `q02` "Nếu rút học 3 ngày trước khai giảng thì được hoàn bao nhiêu phần trăm học phí?" `["70%"]` `chinh-sach-hoan-hoc-phi.md`
  3. `q03` "Đi học muộn 20 phút thì bị tính như thế nào?" `[["0.5","0,5","nửa buổi"]]` `quy-dinh-diem-danh.md`
  4. `q04` "Học viên được bảo lưu tối đa bao lâu?" `["6 tháng"]` `quy-trinh-bao-luu.md`
  5. `q05` "Phí thi lại một lần là bao nhiêu?" `[["300.000","300,000","300000","300 nghìn"]]` `quy-che-hoc-vu.md`
  6. `q06` "Điều kiện để nhận học bổng khuyến học là gì và được bao nhiêu phần trăm?" `[["8.5","8,5"], "30%"]` `chinh-sach-hoc-bong.md`
  7. `q07` "Vắng quá bao nhiêu phần trăm số buổi thì không được thi cuối môn?" `["20%"]` `quy-dinh-diem-danh.md`
  8. `q08` "Học viên đạo văn bài tập lần thứ hai sẽ bị xử lý thế nào?" `["đình chỉ"]` `noi-quy-lop-hoc.md`
  9. `q09` "Có được nhận cùng lúc học bổng khuyến học và học bổng tài năng không?" `[["không được cộng dồn","không cộng dồn","không được nhận cùng lúc","không thể"]]` `chinh-sach-hoc-bong.md`
  10. `q10` "Học viện có ký túc xá cho học viên không?" `[["không tìm thấy","không có thông tin","chưa có thông tin","không đề cập"]]` `null`

Tests `tests/test_eval.py`: grade with accents/decimal comma/alternatives/missing items; normalize_for_match; retrieval_hit True/False/None; questions.jsonl has 10 valid rows with unique ids and every non-null source exists in `docs_noibo/`. Tests `tests/test_cli.py`: `console_approver` with a fake console (`input` returns "y" → True, "n" → False, "Có" → True); `main([])` with both API key env vars removed (monkeypatch, and patch `load_dotenv` to a no-op) returns 1.

Commit.

---

### Task 6: README and final smoke check

- `README.md` in Vietnamese:
  1. Title + one-paragraph problem statement (bài toán thật: giáo vụ trả lời lặp lại câu hỏi quy chế).
  2. Cài đặt: `uv venv` / `python -m venv .venv`, `pip install -r requirements.txt`, copy `.env.example` → `.env`, fill key; run `python -m harness`, `python -m harness.eval`, `python -m pytest -q`.
  3. Kiến trúc: the module table from the spec + a short ASCII flow of the agent loop.
  4. Bảng "Yêu cầu → cách đáp ứng → file:hàm" covering the 7 mandatory requirements and the 3 advanced parts (RAG, duyệt ghi, bộ kiểm thử) and the refusal fallback.
  5. Lệnh trong REPL (/help, /reset, /maxturns, /fault, /cost, /exit).
  6. Ví dụ log (a short illustrative excerpt, labeled "minh họa").
  7. "Kịch bản quay video (≤ 5 phút)" — the 5 steps from spec §7 with the exact questions/commands to type.
  8. Thay tài liệu thật: drop Markdown files into `docs_noibo/`, update `eval/questions.jsonl`.
- Smoke check (no API key needed): `.venv/Scripts/python.exe -m pytest -q` all pass; `.venv/Scripts/python.exe -c "import harness.cli, harness.eval, harness.agent"` imports cleanly; `python -m harness` with no key prints the red key message and exits 1.

Commit.
