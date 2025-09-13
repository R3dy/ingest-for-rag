import re
from urllib.parse import urljoin, urldefrag, urlparse
from urllib import robotparser
from typing import Dict, List, Optional, Set
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

from .text_utils import safe_decode, normalize_ws, DOC_EXTS, is_probably_binary

HEADERS = {"User-Agent": "ingest-for-rag/0.2 (+https://github.com/)"}


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


def extract_title(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return None


def extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Prefer <main> or <article>
    main = soup.find("main") or soup.find("article") or soup

    # Remove junky elements
    for tag in main(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # Inline <code>
    for code in main.find_all("code"):
        if code.string:
            code.replace_with(f"`{code.string.strip()}`")

    # Pre/code blocks with language hints
    for pre in main.find_all("pre"):
        text = pre.get_text().strip()
        lang = "json" if text.startswith("{") or text.startswith("[") else "bash"
        pre.replace_with(f"\n```{lang}\n{text}\n```\n")

    # Convert headings to Markdown
    for level in range(1, 7):
        for h in main.find_all(f"h{level}"):
            txt = h.get_text().strip()
            h.replace_with(f"\n{'#' * level} {txt}\n")

    text = main.get_text("\n", strip=True)
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
    Returns list of raw page records: [{url, path, kind, text, title}]
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
            title = None
            if url.lower().endswith((".md", ".markdown", ".txt")):
                text = normalize_ws(content)
                kind = "markdown" if url.lower().endswith((".md", ".markdown")) else "text"
            else:
                text = extract_visible_text(content)
                kind = "html"
                title = extract_title(content)

            safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", url.lower())
            raw_path = raw_dir / f"{safe_name}.txt"
            raw_path.write_text(text, encoding="utf-8")

            records.append({
                "url": url,
                "path": str(raw_path),
                "kind": kind,
                "text": text,
                "title": title,
            })

            # enqueue links
            if "text/html" in ct:
                for a in BeautifulSoup(content, "html.parser").find_all("a", href=True):
                    ln = urljoin(url, a["href"])
                    ln, _ = urldefrag(ln)
                    if ln not in visited and same_domain(start_url, ln):
                        queue.append(ln)

        except Exception:
            pass

        pbar.update(1)

    pbar.close()
    return records

