import re

def clean_lines(lines):
    """Remove nav/footer junk and duplicates."""
    junk_patterns = [
        r"home page", r"search", r"navigation", r"issues", r"github", r"slack",
        r"was this page helpful", r"copy", r"ask ai", r"⌘", r"assistant",
        r"responses are generated"
    ]
    cleaned, seen = [], set()
    for line in lines:
        low = line.lower().strip()
        if not line.strip():
            continue
        if any(re.search(p, low) for p in junk_patterns):
            continue
        if line in seen:
            continue
        cleaned.append(line)
        seen.add(line)
    return cleaned


def remove_toc_blocks(lines, min_run=5, max_words=4):
    """
    Remove TOC-like blocks: runs of many short lines (outside code).
    """
    cleaned, buffer = [], []
    for line in lines:
        if len(line.split()) <= max_words and not line.strip().startswith("```"):
            buffer.append(line)
            if len(buffer) >= min_run:
                buffer = []  # drop TOC block
        else:
            if buffer:
                cleaned.extend(buffer)
                buffer = []
            cleaned.append(line)
    return cleaned


def promote_headings(lines):
    """Turn common section labels into Markdown headings."""
    fixed = []
    for line in lines:
        if re.match(r"^(overview|reserved keywords|payloadtype|message keywords)", line.strip(), re.I):
            fixed.append("## " + line.strip())
        else:
            fixed.append(line)
    return fixed


def detect_code_lang(block: str) -> str:
    """Guess language for a code block."""
    snippet = block.strip().splitlines()
    if not snippet:
        return "text"
    first = snippet[0].strip()
    block_text = "\n".join(snippet).lower()

    if first.startswith("{") or block_text.startswith("{"):
        return "json"
    if first.startswith("$") or first.startswith("sudo "):
        return "bash"
    if "func " in block_text or "package main" in block_text:
        return "go"
    if "def " in block_text or "import " in block_text:
        return "python"
    return "text"


def wrap_code_blocks(text):
    """Ensure fences are balanced and labeled with language."""
    rebuilt = []
    parts = text.split("```")
    in_code = False
    for i, part in enumerate(parts):
        if in_code:
            lang = detect_code_lang(part)
            rebuilt[-1] = f"```{lang}"  # replace the opening
            rebuilt.append(part)
            rebuilt.append("```")
            in_code = False
        else:
            if i < len(parts) - 1:  # opening fence
                rebuilt.append("```")
                rebuilt.append(part)
                in_code = True
            else:
                rebuilt.append(part)
    return "\n".join(rebuilt)


def format_markdown(raw_text, source, title, category, keywords):
    """Produce clean Markdown with metadata and body text."""
    lines = raw_text.splitlines()
    lines = clean_lines(lines)
    lines = remove_toc_blocks(lines)  # 🔥 remove nav/TOC
    lines = promote_headings(lines)

    body = "\n".join(lines)
    body = wrap_code_blocks(body)

    front_matter = f"""---
source: {source}
title: {title}
category: {category}
keywords: {', '.join(keywords)}
---

# {title}

"""
    return front_matter + body.strip() + "\n"

