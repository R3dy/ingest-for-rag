import re
import chardet

BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg",
    ".ico", ".webp", ".pdf", ".zip", ".tar", ".gz", ".7z",
    ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".exe", ".dll", ".so",
}

DOC_EXTS = {".md", ".markdown", ".html", ".htm", ".txt"}
CODE_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".c", ".h",
    ".cpp", ".hpp", ".java", ".kt", ".rb", ".php", ".sh", ".ps1",
    ".cs", ".scala", ".swift", ".lua", ".pl", ".sql", ".yaml", ".yml",
    ".toml", ".ini", ".json", ".gradle", ".make", ".mk", ".dockerfile",
}


def is_probably_binary(path: str) -> bool:
    from pathlib import Path
    ext = Path(path.lower()).suffix
    return ext in BINARY_EXTS


def detect_encoding(data: bytes) -> str:
    try:
        guess = chardet.detect(data)
        enc = guess.get("encoding") or "utf-8"
        return enc
    except Exception:
        return "utf-8"


def safe_decode(data: bytes) -> str:
    enc = detect_encoding(data)
    try:
        return data.decode(enc, errors="replace")
    except Exception:
        return data.decode("utf-8", errors="replace")


def normalize_ws(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def chunk_text(s: str, max_chars: int = 1200, overlap: int = 150):
    """Generic sliding-window chunking for plain text."""
    s = s.strip()
    if not s:
        return []
    chunks = []
    start = 0
    n = len(s)
    while start < n:
        end = min(start + max_chars, n)
        cut = s.rfind("\n\n", start, end)
        if cut == -1 or cut <= start + 200:
            cut = end
        chunks.append(s[start:cut].strip())
        if cut <= start:
            start = end
        else:
            start = max(0, cut - overlap)
    out = []
    for c in chunks:
        if c and (not out or c != out[-1]):
            out.append(c)
    return out


def chunk_with_code_blocks(s: str, max_chars: int = 1200, overlap: int = 150):
    """
    Split text into chunks, but keep fenced code blocks (```...```) intact.
    Prose outside code blocks is split with chunk_text.
    """
    lines = s.splitlines()
    chunks, buffer, in_code = [], [], False

    for line in lines:
        if line.strip().startswith("```"):  # toggle code block
            if in_code:
                buffer.append(line)
                # flush full code block as one chunk
                block = "\n".join(buffer).strip()
                if block:
                    chunks.append(block)
                buffer, in_code = [], False
            else:
                # flush prose before starting code block
                if buffer:
                    prose = "\n".join(buffer).strip()
                    if prose:
                        chunks.extend(chunk_text(prose, max_chars, overlap))
                    buffer = []
                buffer.append(line)
                in_code = True
        else:
            buffer.append(line)

    # leftover
    if buffer:
        text = "\n".join(buffer).strip()
        if text:
            if in_code:
                chunks.append(text)  # unterminated code block
            else:
                chunks.extend(chunk_text(text, max_chars, overlap))

    return chunks


def chunk_docs(s: str):
    return chunk_with_code_blocks(s, max_chars=1200, overlap=150)


def chunk_code(s: str):
    return chunk_with_code_blocks(s, max_chars=800, overlap=100)

