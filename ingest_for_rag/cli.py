import argparse
import os
import sys
import uuid
import json
from pathlib import Path
from collections import defaultdict

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

    # --- Crawl or ingest ---
    if args.type == "docs":
        if args.debug:
            print("🔎 DEBUG: starting crawl()", flush=True)
        raw_pages = crawl(
            start_url=args.url,
            out_dir=out_dir,
            max_pages=args.max_pages,
            ignore_robots=args.ignore_robots,
            include=include,
            exclude=exclude,
        )
        if args.debug:
            print(f"🔎 DEBUG: crawl() returned {len(raw_pages)} pages", flush=True)

        chunks = []
        for r_idx, rec in enumerate(raw_pages):
            if args.debug:
                print(f"   DEBUG: record {r_idx} has {len(rec['text'])} chars", flush=True)
            chs = chunk_docs(rec["text"])
            if args.debug:
                print(f"   DEBUG: record {r_idx} produced {len(chs)} chunks", flush=True)
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
        if args.debug:
            print("🔎 DEBUG: starting GitHub ingest", flush=True)
        token = os.environ.get("GITHUB_TOKEN", "")
        meta = list_repo_files_github(args.url, token or None)
        recs = fetch_text_files(meta, out_dir)
        chunks = chunk_records_for_git(recs)

    if args.debug:
        print(f"🔎 DEBUG: entering embedding phase with {len(chunks)} chunks", flush=True)
        for idx, c in enumerate(chunks[:5]):
            print(f"   Chunk {idx}: {len(c['text'])} chars", flush=True)

    # --- Output dirs ---
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

            if args.debug:
                print(f"⚡ DEBUG: embedding batch {i//args.batch_size+1} "
                      f"of {((len(chunks)-1)//args.batch_size)+1} "
                      f"({len(batch)} chunks)", flush=True)

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

    # --- Group Markdown export (one file per page) ---
    pages = defaultdict(list)
    titles = {}
    for row in rows:
        pages[row["source"]].append(row)
        titles[row["source"]] = row.get("title")

    for source, page_chunks in pages.items():
        safe_title = titles.get(source) or Path(source).stem or "page"
        safe_title = safe_title.strip().replace(" ", "-").replace("/", "_").replace(":", "_")
        md_path = md_dir / f"{safe_title}.md"

        with open(md_path, "w", encoding="utf-8") as md_file:
            md_file.write(f"# Source: {source}\n\n")
            for c in sorted(page_chunks, key=lambda x: x["chunk_id"]):
                md_file.write(f"## Chunk {c['chunk_id']}\n\n")
                md_file.write(c["text"].strip() + "\n\n")

    print(f"\n🎉 Ingestion complete.\n"
          f"- JSONL: {jsonl_path}\n"
          f"- Markdown: {md_dir}\n"
          f"- Chroma: {Path(out_dir, 'chroma')}\n"
          f"- Entries: {written}")


if __name__ == "__main__":
    main()

