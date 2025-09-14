import re
import chardet

def debug_print(debug, msg):
    if debug:
        print(msg)

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
    return Path(path.lower()).suffix in BINARY_EXTS


def detect_encoding(data: bytes) -> str:
    try:
        guess = chardet.detect(data)
        return guess.get("encoding") or "utf-8"
    except Exception:
        return "utf-8"


def safe_decode(data: bytes, debug=False) -> str:
    debug_print(debug, f"[safe_decode] Decoding {len(data)} bytes")
    enc = detect_encoding(data)
    try:
        return data.decode(enc, errors="replace")
    except Exception:
        return data.decode("utf-8", errors="replace")


def normalize_ws(s: str, debug=False) -> str:
    debug_print(debug, f"[normalize_ws] Normalizing string of length {len(s)}")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def clean_nav_footer_noise(text: str, debug=False) -> str:
    """
    Strip nav/footer/sidebar/UI noise and collapse duplicates before chunking.
    """
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        low = line.lower().strip()
        if not line.strip():
            continue
        if any(x in low for x in [
            "home page", "search", "navigation", "issues", "github", "slack",
            "was this page helpful", "assistant", "responses are generated",
            "copy", "ask ai", "⌘", "version "
        ]):
            continue
        cleaned.append(line)
    # drop consecutive duplicate lines
    out = []
    for l in cleaned:
        if not out or out[-1] != l:
            out.append(l)
    debug_print(debug, f"[clean_nav_footer_noise] Reduced {len(lines)} lines → {len(out)} lines")
    return "\n".join(out)


def chunk_text(s: str, max_chars: int = 1200, overlap: int = 150, debug=False):
    debug_print(debug, f"[chunk_text] Input length {len(s)}")
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

        chunk = s[start:cut].strip()
        if chunk:
            chunks.append(chunk)

        # ✅ guarantee forward progress
        new_start = cut - overlap
        if new_start <= start:
            new_start = start + max_chars
        start = max(0, new_start)

    debug_print(debug, f"[chunk_text] Produced {len(chunks)} chunks")
    return chunks


def chunk_with_code_blocks(s: str, max_chars: int = 1200, overlap: int = 150, debug=False):
    debug_print(debug, f"[chunk_with_code_blocks] Input length {len(s)}")
    # Clean first
    s = clean_nav_footer_noise(s, debug=debug)

    lines = s.splitlines()
    chunks, buffer, in_code = [], [], False

    for line in lines:
        if line.strip().startswith("```"):
            if in_code:
                buffer.append(line)
                block = "\n".join(buffer).strip()
                if block:
                    chunks.append(block)
                buffer, in_code = [], False
            else:
                if buffer:
                    prose = "\n".join(buffer).strip()
                    if prose:
                        chunks.extend(chunk_text(prose, max_chars, overlap, debug))
                    buffer = []
                buffer.append(line)
                in_code = True
        else:
            buffer.append(line)

    if buffer:
        text = "\n".join(buffer).strip()
        if text:
            if in_code:
                chunks.append(text)
            else:
                chunks.extend(chunk_text(text, max_chars, overlap, debug))

    debug_print(debug, f"[chunk_with_code_blocks] Produced {len(chunks)} chunks")
    return chunks


def chunk_docs(s: str, debug=False):
    return chunk_with_code_blocks(s, max_chars=1200, overlap=150, debug=debug)


def chunk_code(s: str, debug=False):
    return chunk_with_code_blocks(s, max_chars=800, overlap=100, debug=debug)

