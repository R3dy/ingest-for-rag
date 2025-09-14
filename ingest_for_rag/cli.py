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
from .text_utils import chunk_docs
from .formatter import format_markdown   # Markdown formatter


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


def safe_filename(name: str) -> str:
    """
    Sanitize filenames for .md exports:
    - only [a-zA-Z0-9._-]
    - collapse underscores
    - strip leading/trailing non-alphanumeric
    """
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    name = re.sub(r"_+", "_", name)
    name = re.sub(r"^[^a-zA-Z0-9]+", "", name)
    name = re.sub(r"[^a-zA-Z0-9]+$", "", name)
    if not name:
        name = "index"
    return name[:255]  # filesystem safe


def url_to_filename(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    base = path.replace("/", "_") if path else "index"
    return safe_filename(base)


def extract_rpc_calls(text: str):
    return list(set(re.findall(r"(Send\w+RPC\w+|MythicRPC\w+)", text)))


def generate_keywords(base_name: str, title: str, text: str) -> list:
    """
    Generate dynamic keywords from slug, title, rpc calls, and code block languages.
    """
    slug_parts = [part.lower() for part in re.split(r"[-_/]", base_name) if part]
    title_parts = [w.lower() for w in re.split(r"\W+", title) if w]
    rpc_calls = [rpc.lower() for rpc in extract_rpc_calls(text)]

    # detect code block languages
    code_langs = []
    for match in re.findall(r"```(\w+)", text):
        if match.lower() not in code_langs:
            code_langs.append(match.lower())

    keywords = set(slug_parts + title_parts + rpc_calls + code_langs)
    return sorted(keywords)


def safe_collection_name(source: str) -> str:
    """
    Sanitize a collection name to meet Chroma's requirements:
    - only [a-zA-Z0-9._-]
    - starts/ends with alphanumeric
    - length 3–512
    """
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", source)
    name = re.sub(r"_+", "_", name)
    name = re.sub(r"^[^a-zA-Z0-9]+", "", name)
    name = re.sub(r"[^a-zA-Z0-9]+$", "", name)
    if len(name) < 3:
        name = f"col_{name}"
    return name[:512]


def main():
    load_dotenv()
    args = parse_args()

    from .embeddings import embed_ollama

    out_dir = args.out
    ensure_dirs(out_dir)

    include = [g.strip() for g in args.include.split(",") if g.strip()] or None
    exclude = [g.strip() for g in args.exclude.split(",") if g.strip()] or None

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
        for idx, rec in enumerate(raw_pages):
            if args.debug:
                print(f"[main] Processing record {idx+1}/{len(raw_pages)} ({len(rec['text'])} chars)")
            chs = chunk_docs(rec["text"], debug=args.debug)
            if args.debug:
                print(f"[main] Record produced {len(chs)} chunks")
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

    # Outputs
    jsonl_path = Path(out_dir, "processed", "entries.jsonl")
    md_dir = Path(out_dir, "md")
    md_dir.mkdir(parents=True, exist_ok=True)

    coll_name_raw = collection_name_from_source(args.url)
    coll_name = safe_collection_name(coll_name_raw)

    client = None
    col = None
    if not args.no_chroma:
        from chromadb import PersistentClient
        client = PersistentClient(path=str(Path(out_dir, "chroma")))
        col = client.get_or_create_collection(coll_name)

    rows = []
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for i in range(0, len(chunks), args.batch_size):
            if args.debug:
                print(f"[main] Embedding batch {i//args.batch_size+1}")
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

    # Markdown export
    pages = defaultdict(list)
    texts = defaultdict(str)
    titles = {}
    for row in rows:
        pages[row["source"]].append(row)
        texts[row["source"]] += "\n" + row["text"]
        titles[row["source"]] = row.get("title")

    all_sources = set(texts.keys()) | set(pages.keys())
    for source in all_sources:
        base_name = url_to_filename(source)
        md_path = md_dir / f"{base_name}.md"

        title = titles.get(source) or base_name.replace("_", " ").title()
        category = "/".join(base_name.split("_")[:-1]) or "root"
        raw_text = texts.get(source, "").strip()

        keywords = generate_keywords(base_name, title, raw_text)

        md_text = format_markdown(
            raw_text,
            source=source,
            title=title,
            category=category,
            keywords=keywords,
        )
        md_path.write_text(md_text, encoding="utf-8")

    print(f"\n🎉 Ingestion complete.\n- JSONL: {jsonl_path}\n- Markdown: {md_dir}\n- Chroma: {Path(out_dir, 'chroma')}\n")


if __name__ == "__main__":
    main()

