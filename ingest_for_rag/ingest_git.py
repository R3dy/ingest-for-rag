import os
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests
from tqdm import tqdm

from .text_utils import safe_decode, normalize_ws, CODE_EXTS, DOC_EXTS, is_probably_binary, chunk_code, chunk_docs

GH_API = "https://api.github.com"
RAW_HOST = "https://raw.githubusercontent.com"


def _parse_github(url: str):
    p = urlparse(url)
    parts = [x for x in p.path.strip("/").split("/") if x]
    if len(parts) < 2:
        raise ValueError("GitHub URL must be like https://github.com/owner/repo[...].")
    owner, repo = parts[0], parts[1]
    return owner, repo


def _github_headers(token: Optional[str]):
    h = {"User-Agent": "ingest-for-rag/0.1"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def list_repo_files_github(url: str, token: Optional[str]) -> Dict:
    owner, repo = _parse_github(url)
    r = requests.get(f"{GH_API}/repos/{owner}/{repo}", headers=_github_headers(token), timeout=20)
    r.raise_for_status()
    default_branch = r.json()["default_branch"]

    r = requests.get(
        f"{GH_API}/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1",
        headers=_github_headers(token),
        timeout=30,
    )
    r.raise_for_status()
    tree = r.json().get("tree", [])
    files = [t for t in tree if t.get("type") == "blob"]
    return {
        "owner": owner,
        "repo": repo,
        "branch": default_branch,
        "files": files,
    }


def fetch_text_files(data: Dict,
                     out_dir: str,
                     include_docs: bool = True,
                     include_code: bool = True) -> List[Dict]:
    owner = data["owner"]
    repo = data["repo"]
    branch = data["branch"]
    files = data["files"]

    raw_dir = Path(out_dir, "raw")
    raw_dir.mkdir(parents=True, exist_ok=True)

    records: List[Dict] = []
    pbar = tqdm(files, desc="Fetching repo files", unit="file")

    for f in pbar:
        path = f["path"]
        lower = path.lower()

        from pathlib import Path as _P
        ext = _P(lower).suffix

        if is_probably_binary(lower):
            continue

        is_doc = ext in DOC_EXTS
        is_code = (ext in CODE_EXTS) or (ext == "" and "/" not in lower and lower == "dockerfile")

        if (include_docs and is_doc) or (include_code and is_code):
            raw_url = f"{RAW_HOST}/{owner}/{repo}/{branch}/{path}"
            try:
                rr = requests.get(raw_url, timeout=30)
                if rr.status_code != 200:
                    continue
                text = normalize_ws(safe_decode(rr.content))

                disk_path = raw_dir / f"{owner}__{repo}__{path.replace('/', '__')}.txt"
                disk_path.parent.mkdir(parents=True, exist_ok=True)
                disk_path.write_text(text, encoding="utf-8")

                kind = "doc" if is_doc else "code"

                records.append({
                    "url": raw_url,
                    "path": str(disk_path),
                    "kind": kind,
                    "text": text,
                })
            except Exception:
                continue

    return records


def chunk_records_for_git(records: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    for rec in records:
        if rec["kind"] == "code":
            chunks = chunk_code(rec["text"])
        else:
            chunks = chunk_docs(rec["text"])
        for i, ch in enumerate(chunks):
            out.append({
                "source": rec["url"],
                "path": rec["path"],
                "kind": rec["kind"],
                "chunk_id": i,
                "text": ch,
                "mode": "git"
            })
    return out

