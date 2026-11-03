# Harness "Trợ lý tra cứu quy chế nội bộ" — Thiết kế

Ngày: 2026-11-03 · Bài tập Buổi 2 (Xây dựng harness) · Hạn nộp 07/11/2026

## 1. Bài toán

Học viên và nhân viên giáo vụ của một học viện đào tạo CNTT (dữ liệu mẫu hư cấu: "Học viện HanesVip") hay hỏi đi hỏi lại các câu về quy chế: điều kiện tốt nghiệp, hoàn học phí, điểm danh, bảo lưu, học bổng, nội quy. Câu trả lời nằm rải rác trong nhiều file Markdown. Harness này là một trợ lý dòng lệnh (CLI): nó tìm đoạn liên quan, đọc tài liệu, rồi trả lời kèm trích nguồn, và nhớ được ngữ cảnh của các câu hỏi trước.

Người dùng có thể thay thư mục `docs_noibo/` bằng tài liệu thật của mình mà không phải sửa code.

## 2. Mục tiêu (đối chiếu yêu cầu đề bài)

| # | Yêu cầu | Cách đáp ứng |
|---|---------|--------------|
| 1 | ≥ 2 tool tự viết | `list_documents`, `search_documents` (RAG/BM25), `read_document`, `save_note` (có duyệt) |
| 2 | Agent loop nhiều lượt | Vòng lặp thủ công: gọi API → chạy tool → trả `tool_result` → gọi lại, tới khi `end_turn` |
| 3 | Giới hạn lượt, lượt cuối phải trả lời | `max_turns` (mặc định 6). Ở lượt cuối: gửi `tool_choice: none` + chèn thông báo "[HỆ THỐNG] lượt cuối…" vào tin nhắn tool_result trước đó |
| 4 | Lịch sử | `Agent.messages` giữ suốt phiên, chỉ thêm vào cuối (append-only) |
| 5 | Cache | System prompt + tool cố định, `cache_control` trên system và cache tự động ở cấp request. Log in ra `cache_read` / `cache_write` từng lượt |
| 6 | Observability | Mỗi lượt log: số lượt, stop_reason, token (in/out/cache read/cache write), chi phí lượt; mỗi tool call log: tên, input, kết quả, thời gian, lỗi. Cuối mỗi câu hỏi: tổng chi phí. Tất cả ghi thêm vào `logs/session-*.jsonl` |
| 7 | Xử lý lỗi | Lỗi tool → `tool_result` có `is_error=true`, vòng lặp chạy tiếp. Lỗi API, refusal, max_tokens → thông báo tiếng Việt rõ ràng, phiên không dừng. Chạm giới hạn lượt → cảnh báo kèm câu trả lời từ thông tin đã có |
| Nâng cao | RAG, duyệt trước khi ghi, bộ câu hỏi kiểm thử | BM25 trên các đoạn (chunk) theo heading; `save_note` hỏi y/n trước khi ghi file; `python -m harness.eval` chấm 10 câu, in độ chính xác và chi phí |

Ngoài phạm vi: giao diện web, embedding hoặc vector DB, đọc PDF, nhiều người dùng.

## 3. Lựa chọn kỹ thuật

- **Python 3.12 + Anthropic SDK `anthropic` 2.4.0**, tự viết vòng lặp thủ công thay vì dùng Tool Runner, vì đề bài yêu cầu tự xây harness (vòng lặp, giới hạn lượt, log). Không có repo demo buổi 2, nên dựng từ đầu.
- **Model mặc định `claude-sonnet-5-5`** (đổi qua env `HARNESS_MODEL` hoặc `--model`). Đặt cố định `output_config.effort = "medium"` để không làm mất cache. Thinking để mặc định (adaptive). Mọi block (kể cả thinking) được gửi lại nguyên vẹn.
- **Fallback khi bị từ chối**: dùng `client.beta.messages.create(..., betas=["server-side-fallback-2026-07-01"], fallbacks="default")`, tắt được bằng `--no-fallbacks`. Chi phí tính theo `response.model` (model thực sự trả lời).
- **Không dùng forced `tool_choice` (`any` / `tool`)**, vì Sonnet 5.5 trả về lỗi 400. Chỉ dùng `auto` (mặc định) và `none` (ở lượt cuối).
- **RAG thuần Python**: chunk theo heading Markdown, token hóa không dấu + bigram, chấm điểm BM25. Không cần thư viện ngoài.
- **Thư viện**: `rich` (log màu, dễ quay video), `python-dotenv` (đọc `.env`), `pytest`.

## 4. Kiến trúc

```
harness/
  config.py     cấu hình: model, max_turns, đường dẫn
  pricing.py    bảng giá $/MTok + Usage + cost_usd()
  rag.py        chunk Markdown + BM25Index
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

Luồng dữ liệu cho một câu hỏi: CLI → `Agent.ask(q)` → (API → log lượt → `DocTools.execute` → log tool)×N → `AnswerResult` → CLI in câu trả lời và chi phí.

## 5. Hành vi chi tiết

**Lịch sử và lỗi.** Khi một câu hỏi kết thúc bất thường (lỗi API, refusal, `max_tokens` giữa chừng một tool_use), harness cắt lịch sử về vị trí trước câu hỏi, rồi thêm cặp `user: <câu hỏi>` / `assistant: "[Không trả lời được: <lý do>]"`. Cách này giữ lịch sử hợp lệ cho API, giữ nguyên phần prefix đã cache, và câu sau vẫn tham chiếu được câu trước.

**Lỗi tool** có bốn loại: tên tool không tồn tại, input sai, `ToolError` (ví dụ không tìm thấy file), và exception bất kỳ. Cả bốn đều trả về `is_error=true` kèm thông điệp tiếng Việt, rồi mô hình tự xử lý tiếp. Lệnh `/fault` làm lần gọi tool kế tiếp ném `RuntimeError`, dùng để demo trong video.

**Giới hạn lượt.** Lượt `max_turns` luôn gửi kèm `tool_choice: none`. Nếu tới được lượt đó vì mô hình vẫn muốn gọi tool, `hit_turn_limit=True` và CLI in cảnh báo vàng: "Đã dùng hết N lượt…".

**Duyệt ghi.** `save_note` gọi `approver(tool_name, input)` trước khi ghi. Nếu người dùng từ chối, tool trả về "Người dùng từ chối…" và không ghi file. Khi chạy eval, approver luôn từ chối.

**Chi phí.** Công thức: `input×giá_in + output×giá_out + cache_read×giá_read + cache_write×giá_write5m`, tính trên mỗi triệu token. Với Sonnet 5.5 là $2 / $10 / $0.20 / $2.50.

## 6. Kiểm thử

- Unit test cho pricing, rag, tools, agent (dùng client giả), và hàm chấm điểm của eval. Không gọi API thật.
- Bộ eval 10 câu (gồm 1 câu không có trong tài liệu). Chấm theo từ khóa: bỏ dấu, chữ thường, chấp nhận nhiều cách viết. Đồng thời đo "retrieval hit" (tool có chạm tới đúng file nguồn không).
- Thử thủ công bằng API key thật theo kịch bản video trong README.

## 7. Kịch bản video (≤ 5 phút)

1. Giới thiệu bài toán và cấu trúc repo (30 giây).
2. Hỏi: "Nếu rút học 3 ngày trước khai giảng thì được hoàn bao nhiêu học phí, cần nộp giấy tờ gì?" → xem log từng lượt, tool, chi phí (60 giây).
3. Hỏi tiếp: "Còn nếu đã học được 1 tuần thì sao?" → dùng lịch sử, log cho thấy `cache_read > 0` (45 giây).
4. Gây lỗi: `/fault` rồi hỏi một câu → tool lỗi, mô hình tự xử lý tiếp. Sau đó `/maxturns 2` và hỏi một câu cần tra cứu → tìm kiếm một lần rồi bị buộc trả lời từ thông tin đã có, hiện cảnh báo hết lượt (nếu lượt cuối vẫn đòi gọi tool thì hiện khung đỏ ⚠); sau demo chạy `/reset` và `/maxturns 6` (60 giây).
5. Phần nâng cao: RAG (BM25), `save_note` có duyệt y/n, `python -m harness.eval` in độ chính xác và chi phí (60 giây).
