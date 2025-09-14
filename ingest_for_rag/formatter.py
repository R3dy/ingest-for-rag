import re

JUNK_PATTERNS = [
    r"home page", r"search", r"navigation", r"issues", r"github", r"slack",
    r"was this page helpful", r"copy", r"ask ai", r"⌘", r"assistant",
    r"responses are generated", r"#mythic community"
]

def clean_lines(lines):
    """Remove obvious UI junk and collapse duplicates."""
    cleaned, prev = [], None
    for line in lines:
        low = line.lower().strip()
        if not line.strip():
            continue
        if any(re.search(p, low) for p in JUNK_PATTERNS):
            continue
        if prev and prev.strip() == line.strip():
            continue
        cleaned.append(line)
        prev = line
    return cleaned

def promote_headings(lines):
    """Promote standalone section labels into Markdown headings."""
    fixed = []
    for line in lines:
        if re.match(r"^(overview|reserved keywords|payloadtype|message keywords|walkthrough)", line.strip(), re.I):
            fixed.append("## " + line.strip())
        else:
            fixed.append(line)
    return fixed

def detect_code_lang(block: str) -> str:
    """Guess code block language from contents."""
    b = block.strip().lower()
    if b.startswith("{") or b.startswith("[") or ":" in b and "{" in b:
        return "json"
    if b.startswith("$") or " sudo " in b:
        return "bash"
    if "func " in b or "package main" in b:
        return "go"
    if "def " in b or "import " in b:
        return "python"
    return "text"

def wrap_code_blocks(text):
    """Ensure code fences are balanced and labeled with language."""
    out, in_code, buffer = [], False, []
    for line in text.splitlines():
        if line.strip().startswith("```"):
            if in_code:
                # close block
                lang = detect_code_lang("\n".join(buffer))
                out[-1] = f"```{lang}"  # replace opening
                out.extend(buffer)
                out.append("```")
                buffer, in_code = [], False
            else:
                # open block
                out.append("```")  # placeholder, replaced at close
                buffer, in_code = [], True
        else:
            if in_code:
                buffer.append(line)
            else:
                out.append(line)
    # flush unterminated
    if buffer:
        lang = detect_code_lang("\n".join(buffer))
        out[-1] = f"```{lang}"
        out.extend(buffer)
        out.append("```")
    return "\n".join(out)

def format_markdown(raw_text, source, title, category, keywords):
    """Produce clean Markdown suitable for RAG ingestion."""
    lines = raw_text.splitlines()
    lines = clean_lines(lines)
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

