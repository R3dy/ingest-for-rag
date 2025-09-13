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
    if ext in BINARY_EXTS:
        return True
    return False


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

def chunk_text(s: str, max_chars: int = 1000, overlap: int = 100):
    """Split text into overlapping chunks with guaranteed forward progress."""
    s = s.strip()
    if not s:
        return []

    chunks = []
    n = len(s)
    start = 0

    while start < n:
        end = min(start + max_chars, n)
        chunk = s[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end == n:
            break  # reached the end
        # move forward but keep overlap
        start = max(0, end - overlap)

    return chunks


def chunk_docs(s: str):
    # Docs: ~1200 char chunks
    return chunk_text(s, max_chars=1200, overlap=150)


def chunk_code(s: str):
    # Code: ~800 char chunks
    return chunk_text(s, max_chars=800, overlap=100)

