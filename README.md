# ingest-for-rag

A one-command ingestion tool for building **Retrieval-Augmented Generation (RAG)** datasets from:

- **Docs sites** (Markdown, HTML, TXT, etc.)
- **GitHub repositories** (source code + docs)
- **PDF directories** (bulk PDF text extraction)

It crawls, fetches, or extracts content, chunks it intelligently, embeds it with **[Ollama](https://ollama.ai/)**, and saves the results in multiple formats:

- **Raw text dumps** (`output/raw/`)  
- **Processed JSONL with embeddings** (`output/processed/entries.jsonl`)  
- **Chroma DB vector store** (`output/chroma/`)  
- **Markdown files (one per page)** (`output/md/`) → ready for **OpenWebUI Knowledgebase ingestion**  

Built by Royce Davis with development assistance from **ChatGPT (OpenAI GPT-5)**.  

---

## ✨ Features

- **Docs mode**  
  Recursively crawls a documentation site. Respects `robots.txt` (unless overridden).  
  Extracts visible text from Markdown, HTML, and plain text files.  

- **Git mode**
  Fetches repo contents using the GitHub API (no full clone needed).
  Indexes source code and docs, skips binaries automatically.

- **PDF mode**
  Recursively scans a local directory for PDF files.
  Extracts text via [PyMuPDF](https://pymupdf.readthedocs.io/), pulls titles from PDF metadata with smart fallbacks, and feeds everything through the standard chunking/embedding pipeline.

- **Embeddings via Ollama**  
  Uses `ollama/api/embeddings` (default model: `nomic-embed-text`, configurable).  

- **Multi-output pipeline**  
  - JSONL file with chunked text + embeddings (portable, easy to re-use)  
  - Persistent Chroma DB for immediate semantic search  
  - Markdown export (one file per page, all chunks included) for OpenWebUI  

- **Streaming + batching**  
  Embeddings are done in batches (default 16) to reduce memory usage.  
  Each batch is streamed directly to JSONL/Chroma/Markdown → no massive memory spikes.  

---

## 🚀 Quickstart

### Install

```bash
git clone https://github.com/<your-username>/ingest-for-rag.git
cd ingest-for-rag
pip install -e .
```

### Basic usage

**Docs site:**

```bash
ingest-for-rag -u https://docs.mythic-c2.net -t docs -o ./output
```

**GitHub repo:**

```bash
export GITHUB_TOKEN=ghp_xxx   # optional for private repos / higher rate limits
ingest-for-rag -u https://github.com/MythicAgents/Medusa -t git -o ./output
```

**PDF directory:**

```bash
ingest-for-rag -t pdf -d /path/to/pdfs -o ./output
```

This recursively finds every `.pdf` under the given directory, extracts the
text from each file, chunks it, generates embeddings, and writes the same
multi-format output (JSONL, Chroma, Markdown) as the other modes.

You can combine it with the usual flags — for example, to skip Chroma and use
a remote Ollama instance:

```bash
ingest-for-rag -t pdf -d ./research-papers \
  --ollama-base http://gpu-box:11434 \
  --model nomic-embed-text \
  --no-chroma \
  -o ./output
```

---

## 📂 Output Structure

After a run, your `./output/` will look like:

```
output/
├── raw/                 # raw crawled text files
├── processed/
│   └── entries.jsonl    # chunked text + embeddings
├── chroma/              # persistent Chroma vector store
└── md/                  # 1 Markdown file per page (OpenWebUI KB)
    ├── Payload-Type-Development.md
    ├── Mythic-Installation.md
    └── ...
```

---

## ⚙️ Options

| Flag              | Description |
|-------------------|-------------|
| `-u, --url`       | Docs base URL or GitHub repo URL (required for `docs`/`git`) |
| `-t, --type`      | Ingestion type: `docs`, `git`, or `pdf` (required) |
| `-d, --dir`       | Directory containing PDF files (required for `pdf`) |
| `-o, --out`       | Output directory (required) |
| `--ignore-robots` | Ignore robots.txt in docs mode |
| `--max-pages`     | Max pages to crawl (default: 5000) |
| `--include`       | Comma-separated glob filters for docs mode |
| `--exclude`       | Comma-separated glob filters for docs mode |
| `--ollama-base`   | Ollama API base URL (default: http://localhost:11434) |
| `--model`         | Embedding model (default: `nomic-embed-text`) |
| `--batch-size`    | Batch size for embeddings (default: 16) |
| `--no-chroma`     | Skip building a Chroma index |
| `--debug`         | Enable verbose debug output |

---

## 🔗 Integration

### Use with Chroma directly

```python
from chromadb import PersistentClient

client = PersistentClient(path="output/chroma")
col = client.get_or_create_collection("docs_mythic_c2_net")

results = col.query(query_texts=["How do I configure Mythic Agents?"], n_results=3)
print(results["documents"])
```

### Use with OpenWebUI

- Point OpenWebUI’s **Knowledgebase ingestion** at `output/md/`  
- Each `.md` is one page with all its chunks, ready for semantic retrieval inside the chat UI.

---

## 🛠️ Development Notes

- Built with ❤️ by Royce Davis.  
- Code co-authored with **ChatGPT (OpenAI GPT-5)**, which helped write the core modules and CLI.  
- Licensed under **MIT** — feel free to fork, adapt, and improve.  

---

## 🙌 Contributing

PRs welcome! Ideas, bug fixes, and new features (multi-backend embeddings, other vector DBs, etc.) are encouraged.  

