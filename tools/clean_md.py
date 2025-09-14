import os
import re
import argparse
from pathlib import Path


def remove_toc_blocks(lines, min_run=5, max_len=40):
    """
    Remove TOC-like blocks: runs of many short lines (outside code).
    """
    cleaned, buffer = [], []
    for line in lines:
        if len(line.strip()) <= max_len and not line.strip().startswith("```"):
            buffer.append(line)
            if len(buffer) >= min_run:
                buffer = []  # drop
        else:
            if buffer:
                cleaned.extend(buffer)
                buffer = []
            cleaned.append(line)
    return cleaned


def split_multi_json_blocks(text):
    """
    If a ```json block has multiple { } objects, split into separate blocks.
    """
    def replacer(match):
        block = match.group(0)
        header = block.splitlines()[0]
        footer = block.splitlines()[-1]
        body = "\n".join(block.splitlines()[1:-1]).strip()

        # Look for multiple root objects
        objects = re.split(r"\n\s*or\s*(even)?\s*\n", body, flags=re.IGNORECASE)
        if len(objects) > 1:
            parts = []
            for obj in objects:
                obj = obj.strip()
                if obj:
                    parts.append(f"{header}\n{obj}\n{footer}")
            return "\n\n".join(parts)
        return block

    return re.sub(r"```json[\s\S]*?```", replacer, text)


def clean_file(path: Path, debug=False):
    if debug:
        print(f"[cleanup] Processing {path}")

    original = path.read_text(encoding="utf-8")

    # Separate front matter (if present)
    front, body = "", original
    if original.startswith("---"):
        parts = original.split("---", 2)
        if len(parts) >= 3:
            front = "---" + parts[1] + "---\n\n"
            body = parts[2]

    # Remove obvious junk
    junk_patterns = [
        r"\bhome page\b",
        r"\bsearch\b",
        r"\bissues\b",
        r"\bslack\b",
        r"\bwas this page helpful\b",
        r"\bcopy\b",
        r"\bask ai\b",
        r"⌘",
        r"\bversion\s+\d+(\.\d+)*",
        r"\bassistant\b",
        r"\bresponses are generated.*",
    ]
    for pat in junk_patterns:
        body = re.sub(pat, "", body, flags=re.IGNORECASE)

    # Collapse duplicate consecutive lines
    lines = body.splitlines()
    deduped = []
    for line in lines:
        if not deduped or deduped[-1].strip() != line.strip():
            deduped.append(line)

    # Remove TOC-like blocks
    deduped = remove_toc_blocks(deduped)

    body = "\n".join(deduped)

    # Split multi-example JSON blocks but KEEP fences
    body = split_multi_json_blocks(body)

    # Balance fences if needed
    if body.count("```") % 2 != 0:
        body += "\n```"

    cleaned = front + body.strip() + "\n"
    path.write_text(cleaned, encoding="utf-8")

    if debug:
        print(f"[cleanup] Finished {path}")


def main():
    parser = argparse.ArgumentParser(description="Clean up exported Markdown docs")
    parser.add_argument("dir", help="Directory containing .md files")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    args = parser.parse_args()

    md_dir = Path(args.dir)
    if not md_dir.exists():
        print(f"❌ Directory not found: {md_dir}")
        return

    for md_file in md_dir.rglob("*.md"):
        clean_file(md_file, debug=args.debug)

    print("✅ Cleanup complete.")


if __name__ == "__main__":
    main()

