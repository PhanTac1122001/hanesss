# Harness "Trợ lý tra cứu quy chế nội bộ"

Bài tập Buổi 2 · Xây dựng harness · Python CLI, vòng lặp agent viết tay trên Anthropic Messages API.

## 1. Bài toán

Giáo vụ và học viên của một học viện đào tạo CNTT (dữ liệu mẫu hư cấu: "Học viện HanesVip") hay hỏi đi hỏi lại những câu về quy chế: điều kiện tốt nghiệp, hoàn học phí, điểm danh, bảo lưu, học bổng, nội quy. Câu trả lời nằm rải rác trong nhiều file Markdown, và người trả lời phải mở từng file để tìm. Harness này là một trợ lý dòng lệnh: nó tìm đoạn liên quan (BM25), đọc tài liệu, trả lời bằng tiếng Việt kèm trích nguồn `[tên-file › mục]`, và nhớ ngữ cảnh các câu hỏi trước trong cùng phiên. Muốn dùng tài liệu thật, chỉ cần thay file trong `docs_noibo/`, không phải sửa code.

## 2. Cài đặt và chạy

Cần Python 3.12 và `anthropic>=2.4.0`. Chọn một trong các cách tạo môi trường ảo:

**Windows PowerShell** (mỗi lệnh một dòng, không dùng `&&`):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

**Windows Git Bash**:

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env
```

**macOS/Linux**:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Hoặc dùng `uv`: `uv venv` rồi `uv pip install -r requirements.txt`.

Sau đó điền `ANTHROPIC_API_KEY` vào file `.env` và chạy:

```bash
python -m harness           # mở REPL hỏi đáp
python -m harness.eval      # chạy bộ 10 câu hỏi kiểm thử
python -m pytest -q         # chạy test (không gọi API thật)
```

Không muốn kích hoạt môi trường ảo thì gọi thẳng Python trong đó, ví dụ trên Windows: `.venv\Scripts\python -m harness` (macOS/Linux: `.venv/bin/python -m harness`).

| Tùy chọn | Ý nghĩa |
|----------|---------|
| Model mặc định | `claude-sonnet-5-5`. Đổi bằng biến môi trường `HARNESS_MODEL` hoặc `--model <id>` |
| `--max-turns N` / `HARNESS_MAX_TURNS` | Số lượt tối đa cho mỗi câu hỏi (mặc định 6) |
| Server-side fallback khi bị từ chối | Bật mặc định. Tắt bằng `--no-fallbacks` |
| `--quiet` | Ẩn log từng lượt trên console (vẫn ghi JSONL) |

Lưu ý: `python -m harness.eval` gọi API thật cho 10 câu hỏi nên tốn tiền (in ra tổng chi phí ở cuối). Thêm `--limit N` để chạy ít câu hơn. Khi chưa có key, cả hai lệnh in thông báo đỏ và thoát với mã 1.

## 3. Kiến trúc

```
harness/
  config.py     cấu hình: model, max_turns, đường dẫn
  pricing.py    bảng giá $/MTok + Usage + cost_usd()
  rag.py        chunk Markdown theo heading + BM25Index
  tools.py      schema 4 tool + DocTools.execute() (bắt mọi lỗi, duyệt ghi, giả lập lỗi)
  logger.py     RunLogger: in ra console (rich) + ghi JSONL
  agent.py      Agent: lịch sử, vòng lặp, giới hạn lượt, cache, xử lý lỗi API
  cli.py        REPL: /help /exit /reset /maxturns N /fault /cost
  __main__.py   python -m harness
  eval.py       python -m harness.eval
docs_noibo/     6 file Markdown quy chế mẫu
eval/questions.jsonl   10 câu hỏi + từ khóa kỳ vọng
tests/          pytest, dùng client giả (không gọi API thật)
```

Vòng lặp agent cho một câu hỏi (`Agent.ask`):

```
 câu hỏi ──► append user message
                │
      ┌─────────▼──────────┐   lỗi API / refusal / max_tokens giữa tool_use
      │ lượt i = 1..max    │──────────────► rollback lịch sử (_abort) + thông báo tiếng Việt
      │ gọi API (_create)  │
      └─────────┬──────────┘
                │ log lượt (stop_reason, token, cache, $)
        có tool_use?
        ├── không ──► trả lời cuối (end_turn) ──► log tổng chi phí câu hỏi
        └── có ─────► DocTools.execute (lỗi ⇒ is_error=true) ─► log tool
                      append tool_result ─► lượt kế
                      (lượt max_turns: tool_choice=none + thông báo "[HỆ THỐNG] lượt cuối")
```

## 4. Yêu cầu → cách đáp ứng → file:hàm

| # | Yêu cầu | Cách đáp ứng | File:hàm |
|---|---------|--------------|----------|
| 1 | ≥ 2 tool tự viết | 4 tool: `list_documents`, `search_documents` (BM25), `read_document`, `save_note` (có duyệt) | `harness/tools.py`: `TOOL_SCHEMAS`, `DocTools._list_documents/_search_documents/_read_document/_save_note` |
| 2 | Agent loop nhiều lượt | Gọi API, chạy tool, trả `tool_result`, gọi lại tới khi không còn `tool_use` | `harness/agent.py`: `Agent.ask` |
| 3 | Giới hạn lượt, lượt cuối phải trả lời | Lượt `max_turns` gửi `tool_choice: {"type": "none"}`; lượt ngay trước đó chèn text "[HỆ THỐNG] Đây là lượt cuối…" vào khối `tool_result`. Nếu `max_turns=1` thì thông báo nằm cùng tin nhắn câu hỏi. Nếu vẫn chạm giới hạn, `hit_turn_limit=True` và CLI cảnh báo vàng. Không dùng `tool_choice` kiểu `any`/`tool` (Sonnet 5.5 trả lỗi 400) | `harness/agent.py`: `Agent._create` (tool_choice), `Agent.ask` (`FINAL_TURN_NOTICE`, `hit_turn_limit`) |
| 4 | Lịch sử | `Agent.messages` giữ suốt phiên, chỉ thêm vào cuối. Nội dung assistant (kể cả thinking) được gửi lại nguyên vẹn. `/reset` xóa lịch sử | `harness/agent.py`: `Agent.messages`, `Agent.reset`; `harness/cli.py`: `/reset` |
| 5 | Cache | System prompt và tool cố định, `cache_control` trên khối system và cache tự động ở cấp request. Log in `cache_read`/`cache_write` mỗi lượt (màu xanh khi `cache_read > 0`) | `harness/agent.py`: `Agent._create`; `harness/logger.py`: `RunLogger.turn` |
| 6 | Observability | Mỗi lượt: số lượt, `stop_reason`, token in/out/cache read/cache write, chi phí. Mỗi tool call: tên, input, kết quả, thời gian ms, lỗi. Cuối câu hỏi: tổng chi phí. Mọi sự kiện ghi thêm vào `logs/session-*.jsonl` | `harness/logger.py`: `RunLogger.turn/tool_call/question_end/_write`; `harness/pricing.py`: `cost_usd` |
| 7 | Xử lý lỗi | Lỗi tool (tên lạ, input sai, `ToolError`, exception bất kỳ) trả `is_error=true` rồi vòng lặp chạy tiếp. Lỗi API, refusal, `max_tokens` giữa `tool_use`: thông báo tiếng Việt, rollback lịch sử về trước câu hỏi rồi thêm cặp user/assistant tổng hợp, phiên không dừng. Exception bất ngờ hoặc Ctrl-C giữa câu hỏi: lịch sử được cắt về trước câu hỏi, REPL tiếp tục | `harness/tools.py`: `DocTools.execute`, `_validate`; `harness/agent.py`: `Agent._api_error_message`, `Agent._abort` |
| Nâng cao | RAG | Chunk theo heading Markdown, token hóa không dấu + bigram, chấm điểm BM25 thuần Python | `harness/rag.py`: `chunk_markdown`, `BM25Index.search`, `build_index` |
| Nâng cao | Duyệt trước khi ghi | `save_note` gọi `approver` trước khi ghi file; từ chối thì không ghi gì. REPL hỏi y/n; eval luôn từ chối | `harness/tools.py`: `DocTools._save_note`; `harness/cli.py`: `console_approver`; `harness/eval.py`: `approver=lambda *_: False` |
| Nâng cao | Bộ kiểm thử | 77 test không gọi API thật (client giả). Bộ eval 10 câu (gồm 1 câu không có trong tài liệu), chấm theo từ khóa bỏ dấu, đo thêm "retrieval hit" | `tests/`; `harness/eval.py`: `grade`, `retrieval_hit`, `main` |
| Thêm | Giả lập lỗi để demo | `/fault` làm lần gọi tool kế tiếp ném `RuntimeError` | `harness/tools.py`: `DocTools.fault_next`; `harness/cli.py`: `_handle_command` |
| Thêm | Fallback khi refusal | Dùng `client.beta.messages.create(..., betas=["server-side-fallback-2026-07-01"], fallbacks="default")`; chi phí tính theo `response.model` (model thực sự trả lời). Tắt bằng `--no-fallbacks` | `harness/agent.py`: `Agent._create`, `FALLBACK_BETA`; `harness/cli.py`: `--no-fallbacks` |

## 5. Lệnh trong REPL

| Lệnh | Tác dụng |
|------|----------|
| `/help` | Xem danh sách lệnh |
| `/reset` | Xóa lịch sử hội thoại (chi phí phiên được giữ) |
| `/maxturns N` | Đặt số lượt tối đa mỗi câu hỏi (N ≥ 1) |
| `/fault` | Làm lần gọi tool kế tiếp bị lỗi giả lập |
| `/cost` | Xem token và chi phí cả phiên |
| `/exit`, `/quit` | Thoát, in chi phí phiên |

## 6. Ví dụ log (minh họa)

> Đoạn dưới đây là **minh họa** theo đúng định dạng mà `harness/logger.py` in ra. Số token, thời gian và chi phí là số giả định, chưa phải kết quả của một lần chạy thật.

Console (câu hỏi 2, dùng lịch sử, `cache_read > 0`):

```
──────────────────────── Câu hỏi #2 ────────────────────────
Lượt 1/6 · stop=tool_use · in=412 out=96 cache_read=3180 cache_write=640 · $0.00402
  ↳ tool search_documents {"query":"hoàn học phí đã học 1 tuần"}
    [chinh-sach-hoan-hoc-phi.md#2] chinh-sach-hoan-hoc-phi.md › Chính sách hoàn học phí › Mức hoàn học phí (điểm 12.25)
    … (3 ms)
Lượt 2/6 · stop=end_turn · in=1350 out=210 cache_read=3820 cache_write=0 · $0.00556
Số lượt: 2 · Số tool call: 1 · Tokens: in=1762 out=306 cache_read=7000 cache_write=640
Chi phí câu hỏi: $0.00958 · Cache hit: có
```

Một dòng trong `logs/session-*.jsonl` (mỗi sự kiện một dòng JSON):

```json
{"ts": "2026-11-03T09:15:02+00:00", "event": "turn", "turn": 1, "max_turns": 6, "stop_reason": "tool_use", "model": "claude-sonnet-5-5", "final_turn": false, "input_tokens": 412, "output_tokens": 96, "cache_read": 3180, "cache_write": 640, "cost_usd": 0.00402}
```

Chi phí mỗi lượt theo `harness/pricing.py` (claude-sonnet-5-5: $2 in / $10 out / $0.20 cache_read / $2.50 cache_write mỗi triệu token). Ví dụ lượt 1: (412×2 + 96×10 + 3180×0,2 + 640×2,5) / 1.000.000 = $0,00402.

Các loại sự kiện: `question_start`, `turn`, `tool_call`, `notice`, `question_end`.

## 7. Kịch bản quay video (≤ 5 phút)

1. **Giới thiệu bài toán và cấu trúc repo (30 giây).** Mở README mục 1 và mục 3, lướt qua `harness/` và `docs_noibo/`.
2. **Câu hỏi đầu (60 giây).** Chạy `python -m harness`, gõ:
   `Nếu rút học 3 ngày trước khai giảng thì được hoàn bao nhiêu học phí, cần nộp giấy tờ gì?`
   Chỉ vào log từng lượt, tool call và chi phí câu hỏi.
3. **Câu hỏi nối tiếp (45 giây).** Gõ:
   `Còn nếu đã học được 1 tuần thì sao?`
   Mô hình dùng lịch sử; log cho thấy `cache_read > 0` và "Cache hit: có".
4. **Gây lỗi (60 giây).** Gõ `/fault` rồi hỏi một câu bất kỳ về quy chế: tool lỗi (`LỖI:` màu đỏ), mô hình tự xử lý tiếp. Sau đó gõ `/maxturns 2` và hỏi một câu cần tra cứu: mô hình tìm kiếm một lần, rồi bị buộc trả lời bằng thông tin đã thu thập và hiện cảnh báo "Đã dùng hết 2 lượt…". Nếu ở lượt cuối mô hình vẫn đòi gọi tool thì hiện khung đỏ có ký hiệu ⚠ (hủy câu hỏi, lịch sử được hoàn nguyên). Xong demo, gõ `/reset` rồi `/maxturns 6` trước khi làm tiếp.
5. **Phần nâng cao (60 giây).** Giới thiệu RAG BM25 (`harness/rag.py`); yêu cầu "hãy lưu ghi chú tóm tắt mức hoàn học phí" để thấy bảng duyệt `save_note` y/n; thoát REPL rồi chạy `python -m harness.eval` để in độ chính xác, retrieval hit và tổng chi phí.

## 8. Thay bằng tài liệu thật

1. Xóa hoặc thay các file `.md` trong `docs_noibo/` bằng tài liệu của bạn (chia mục bằng heading `#`, `##`, … để RAG chunk tốt). Không cần sửa code; index BM25 được dựng lại mỗi lần khởi động.
2. Cập nhật `eval/questions.jsonl`, mỗi dòng một câu:
   ```json
   {"id": "q01", "question": "…", "must_include": [["6.5", "6,5"], "70%"], "source": "ten-file.md"}
   ```
   `must_include` là danh sách từ khóa phải xuất hiện trong câu trả lời (phần tử là danh sách con = chấp nhận một trong các cách viết; so khớp không phân biệt hoa thường và dấu). `source` là file nguồn để đo retrieval hit, đặt `null` cho câu hỏi không có đáp án trong tài liệu.
3. Ghi chú do `save_note` tạo nằm trong `notes/`; log nằm trong `logs/` (cả hai đã được `.gitignore`).
