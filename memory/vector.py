"""Vector store for semantic search. Lightweight — uses sqlite-vec or
falls back to simple keyword matching if dependencies unavailable.
DNA: Qwen3.8-Max (long context) + Astra (semantic compression).
"""

import json
from pathlib import Path
from typing import Optional


class VectorStore:
    """Semantic search over stored content. Lightweight by default."""

    def __init__(self, db_path: str = "~/.omnicore/vectors"):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._embeddings: list[dict] = []
        self._load()

    def add(self, text: str, metadata: Optional[dict] = None) -> None:
        """Index a piece of text for later retrieval."""
        # In a full implementation, we'd compute embeddings here.
        # For M2, we store text + metadata for keyword matching.
        entry = {
            "text": text,
            "metadata": metadata or {},
            "tokens": set(text.lower().split()),
        }
        self._embeddings.append(entry)
        self._save()

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Search for semantically similar content.
        
        Currently uses Jaccard similarity on tokens.
        Future: sentence-transformers embeddings.
        """
        query_tokens = set(query.lower().split())
        if not query_tokens:
            return []

        scored = []
        for entry in self._embeddings:
            entry_tokens = entry["tokens"]
            if not entry_tokens:
                continue
            # Jaccard similarity
            intersection = query_tokens & entry_tokens
            union = query_tokens | entry_tokens
            score = len(intersection) / len(union) if union else 0
            
            # Boost exact phrase matches
            if query.lower() in entry["text"].lower():
                score += 0.3

            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"score": round(s, 3), "text": e["text"][:500], "metadata": e["metadata"]}
            for s, e in scored[:top_k]
        ]

    def _save(self):
        """Persist to disk (simple JSON for M2)."""
        data = [{"text": e["text"], "metadata": e["metadata"]} for e in self._embeddings[-1000:]]
        (self.db_path / "index.json").write_text(json.dumps(data))

    def _load(self):
        index_file = self.db_path / "index.json"
        if index_file.exists():
            data = json.loads(index_file.read_text())
            self._embeddings = [
                {"text": d["text"], "metadata": d["metadata"], "tokens": set(d["text"].lower().split())}
                for d in data
            ]

    def clear(self):
        self._embeddings = []
        self._save()