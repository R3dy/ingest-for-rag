import re
from pathlib import Path
from typing import Dict, List

import fitz  # pymupdf
from tqdm import tqdm

from .text_utils import normalize_ws, chunk_docs


def find_pdfs(directory: str) -> List[Path]:
    """Recursively find all PDF files in a directory."""
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"Not a directory: {directory}")
    pdfs = sorted(root.rglob("*.pdf"))
    if not pdfs:
        raise ValueError(f"No PDF files found in {directory}")
    return pdfs


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract text from all pages of a PDF using PyMuPDF."""
    doc = fitz.open(str(pdf_path))
    pages = []
    for page in doc:
        text = page.get_text("text")
        if text and text.strip():
            pages.append(text)
    doc.close()
    return "\n\n".join(pages)


def extract_pdf_title(pdf_path: Path, text: str) -> str:
    """Try to extract a meaningful title from PDF metadata or first heading."""
    try:
        doc = fitz.open(str(pdf_path))
        meta = doc.metadata
        doc.close()
        if meta and meta.get("title") and meta["title"].strip():
            return meta["title"].strip()
    except Exception:
        pass

    # Fallback: use first non-empty line as title
    for line in text.splitlines():
        line = line.strip()
        if line and len(line) > 3:
            # Truncate very long first lines
            return line[:120]

    return pdf_path.stem.replace("_", " ").replace("-", " ").title()


def ingest_pdfs(directory: str, out_dir: str, debug: bool = False) -> List[Dict]:
    """
    Process all PDF files in a directory and return raw page records
    compatible with the existing pipeline.

    Returns list of: [{source, path, kind, text, title}]
    """
    pdf_files = find_pdfs(directory)
    raw_dir = Path(out_dir, "raw")
    raw_dir.mkdir(parents=True, exist_ok=True)

    records: List[Dict] = []
    pbar = tqdm(pdf_files, desc="Processing PDFs", unit="file")

    for pdf_path in pbar:
        pbar.set_postfix_str(pdf_path.name[:40])

        try:
            raw_text = extract_pdf_text(pdf_path)
            if not raw_text.strip():
                if debug:
                    print(f"[ingest_pdf] Skipping empty PDF: {pdf_path}")
                continue

            text = normalize_ws(raw_text)
            title = extract_pdf_title(pdf_path, text)

            # Write raw extracted text to output
            safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", pdf_path.name.lower())
            raw_path = raw_dir / f"{safe_name}.txt"
            raw_path.write_text(text, encoding="utf-8")

            # Use the absolute path as the source identifier
            source = str(pdf_path.resolve())

            records.append({
                "source": source,
                "path": str(raw_path),
                "kind": "pdf",
                "text": text,
                "title": title,
            })

            if debug:
                print(f"[ingest_pdf] Extracted {len(text)} chars from {pdf_path.name}")

        except Exception as e:
            print(f"Failed to process {pdf_path}: {e}")
            continue

    pbar.close()
    print(f"Extracted text from {len(records)}/{len(pdf_files)} PDF files.")
    return records


def chunk_records_for_pdf(records: List[Dict], debug: bool = False) -> List[Dict]:
    """Chunk PDF records into smaller pieces for embedding."""
    chunks: List[Dict] = []
    for rec in records:
        chs = chunk_docs(rec["text"], debug=debug)
        for i, ch in enumerate(chs):
            chunks.append({
                "source": rec["source"],
                "path": rec["path"],
                "kind": rec["kind"],
                "chunk_id": i,
                "text": ch,
                "mode": "pdf",
                "title": rec.get("title"),
            })
    return chunks
