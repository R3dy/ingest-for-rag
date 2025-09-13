import json
import os
import requests
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

DEFAULT_OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
DEFAULT_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")

def embed_ollama(texts: List[str],
                 model: Optional[str] = None,
                 base: Optional[str] = None) -> List[List[float]]:
    """
    Calls Ollama /api/embeddings for each text, returns list of vectors.
    Adds logging and enforces per-item timeout.
    """
    base = base or DEFAULT_OLLAMA_BASE
    model = model or DEFAULT_EMBED_MODEL
    url = f"{base.rstrip('/')}/api/embeddings"

    vectors = []
    for i, t in enumerate(texts):
        payload = {"model": model, "prompt": t}
        try:
            print(f"⚡ Embedding {len(t)} chars (item {i+1}/{len(texts)})...")
            r = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,          # ✅ this ensures proper JSON encoding
                timeout=60,
            )
            r.raise_for_status()
            data = r.json()
            vec = data.get("embedding")
            if not vec:
                raise RuntimeError(f"Ollama response missing 'embedding': {data}")
            vectors.append(vec)
        except Exception as e:
            print(f"❌ Embedding failed: {e}")
            vectors.append(None)
    return vectors
