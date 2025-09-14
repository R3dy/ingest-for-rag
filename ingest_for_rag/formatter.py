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

def promote_headings(lines):
    """Turn section labels into real Markdown headings."""
    fixed = []
    for line in lines:
        if re.match(r"^(overview|reserved keywords|payloadtype|message keywords)", line.strip(), re.I):
            fixed.append("## " + line.strip())
        else:
            fixed.append(line)
    return fixed

def wrap_code_blocks(text):
    """Ensure fences are balanced and labeled."""
    # balance
    if text.count("```") % 2 != 0:
        text += "\n```"
    # label obvious json
    text = re.sub(r"```[\s]*\{", "```json\n{", text)
    return text

def format_markdown(raw_text, source, title, category, keywords):
    """Produce clean Markdown with metadata and body text."""
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

