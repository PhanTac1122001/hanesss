"""Manual agent loop over the Anthropic Messages API."""
from __future__ import annotations

from dataclasses import dataclass, field

import anthropic

from harness import config
from harness.logger import RunLogger
from harness.pricing import Usage, cost_usd
from harness.tools import TOOL_SCHEMAS, DocTools

SYSTEM_PROMPT = """\
Bạn là trợ lý tra cứu quy chế nội bộ của Học viện HanesVip. Nhiệm vụ của bạn là giúp học viên, giảng viên và nhân viên của Học viện tìm đúng thông tin trong các tài liệu quy chế nội bộ (quy chế học vụ, chính sách học bổng, chính sách hoàn học phí, quy định điểm danh, quy trình bảo lưu, nội quy lớp học, ...) và trả lời chính xác, ngắn gọn, dễ hiểu bằng tiếng Việt.

## Cách làm việc
- Với mọi câu hỏi về quy chế, hãy gọi tool search_documents TRƯỚC TIÊN để tìm các đoạn liên quan nhất. Chọn từ khóa tiếng Việt cụ thể, bám sát nội dung câu hỏi (ví dụ: "hoàn học phí", "điều kiện bảo lưu", "số buổi vắng tối đa").
- Khi các đoạn tìm được chưa đủ chi tiết (thiếu điều kiện, số liệu, ngoại lệ, quy trình từng bước), dùng read_document để đọc đầy đủ tài liệu hoặc chỉ mục có tiêu đề khớp (tham số section).
- Dùng list_documents khi cần biết hiện có những tài liệu nào, hoặc khi tìm kiếm không cho kết quả phù hợp.
- Bạn được phép gọi nhiều tool liên tiếp để thu thập đủ thông tin, nhưng hãy gọn gàng: chỉ tìm kiếm thêm tối đa vài lần với các từ khóa khác nhau, không lặp lại cùng một truy vấn, và dừng lại ngay khi đã đủ thông tin để trả lời.
- Nếu câu hỏi gồm nhiều ý, hãy tìm thông tin cho từng ý rồi tổng hợp thành một câu trả lời thống nhất.

## Quy tắc trả lời
- Chỉ trả lời dựa trên nội dung các tài liệu mà tool trả về. Không dùng kiến thức bên ngoài, không suy đoán, không tự bổ sung quy định không có trong tài liệu.
- Luôn trích dẫn nguồn cho từng thông tin quan trọng theo định dạng [tên-file › mục], ví dụ [quy-che-hoc-vu.md › Điều kiện dự thi]. Nếu thông tin nằm ở nhiều nguồn, ghi đủ các nguồn.
- Tuyệt đối không bịa số liệu: số buổi, tỷ lệ phần trăm, số tiền, thời hạn, ngày tháng, điểm số phải khớp chính xác với tài liệu. Nếu tài liệu nói khác nhau ở các nơi, hãy nêu rõ sự khác biệt và nguồn của từng nơi.
- Nếu các tài liệu không chứa câu trả lời, hãy nói rõ: "không tìm thấy thông tin" về nội dung được hỏi trong các tài liệu hiện có, nêu ngắn gọn bạn đã tra cứu những gì, và gợi ý người dùng liên hệ bộ phận phụ trách phù hợp. Không được trả lời cho có.
- Nếu tài liệu chỉ trả lời được một phần câu hỏi, hãy trả lời phần có thông tin và nói rõ phần nào còn thiếu.
- Trả lời bằng tiếng Việt, súc tích, đi thẳng vào vấn đề. Dùng gạch đầu dòng khi liệt kê điều kiện, bước thực hiện hoặc nhiều mục; câu hỏi đơn giản thì trả lời bằng một hai câu.
- Giữ giọng điệu lịch sự, trung lập, chuyên nghiệp.

## Hội thoại nhiều lượt
- Người dùng có thể đặt câu hỏi nối tiếp (ví dụ "còn trường hợp ốm thì sao?"). Hãy dùng nội dung các câu hỏi và câu trả lời trước đó trong cuộc trò chuyện để hiểu đúng ngữ cảnh, nhưng vẫn tra cứu lại tài liệu khi câu hỏi mới cần thông tin chưa có.

## Ghi chú (save_note)
- Chỉ dùng tool save_note khi người dùng yêu cầu rõ ràng việc lưu lại ghi chú. Không tự ý lưu.
- Người dùng có thể từ chối việc lưu. Khi đó hãy thông báo ngắn gọn rằng ghi chú chưa được lưu và tiếp tục hỗ trợ bình thường, không nài nỉ.

## Xử lý lỗi
- Khi một tool trả về lỗi, đừng bỏ cuộc ngay: hãy thử cách khác (đổi từ khóa tìm kiếm, dùng list_documents để xem tên file chính xác, đọc theo mục khác). Nếu vẫn không được, giải thích ngắn gọn cho người dùng vấn đề gặp phải và những gì bạn đã có được.

## Lượt cuối
- Khi hệ thống thông báo đây là lượt cuối cùng, không gọi thêm tool. Hãy trả lời ngay bằng thông tin đã thu thập được và nói rõ phần nào còn thiếu hoặc chưa kiểm chứng được.
"""

FINAL_TURN_NOTICE = (
    "[HỆ THỐNG] Đây là lượt cuối cùng (giới hạn {max_turns} lượt). Không gọi thêm tool. "
    "Hãy trả lời ngay bằng thông tin đã thu thập; nếu chưa đủ, nói rõ phần nào còn thiếu."
)
EMPTY_ANSWER_TEXT = "(Mô hình không trả về nội dung văn bản.)"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_RESULT_LOG_CHARS = 2000


@dataclass
class ToolCallRecord:
    name: str
    input: dict
    result: str
    is_error: bool


@dataclass
class AnswerResult:
    text: str
    turns: int
    usage: Usage
    cost_usd: float
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    hit_turn_limit: bool = False
    error: str | None = None

    @property
    def cache_hit(self) -> bool:
        return self.usage.cache_read > 0


class Agent:
    def __init__(
        self,
        client,
        tools: DocTools,
        logger: RunLogger,
        model: str = config.DEFAULT_MODEL,
        max_turns: int = config.DEFAULT_MAX_TURNS,
        use_fallbacks: bool = True,
    ):
        self.client = client
        self.tools = tools
        self.logger = logger
        self.model = model
        self.max_turns = max_turns
        self.use_fallbacks = use_fallbacks
        self.messages: list = []
        self.question_count = 0
        self.session_usage = Usage()
        self.session_cost = 0.0

    def reset(self) -> None:
        """Start a new conversation; session cost is kept."""
        self.messages = []

    def _create(self, final_turn: bool):
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
            return self.client.beta.messages.create(
                **kwargs, betas=[FALLBACK_BETA], fallbacks="default"
            )
        return self.client.messages.create(**kwargs)

    def _api_error_message(self, e: anthropic.APIError) -> str:
        """Map an SDK exception to a Vietnamese message (most specific first)."""
        if isinstance(e, anthropic.AuthenticationError):
            return "API key không hợp lệ hoặc chưa được cấu hình (ANTHROPIC_API_KEY)."
        if isinstance(e, anthropic.PermissionDeniedError):
            return "API key không có quyền dùng model này."
        if isinstance(e, anthropic.NotFoundError):
            return f"Model '{self.model}' không tồn tại hoặc không khả dụng."
        if isinstance(e, anthropic.RateLimitError):
            return "Bị giới hạn tốc độ (rate limit). Vui lòng thử lại sau ít phút."
        if isinstance(e, anthropic.BadRequestError):
            return f"Yêu cầu không hợp lệ: {e.message}"
        if isinstance(e, anthropic.APIStatusError):
            return f"Lỗi máy chủ API ({e.status_code}). Vui lòng thử lại."
        if isinstance(e, anthropic.APIConnectionError):
            return "Không kết nối được tới API. Kiểm tra mạng rồi thử lại."
        return f"Lỗi API không xác định ({type(e).__name__}): {e}. Vui lòng thử lại."

    def ask(self, question: str) -> AnswerResult:
        start_len = len(self.messages)
        try:
            return self._ask(question)
        except BaseException:
            # Unhandled error / Ctrl-C: never leave a dangling user message or tool_use.
            del self.messages[start_len:]
            raise

    def _ask(self, question: str) -> AnswerResult:
        max_turns = max(1, self.max_turns)
        self.question_count += 1
        self.logger.question_start(self.question_count, question)
        start_len = len(self.messages)

        content = [{"type": "text", "text": question}]
        if max_turns == 1:
            content.append({"type": "text", "text": FINAL_TURN_NOTICE.format(max_turns=1)})
        self.messages.append({"role": "user", "content": content})

        usage = Usage()
        cost = 0.0
        turns = 0
        tool_calls: list[ToolCallRecord] = []

        def abort(message: str, hit_limit: bool = False) -> AnswerResult:
            return self._abort(
                start_len, question, message, turns, usage, cost, tool_calls, hit_limit
            )

        for turn in range(1, max_turns + 1):
            final = turn == max_turns
            try:
                resp = self._create(final)
            except anthropic.APIError as e:
                msg = self._api_error_message(e)
                self.logger.notice(msg, "error")
                return abort(msg)

            turns += 1
            model_name = getattr(resp, "model", None) or self.model
            turn_usage = Usage.from_api(resp.usage)
            turn_cost = cost_usd(model_name, turn_usage)
            usage = usage + turn_usage
            cost += turn_cost
            self.session_usage = self.session_usage + turn_usage
            self.session_cost += turn_cost
            self.logger.turn(
                turn, max_turns, resp.stop_reason, turn_usage, turn_cost, model_name, final
            )

            if resp.stop_reason == "refusal":
                msg = "Mô hình từ chối trả lời yêu cầu này"
                category = getattr(getattr(resp, "stop_details", None), "category", None)
                if category:
                    msg += f" (loại: {category})"
                return abort(msg)

            # Content is passed back unchanged (thinking / fallback blocks included).
            self.messages.append({"role": "assistant", "content": resp.content})
            tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]

            if resp.stop_reason == "max_tokens" and tool_uses:
                return abort("Câu trả lời bị cắt do vượt giới hạn max_tokens.")

            if not tool_uses:
                text = "\n".join(
                    b.text for b in resp.content if getattr(b, "type", None) == "text"
                ).strip()
                if not text:
                    text = EMPTY_ANSWER_TEXT
                if resp.stop_reason == "max_tokens":
                    text += "\n\n(…câu trả lời bị cắt do giới hạn độ dài)"
                if final:
                    self.logger.notice(
                        f"Đã dùng hết {max_turns} lượt — câu trả lời dựa trên thông tin đã thu thập, "
                        "có thể chưa đầy đủ.",
                        "warn",
                    )
                result = AnswerResult(text, turns, usage, cost, tool_calls, final)
                self.logger.question_end(result)
                return result

            if final:
                return abort(
                    "Mô hình vẫn muốn gọi tool ở lượt cuối; dừng lại theo giới hạn.", True
                )

            blocks: list[dict] = []
            for b in tool_uses:
                tool_input = dict(b.input or {})
                res = self.tools.execute(b.name, tool_input)
                self.logger.tool_call(b.name, tool_input, res)
                tool_calls.append(
                    ToolCallRecord(b.name, tool_input, res.content[:_RESULT_LOG_CHARS], res.is_error)
                )
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": b.id,
                        "content": res.content,
                        "is_error": res.is_error,
                    }
                )
            if turn + 1 == max_turns:
                blocks.append(
                    {"type": "text", "text": FINAL_TURN_NOTICE.format(max_turns=max_turns)}
                )
            self.messages.append({"role": "user", "content": blocks})

        raise AssertionError("unreachable: the final turn always returns")  # pragma: no cover

    def _abort(
        self,
        start_len: int,
        question: str,
        message: str,
        turns: int,
        usage: Usage,
        cost: float,
        tool_calls: list[ToolCallRecord],
        hit_turn_limit: bool = False,
    ) -> AnswerResult:
        """Roll history back to the pre-question state plus a synthetic pair."""
        del self.messages[start_len:]
        self.messages.append({"role": "user", "content": [{"type": "text", "text": question}]})
        self.messages.append(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": f"[Không trả lời được: {message}]"}],
            }
        )
        result = AnswerResult(
            f"⚠ {message}", turns, usage, cost, tool_calls, hit_turn_limit, error=message
        )
        self.logger.question_end(result)
        return result
