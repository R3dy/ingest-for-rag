import json
from typing import Dict, Iterable, List
from pathlib import Path
from chromadb import PersistentClient


def ensure_dirs(out_dir: str):
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(out_dir, "raw").mkdir(parents=True, exist_ok=True)
    Path(out_dir, "processed").mkdir(parents=True, exist_ok=True)
    Path(out_dir, "chroma").mkdir(parents=True, exist_ok=True)


def collection_name_from_source(source: str) -> str:
    # Simple safe-name builder
    name = source.lower().replace("https://", "").replace("http://", "")
    name = name.replace("/", "_").replace(":", "_")
    return name[:60]


def write_jsonl(path: str, rows: Iterable[Dict]):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def build_chroma(out_dir: str,
                 rows: List[Dict],
                 collection_name: str,
                 use_chroma: bool = True):
    if not use_chroma:
        return
    client = PersistentClient(path=str(Path(out_dir, "chroma")))
    col = client.get_or_create_collection(collection_name)

    ids, docs, metas, embs = [], [], [], []
    for r in rows:
        if "embedding" not in r or r["embedding"] is None:
            continue
        ids.append(r["id"])
        docs.append(r["text"])
        metas.append({k: v for k, v in r.items() if k not in ("text", "embedding")})
        embs.append(r["embedding"])

    if ids:
        col.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=embs)

