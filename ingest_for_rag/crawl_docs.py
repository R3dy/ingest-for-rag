import os
import re
from urllib.parse import urljoin, urldefrag, urlparse
from urllib import robotparser
from typing import Dict, List, Optional, Set
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

from .text_utils import safe_decode, normalize_ws, DOC_EXTS, is_probably_binary, chunk_docs

HEADERS = {"User-Agent": "ingest-for-rag/0.1 (+https://github.com/)"}


def same_domain(root: str, candidate: str) -> bool:
    rp = urlparse(root)
    cp = urlparse(candidate)
    return rp.netloc == cp.netloc and cp.scheme in ("http", "https")


def get_robots_ok(start_url: str, ignore_robots: bool) -> robotparser.RobotFileParser:
    rp = robotparser.RobotFileParser()
    if ignore_robots:
        rp.can_fetch = lambda agent, url: True  # type: ignore
        return rp
    base = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
    robots_url = urljoin(base, "/robots.txt")
    try:
        rp.set_url(robots_url)
        rp.read()
    except Exception:
        pass
    return rp


def extract_links(html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        href, _ = urldefrag(href)
        links.add(href)
    return list(links)


def extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    return normalize_ws(text)


def should_keep_url(u: str, include_globs: Optional[List[str]], exclude_globs: Optional[List[str]]) -> bool:
    from fnmatch import fnmatch
    if exclude_globs:
        for g in exclude_globs:
            if fnmatch(u.lower(), g.lower()):
                return False
    if include_globs:
        for g in include_globs:
            if fnmatch(u.lower(), g.lower()):
                return True
        return False
    return True


def crawl(start_url: str,
          out_dir: str,
          max_pages: int = 5000,
          ignore_robots: bool = False,
          include: Optional[List[str]] = None,
          exclude: Optional[List[str]] = None) -> List[Dict]:
    """
    Returns list of raw page records: [{url, path, kind, text}]
    """
    visited: Set[str] = set()
    queue: List[str] = [start_url]
    rp = get_robots_ok(start_url, ignore_robots)
    raw_dir = Path(out_dir, "raw")
    raw_dir.mkdir(parents=True, exist_ok=True)

    records: List[Dict] = []
    pbar = tqdm(total=max_pages, desc="Crawling", unit="page")

    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        if not same_domain(start_url, url):
            continue
        if not rp.can_fetch("*", url):
            continue
        if not should_keep_url(url, include, exclude):
            continue

        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            ct = r.headers.get("Content-Type", "").lower()
            if "text/html" not in ct and not any(url.lower().endswith(ext) for ext in DOC_EXTS):
                continue
            if is_probably_binary(url):
                continue

            content = safe_decode(r.content)
            text = ""
            kind = "html"
            if url.lower().endswith((".md", ".markdown", ".txt")):
                text = normalize_ws(content)
                kind = "markdown" if url.lower().endswith((".md", ".markdown")) else "text"
            else:
                text = extract_visible_text(content)
                kind = "html"

            safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", url.lower())
            raw_path = raw_dir / f"{safe_name}.txt"
            raw_path.write_text(text, encoding="utf-8")

            records.append({
                "url": url,
                "path": str(raw_path),
                "kind": kind,
                "text": text,
            })

            if "text/html" in ct:
                links = extract_links(content, url)
                for ln in links:
                    if ln not in visited and same_domain(start_url, ln):
                        queue.append(ln)

        except Exception:
            pass

        pbar.update(1)

    pbar.close()
    return records


def chunk_records_for_docs(records: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    for rec in records:
        chunks = chunk_docs(rec["text"])
        for i, ch in enumerate(chunks):
            out.append({
                "source": rec["url"],
                "path": rec["path"],
                "kind": rec["kind"],
                "chunk_id": i,
                "text": ch,
                "meta": {"mode": "docs"},
            })
    return out

