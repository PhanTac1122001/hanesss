"""Pure-Python BM25 index over Markdown policy documents."""
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*?)\s*$")
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)?")


def normalize(text: str) -> str:
    """Lowercase, map đ to d and strip Vietnamese diacritics."""
    text = text.lower().replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def tokenize(text: str) -> list[str]:
    """Unigrams plus bigrams (joined by '_') of the normalized text."""
    unigrams = _TOKEN_RE.findall(normalize(text))
    bigrams = [f"{a}_{b}" for a, b in zip(unigrams, unigrams[1:])]
    return unigrams + bigrams


@dataclass(frozen=True)
class Chunk:
    id: str
    doc: str
    heading: str
    text: str


def _split_body(body: str, max_chars: int) -> list[str]:
    if len(body) <= max_chars:
        return [body]
    pieces: list[str] = []
    current = ""
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para:
            continue
        if not current:
            current = para
        elif len(current) + 2 + len(para) <= max_chars:
            current += "\n\n" + para
        else:
            pieces.append(current)
            current = para
    if current:
        pieces.append(current)
    return pieces


def chunk_markdown(doc: str, text: str, max_chars: int = 1200) -> list[Chunk]:
    """Split Markdown into per-section chunks carrying the heading path."""
    sections: list[tuple[str, str]] = []
    path: list[tuple[int, str]] = []
    heading = ""
    body_lines: list[str] = []

    def flush() -> None:
        sections.append((heading, "\n".join(body_lines).strip()))

    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            flush()
            body_lines = []
            level = len(m.group(1))
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, m.group(2)))
            heading = " › ".join(t for _, t in path)
        else:
            body_lines.append(line)
    flush()

    chunks: list[Chunk] = []
    for head, body in sections:
        if not body:
            continue
        for piece in _split_body(body, max_chars):
            chunks.append(Chunk(f"{doc}#{len(chunks) + 1}", doc, head, piece))
    return chunks


class BM25Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self._tfs = [Counter(tokenize(c.heading + "\n" + c.text)) for c in chunks]
        self._lens = [sum(tf.values()) for tf in self._tfs]
        self._n = len(chunks)
        self._avgdl = sum(self._lens) / self._n if self._n else 0.0
        df: Counter = Counter()
        for tf in self._tfs:
            df.update(tf.keys())
        self._idf = {
            t: math.log(1 + (self._n - d + 0.5) / (d + 0.5)) for t, d in df.items()
        }

    def search(self, query: str, top_k: int = 4) -> list[tuple[Chunk, float]]:
        terms = [t for t in dict.fromkeys(tokenize(query)) if t in self._idf]
        scored: list[tuple[Chunk, float]] = []
        for chunk, tf, dl in zip(self.chunks, self._tfs, self._lens):
            norm = 1 - self.b + self.b * dl / self._avgdl if self._avgdl else 1.0
            score = 0.0
            for t in terms:
                f = tf.get(t, 0)
                if f:
                    score += self._idf[t] * f * (self.k1 + 1) / (f + self.k1 * norm)
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


def build_index(docs_dir: Path) -> tuple[BM25Index, dict[str, str]]:
    """Index every *.md file; return the index and {filename: full_text}."""
    chunks: list[Chunk] = []
    full: dict[str, str] = {}
    for path in sorted(Path(docs_dir).glob("*.md"), key=lambda p: p.name):
        content = path.read_text(encoding="utf-8")
        full[path.name] = content
        chunks.extend(chunk_markdown(path.name, content))
    return BM25Index(chunks), full
