import os
import re
import argparse
from pathlib import Path


def clean_file(path: Path, debug=False):
    """Clean a single markdown file in place."""
    if debug:
        print(f"[cleanup] Processing {path}")

    text = path.read_text(encoding="utf-8")

    # 1. Strip known junk patterns (generic, not Mythic-specific)
    junk_patterns = [
        r"\bhome page\b",
        r"\bnavigation\b",
        r"\bsearch\b",
        r"\bissues\b",
        r"\bgithub\b",
        r"\bslack\b",
        r"\bwas this page helpful\b",
        r"\bcopy\b",
        r"\bask ai\b",
        r"⌘",
        r"\bversion\s+\d+(\.\d+)*",
        r"\bassistant\b",
        r"\bresponses are generated.*",  # boilerplate disclaimers
    ]
    for pat in junk_patterns:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)

    # 2. Collapse duplicate consecutive lines
    lines = text.splitlines()
    deduped = []
    for line in lines:
        if not deduped or deduped[-1].strip() != line.strip():
            deduped.append(line)
    text = "\n".join(deduped)

    # 3. Fix malformed code fences (ensure each ``` closes properly)
    # If there are odd numbers of fences, add a closing one
    fence_count = text.count("```")
    if fence_count % 2 != 0:
        if debug:
            print(f"[cleanup] Fixing unbalanced code fence in {path}")
        text += "\n```"

    # 4. Split multi-example code blocks
    def split_multi_examples(match):
        block = match.group(0)
        if block.count("{") > 1:  # multiple JSON objects, for example
            parts = re.split(r"\n\s*or\s*\n", block, flags=re.IGNORECASE)
            return "\n\n".join(parts)
        return block

    text = re.sub(r"```[a-z]*[\s\S]*?```", split_multi_examples, text)

    # 5. Remove long trailing TOC-like blocks (heuristic: 10+ consecutive short lines)
    lines = text.splitlines()
    cleaned_lines, buffer = [], []
    for line in lines:
        if 1 <= len(line.strip()) <= 20:  # suspiciously short
            buffer.append(line)
            if len(buffer) > 10:
                buffer = []  # drop this block
        else:
            if buffer:
                cleaned_lines.extend(buffer)
                buffer = []
            cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    # Save cleaned file
    path.write_text(text.strip() + "\n", encoding="utf-8")


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

