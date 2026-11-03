"""Document tools exposed to the model: schemas and the executor."""
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from harness import rag

Approver = Callable[[str, dict], bool]

MAX_FULL_CHARS = 8000
SNIPPET_CHARS = 500


class ToolError(Exception):
    """Expected, user-explainable tool failure."""


@dataclass
class ToolResult:
    content: str
    is_error: bool
    duration_ms: float


TOOL_SCHEMAS: list[dict] = [
    {
        "name": "list_documents",
        "description": (
            "Liệt kê tất cả tài liệu quy chế nội bộ hiện có (tên file, tiêu đề, độ dài). "
            "Dùng khi cần biết có những tài liệu nào."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_documents",
        "description": (
            "Tìm kiếm bằng BM25 trên các mục của tài liệu và trả về các đoạn liên quan nhất "
            "kèm điểm số. Nên dùng tool này ĐẦU TIÊN cho mọi câu hỏi về quy chế."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Từ khóa hoặc câu truy vấn tiếng Việt."},
                "top_k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 8,
                    "default": 4,
                    "description": "Số đoạn tối đa trả về (1-8, mặc định 4).",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_document",
        "description": (
            "Đọc nội dung một tài liệu theo tên file. Dùng sau khi tìm kiếm khi cần xem đầy đủ "
            "ngữ cảnh; truyền section để chỉ đọc các mục có tiêu đề khớp."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Tên file tài liệu, ví dụ quy-che-hoc-vu.md.",
                },
                "section": {
                    "type": "string",
                    "description": "Từ khóa tiêu đề mục (tùy chọn) để chỉ đọc các mục khớp.",
                },
            },
            "required": ["filename"],
            "additionalProperties": False,
        },
    },
    {
        "name": "save_note",
        "description": (
            "GHI một file ghi chú vào thư mục notes/. Chỉ dùng khi người dùng yêu cầu rõ ràng "
            "việc lưu ghi chú; tool này cần người dùng phê duyệt trước khi ghi."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Tiêu đề ghi chú."},
                "content": {"type": "string", "description": "Nội dung ghi chú."},
            },
            "required": ["title", "content"],
            "additionalProperties": False,
        },
    },
]

_TOOL_NAMES = [s["name"] for s in TOOL_SCHEMAS]
_TYPE_LABELS = {str: "string", int: "integer"}


def _validate(name: str, tool_input: object) -> None:
    """Check required/optional params against the schema; raise ToolError."""
    if not isinstance(tool_input, dict):
        raise ToolError("Tham số của tool phải là một đối tượng JSON.")
    props = next(s for s in TOOL_SCHEMAS if s["name"] == name)["input_schema"]
    required = props["required"]
    for field, spec in props["properties"].items():
        py_type = int if spec["type"] == "integer" else str
        label = _TYPE_LABELS[py_type]
        if field not in tool_input or tool_input[field] is None:
            if field in required:
                raise ToolError(f"Thiếu tham số bắt buộc '{field}' (kiểu {label}).")
            continue
        value = tool_input[field]
        if not isinstance(value, py_type) or isinstance(value, bool):
            raise ToolError(f"Tham số '{field}' phải có kiểu {label}.")


class DocTools:
    def __init__(self, docs_dir: Path, notes_dir: Path, approver: Approver):
        self.docs_dir = Path(docs_dir)
        self.notes_dir = Path(notes_dir)
        self.approver = approver
        self.index, self.docs = rag.build_index(self.docs_dir)
        self.fault_next = False

    def execute(self, name: str, tool_input: dict) -> ToolResult:
        start = time.perf_counter()

        def done(content: str, is_error: bool) -> ToolResult:
            return ToolResult(content, is_error, (time.perf_counter() - start) * 1000)

        try:
            if self.fault_next:
                self.fault_next = False
                raise RuntimeError(
                    "Lỗi giả lập (fault injection) — dùng để kiểm thử xử lý lỗi"
                )
            if name not in _TOOL_NAMES:
                return done(
                    f"Tool '{name}' không tồn tại. Các tool hợp lệ: "
                    + ", ".join(_TOOL_NAMES) + ".",
                    True,
                )
            _validate(name, tool_input)
            handler = getattr(self, f"_{name}")
            return done(handler(**tool_input), False)
        except ToolError as e:
            return done(str(e), True)
        except Exception as e:  # never let a tool crash the loop
            return done(f"Lỗi nội bộ khi chạy tool {name}: {type(e).__name__}: {e}", True)

    # --- handlers -------------------------------------------------------

    def _list_documents(self) -> str:
        lines = [f"Có {len(self.docs)} tài liệu:"]
        for filename, text in self.docs.items():
            title = filename
            for line in text.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            lines.append(f"- {filename}: {title} ({len(text)} ký tự)")
        return "\n".join(lines)

    def _search_documents(self, query: str, top_k: int = 4) -> str:
        if not query.strip():
            raise ToolError("Câu truy vấn rỗng.")
        top_k = max(1, min(8, top_k))
        hits = self.index.search(query, top_k=top_k)
        if not hits:
            return (
                f"Không tìm thấy đoạn nào khớp với '{query}'. "
                "Thử từ khóa khác hoặc dùng list_documents."
            )
        blocks = [
            f"[{c.id}] {c.doc} › {c.heading} (điểm {score:.2f})\n{c.text[:SNIPPET_CHARS]}"
            for c, score in hits
        ]
        return "\n\n".join(blocks)

    def _read_document(self, filename: str, section: str | None = None) -> str:
        if "/" in filename or "\\" in filename or ".." in filename:
            raise ToolError(f"Tên file không hợp lệ: '{filename}'.")
        if filename not in self.docs:
            raise ToolError(
                f"Không tìm thấy tài liệu '{filename}'. Dùng list_documents để xem danh sách."
            )
        if section:
            chunks = [c for c in self.index.chunks if c.doc == filename]
            wanted = rag.normalize(section)
            matched = [c for c in chunks if wanted in rag.normalize(c.heading)]
            if not matched:
                headings = list(dict.fromkeys(c.heading for c in chunks if c.heading))
                raise ToolError(
                    f"Không có mục nào khớp '{section}' trong {filename}. "
                    "Các mục hiện có: " + "; ".join(headings) + "."
                )
            return "\n\n".join(f"## {c.heading}\n{c.text}" for c in matched)
        text = self.docs[filename]
        if len(text) > MAX_FULL_CHARS:
            text = (
                text[:MAX_FULL_CHARS]
                + "\n…(đã cắt bớt, dùng tham số section để đọc từng mục)"
            )
        return text

    def _save_note(self, title: str, content: str) -> str:
        if not self.approver("save_note", {"title": title, "content": content}):
            return "Người dùng đã TỪ CHỐI lưu ghi chú. Không có file nào được ghi."
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", rag.normalize(title)).strip("-")[:60].strip("-")
        slug = slug or "ghi-chu"
        fname = f"{slug}.md"
        n = 2
        while (self.notes_dir / fname).exists():
            fname = f"{slug}-{n}.md"
            n += 1
        (self.notes_dir / fname).write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
        return f"Đã lưu ghi chú vào notes/{fname}"
