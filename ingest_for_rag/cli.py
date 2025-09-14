import argparse
import os
import sys
import uuid
import json
import re
from pathlib import Path
from collections import defaultdict
from urllib.parse import urlparse

from dotenv import load_dotenv

from .crawl_docs import crawl
from .ingest_git import list_repo_files_github, fetch_text_files, chunk_records_for_git
from .storage import ensure_dirs, collection_name_from_source


def parse_args():
    p = argparse.ArgumentParser(
        prog="ingest-for-rag",
        description="Ingest a docs site or GitHub repo and build embeddings for RAG (Ollama + Chroma + Markdown).",
    )
    p.add_argument("-u", "--url", required=True, help="Docs site base URL or GitHub repo URL")
    p.add_argument("-t", "--type", choices=["docs", "git"], required=True, help="Ingestion type")
    p.add_argument("-o", "--out", required=True, help="Output directory")
    p.add_argument("--ignore-robots", action="store_true", help="Ignore robots.txt (docs mode)")
    p.add_argument("--max-pages", type=int, default=5000, help="Max pages to crawl (docs mode)")
    p.add_argument("--include", default="", help="Comma-separated glob filters to include (docs mode)")
    p.add_argument("--exclude", default="", help="Comma-separated glob filters to exclude (docs mode)")
    p.add_argument("--ollama-base", default=None, help="Override OLLAMA_BASE")
    p.add_argument("--model", default=None, help="Ollama embedding model (default from .env or nomic-embed-text)")
    p.add_argument("--batch-size", type=int, default=16, help="Batch size for embedding calls")
    p.add_argument("--no-chroma", action="store_true", help="Skip building a Chroma index")
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    return p.parse_args()


def url_to_filename(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return "index"
    return path.replace("/", "_")


def extract_rpc_calls(text: str):
    """Find RPC/API call names in text."""
    return list(set(re.findall(r"(Send\w+RPC\w+|MythicRPC\w+)", text)))


def generate_keywords(base_name: str, title: str, text: str) -> list:
    """Generate dynamic keywords per page from slug, title, and RPC calls."""
    slug_parts = [part.lower() for part in re.split(r"[-_/]", base_name) if part]
    title_parts = [w.lower() for w in re.split(r"\W+", title) if w]
    rpc_calls = [rpc.lower() for rpc in extract_rpc_calls(text)]
    keywords = set(slug_parts + title_parts + rpc_calls)
    return sorted(keywords)


def annotate_code_blocks(text: str) -> str:
    """Add semantic headings above fenced code blocks."""
    out_lines = []
    for line in text.splitlines():
        if line.strip().startswith("```"):
            lang = line.strip().lstrip("`").lower()
            if "json" in lang:
                out_lines.append("## Example JSON Block")
            elif "python" in lang:
                out_lines.append("## Example Python Block")
            elif "bash" in lang or "sh" in lang:
                out_lines.append("## Example Shell Block")
            elif "yaml" in lang or "yml" in lang:
                out_lines.append("## Example YAML Block")
            else:
                out_lines.append("## Example Code Block")
            out_lines.append(line)  # keep the code fence
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def clean_nav_footer_noise(text: str) -> str:
    """
    Remove common nav/footer/sidebar noise to keep markdown focused.
    """
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        low = line.lower().strip()
        if not line.strip():
            continue
        # Drop common UI/nav/footer lines
        if "home page" in low or "search" in low or "navigation" in low:
            continue
        if "issues" in low or "github" in low or "slack" in low:
            continue
        if "was this page helpful" in low or "assistant" in low:
            continue
        if low in {"yes", "no"}:
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def main():
    load_dotenv()
    args = parse_args()

    from .embeddings import embed_ollama
    from .text_utils import chunk_docs

    out_dir = args.out
    ensure_dirs(out_dir)

    include = [g.strip() for g in args.include.split(",") if g.strip()] or None
    exclude = [g.strip() for g in args.exclude.split(",") if g.strip()] or None

    source = args.url

    if args.type == "docs":
        raw_pages = crawl(
            start_url=args.url,
            out_dir=out_dir,
            max_pages=args.max_pages,
            ignore_robots=args.ignore_robots,
            include=include,
            exclude=exclude,
        )
        chunks = []
        for rec in raw_pages:
            chs = chunk_docs(rec["text"])
            for i, ch in enumerate(chs):
                chunks.append({
                    "source": rec["url"],
                    "path": rec["path"],
                    "kind": rec["kind"],
                    "chunk_id": i,
                    "text": ch,
                    "mode": "docs",
                    "title": rec.get("title"),
                })
    else:
        token = os.environ.get("GITHUB_TOKEN", "")
        meta = list_repo_files_github(args.url, token or None)
        recs = fetch_text_files(meta, out_dir)
        chunks = chunk_records_for_git(recs)

    # --- Setup outputs ---
    jsonl_path = Path(out_dir, "processed", "entries.jsonl")
    md_dir = Path(out_dir, "md")
    md_dir.mkdir(parents=True, exist_ok=True)

    coll_name = collection_name_from_source(source)
    client = None
    col = None
    if not args.no_chroma:
        from chromadb import PersistentClient
        client = PersistentClient(path=str(Path(out_dir, "chroma")))
        col = client.get_or_create_collection(coll_name)

    rows = []
    written = 0
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for i in range(0, len(chunks), args.batch_size):
            batch = chunks[i:i+args.batch_size]
            texts = [c["text"] for c in batch]
            embs = embed_ollama(texts, model=args.model, base=args.ollama_base)

            ids, docs, metas = [], [], []
            for c, emb in zip(batch, embs):
                rid = str(uuid.uuid4())
                row = {"id": rid, **c, "embedding": emb}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                rows.append(row)

                ids.append(rid)
                docs.append(c["text"])
                metas.append({k: v for k, v in c.items() if k not in ("text", "embedding")})

            if col and ids:
                col.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=embs)

            written += len(batch)
            print(f"✅ Processed {written}/{len(chunks)}")

    # --- Markdown export (one file per page, always) ---
    pages = defaultdict(list)
    texts = {}
    titles = {}

    for row in rows:
        pages[row["source"]].append(row)
        texts[row["source"]] = row["text"]
        titles[row["source"]] = row.get("title")

    all_sources = set(texts.keys()) | set(pages.keys())

    for source in all_sources:
        page_chunks = pages.get(source, [])
        base_name = url_to_filename(source)
        md_path = md_dir / f"{base_name}.md"

        title = titles.get(source) or base_name.replace("_", " ").title()
        category = "/".join(base_name.split("_")[:-1]) or "root"
        raw_text = texts.get(source, "").strip()
        combined_text = " ".join(c["text"] for c in page_chunks) if page_chunks else raw_text

        # Clean nav/footer noise
        combined_text = clean_nav_footer_noise(combined_text)

        # Dynamic keywords per page
        keywords = generate_keywords(base_name, title, combined_text)
        rpc_calls = extract_rpc_calls(combined_text)

        with open(md_path, "w", encoding="utf-8") as md_file:
            # YAML front-matter
            md_file.write(f"---\n")
            md_file.write(f"source: {source}\n")
            md_file.write(f"title: {title}\n")
            md_file.write(f"category: {category}\n")
            if keywords:
                md_file.write("keywords: " + ", ".join(keywords) + "\n")
            md_file.write(f"---\n\n")

            md_file.write(f"# {title}\n\n")

            if page_chunks:
                for c in sorted(page_chunks, key=lambda x: x["chunk_id"]):
                    text = clean_nav_footer_noise(c["text"].strip())
                    if text:
                        text = annotate_code_blocks(text)
                        md_file.write(text + "\n\n")
            else:
                if raw_text:
                    raw_text = annotate_code_blocks(clean_nav_footer_noise(raw_text))
                    md_file.write(raw_text + "\n")

            # RPC promotion
            if rpc_calls:
                md_file.write("\n## RPC Calls\n\n")
                for rpc in rpc_calls:
                    md_file.write(f"### RPC: {rpc}\n\n")
                    md_file.write(f"Reference to `{rpc}` found in this page.\n\n")

    print(f"\n🎉 Ingestion complete.\n"
          f"- JSONL: {jsonl_path}\n"
          f"- Markdown: {md_dir}\n"
          f"- Chroma: {Path(out_dir, 'chroma')}\n"
          f"- Entries: {written}")


if __name__ == "__main__":
    main()

