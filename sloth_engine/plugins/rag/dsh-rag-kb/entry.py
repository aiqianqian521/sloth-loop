"""dsh-rag-kb (Python port) - local RAG knowledge base plugin.

Translated (concept port, not code copy) from the TS host plugin
@deepseek-ai/dsh-rag-kb by AlowEnsoul. Same contract surface:
  - JSON-persisted named knowledge bases
  - chunk + vector-embed + cosine retrieval
  - three model-facing tools: kb_search / kb_index / kb_status

Embeddings: uses a local Ollama /api/embed endpoint when configured
(config.plugins.rag.embed_url) AND reachable; otherwise falls back to a
deterministic local hash/bigram embedding so the plugin runs fully offline
(no network, no Ollama dependency for the loop task).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import uuid
from pathlib import Path

DIM = 384
TEXT_EXT = {".txt", ".md", ".markdown", ".json", ".py", ".ts", ".tsx", ".js",
            ".jsx", ".yml", ".yaml", ".csv", ".log", ".rst", ".ini", ".toml",
            ".html", ".htm"}
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "__pycache__", ".venv",
             "venv", ".cache"}


def _tokenize(t):
    return re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_]+", (t or "").lower())


def _local_embed(text):
    """Deterministic bag-of-bigrams hashed vector (offline fallback)."""
    v = [0.0] * DIM
    toks = _tokenize(text)
    if not toks:
        import warnings
        warnings.warn(f"RAG-08: _local_embed received text with zero tokens after _tokenize: {text[:120]!r}")
        return [0.0] * DIM
    grams = list(toks) + [(toks[i] + "_" + toks[i + 1]) for i in range(max(0, len(toks) - 1))]
    for g in grams:
        h = hashlib.blake2b(g.encode("utf-8"), digest_size=4).digest()
        idx = int.from_bytes(h, "big") % DIM
        sign = 1.0 if (h[0] & 1) == 0 else -1.0
        v[idx] += sign
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def _cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


def _chunk_text(text, size):
    size = max(1, int(size))
    pieces = [text[i:i + size] for i in range(0, len(text), size)]
    return [p for p in pieces if p.strip() != ""] or [text]


def _uid():
    return uuid.uuid4().hex[:8]


def _is_text(p: Path):
    return p.is_file() and p.suffix.lower() in TEXT_EXT


class _RagKb:
    def __init__(self, config):
        self.config = config or {}
        rag_cfg = (self.config.get("plugins") or {}).get("rag") or {}
        self.store_path = Path(rag_cfg.get("store_path") or "data/dsh-kb-store.json")
        self.embed_url = str(rag_cfg.get("embed_url") or "")
        self.embed_model = str(rag_cfg.get("embed_model") or "nomic-embed-text")
        self.chunk_chars = int(rag_cfg.get("chunk_chars") or 800)
        self._store = None
        self._ensure()

    def _ensure(self):
        if self._store is not None:
            return
        if self.store_path.exists():
            try:
                self._store = json.loads(self.store_path.read_text(encoding="utf-8"))
                if "kbs" not in self._store:
                    self._store = self._blank()
            except Exception:
                self._store = self._blank()
        else:
            self._store = self._blank()

    def _blank(self):
        return {"config": {"embed_url": self.embed_url, "embed_model": self.embed_model,
                           "chunk_chars": self.chunk_chars}, "kbs": []}

    def _save(self):
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(self._store, ensure_ascii=False, indent=2),
                                   encoding="utf-8")

    def _embed(self, texts):
        if self.embed_url:
            ov = self._ollama_embed(texts)
            if ov is not None:
                return ov
        return [_local_embed(t) for t in texts]

    def _ollama_embed(self, texts):
        try:
            import urllib.request
            body = json.dumps({"model": self.embed_model, "input": texts}).encode("utf-8")
            req = urllib.request.Request(
                self.embed_url.rstrip("/") + "/api/embed", data=body,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                j = json.loads(r.read().decode("utf-8"))
            vecs = j.get("embeddings")
            if isinstance(vecs, list) and len(vecs) == len(texts):
                return vecs
        except Exception:
            pass
        return None

    def _find_by_title(self, title):
        return next((k for k in self._store["kbs"] if k.get("title") == title), None)

    def list_kbs(self):
        out = []
        for k in self._store["kbs"]:
            files = {c.get("path", "") for c in k.get("chunks", [])}
            out.append({"id": k.get("id"), "title": k.get("title", ""),
                        "createdAt": k.get("createdAt", 0),
                        "fileCount": len(files), "chunkCount": len(k.get("chunks", []))})
        return out

    def index_path(self, path, kb_title):
        p = Path(path)
        if not p.exists():
            return {"ok": False, "error": f"path not found: {path}"}
        title = (str(kb_title or "").strip()) or "default-KB"
        kb = self._find_by_title(title)
        if kb is None:
            kb = {"id": _uid(), "title": title, "createdAt": int(time.time()), "chunks": []}
            self._store["kbs"].append(kb)
        added_files, chunks = self._add_paths(p)
        # RAG-06: hash-based dedup against existing chunks before adding
        existing_hashes = {c.get("_hash", "") for c in kb["chunks"] if c.get("_hash")}
        new_chunks = [c for c in chunks if c.get("_hash", "") not in existing_hashes]
        kb["chunks"].extend(new_chunks)
        added_files = len({c["path"] for c in new_chunks}) if new_chunks else 0
        self._save()
        return {"ok": True, "kb": kb["title"], "addedFiles": added_files,
                "addedChunks": len(chunks), "chunkCount": len(kb["chunks"])}

    def _add_paths(self, p):
        files = []
        if p.is_file():
            if _is_text(p):
                files = [p]
        else:
            for root, dirs, fs in os.walk(p):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for f in fs:
                    fp = Path(root) / f
                    if _is_text(fp):
                        files.append(fp)
        if not files:
            return 0, []
        texts, metas = [], []
        for fp in files:
            try:
                raw = fp.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for piece in _chunk_text(raw, self.chunk_chars):
                texts.append(piece)
                metas.append(str(fp))
        if not texts:
            return 0, []
        vecs = self._embed(texts)
        chunks = [{"path": m, "text": t, "vector": v} for t, m, v in zip(texts, metas, vecs)]
        chunks = [{"path": m, "text": t, "vector": v, "_hash": hashlib.md5(t.encode("utf-8")).hexdigest()[:16]} for t, m, v in zip(texts, metas, vecs)]
        # RAG-06: semantic dedup
        chunks = self._dedup_chunks(chunks)
        return len(files), chunks

    def _dedup_chunks(self, chunks: list[dict], threshold: float = 0.85) -> list[dict]:
        """RAG-06: Semantic deduplication via pairwise cosine similarity.

        Marks duplicate chunks where cosine similarity exceeds threshold.
        Keeps the later (newer) chunk in each duplicate pair.
        Returns the deduplicated list.
        """
        if len(chunks) <= 1:
            return chunks
        n = len(chunks)
        # Compute pairwise cosine; mark earlier index as duplicate
        duplicates: set[int] = set()
        for i in range(n):
            if i in duplicates:
                continue
            vi = chunks[i].get("vector", [])
            if not vi:
                continue
            for j in range(i + 1, n):
                if j in duplicates:
                    continue
                vj = chunks[j].get("vector", [])
                if not vj:
                    continue
                sim = _cosine(vi, vj)
                if sim > threshold:
                    # Keep the newer one (j is later in list)
                    duplicates.add(i)
                    break
        if duplicates:
            return [c for idx, c in enumerate(chunks) if idx not in duplicates]
        return chunks

    @staticmethod
    def _truncate_by_tokens(text: str, max_tokens: int = 100) -> str:
        """RAG-07: Token-aware truncation using len(text)/3.5 estimation.

        Replaces fixed-character cutoff with an accumulate-until-budget-exhausted
        approach that respects approximate token counts.
        """
        if not text:
            return text
        # Rough estimate: 1 token ~ 3.5 chars for mixed Chinese/English text
        max_chars = max(1, int(max_tokens * 3.5))
        if len(text) <= max_chars:
            return text
        # Accumulate until budget is exhausted, break at a natural boundary
        accumulated = 0
        result = []
        for ch in text:
            # Chinese chars and emoji are ~1.5 tokens, ASCII ~0.3 tokens
            if ord(ch) > 127:
                accumulated += 1.5
            else:
                accumulated += 0.3
            if accumulated > max_tokens:
                break
            result.append(ch)
        return "".join(result)

    def search(self, query, kb_id, top_k, include_mental_models: bool = True):
        if not str(query or "").strip():
            return {"ok": False, "error": "query required"}
        kbs = self._store["kbs"]
        if not kbs:
            return {"ok": False, "error": "knowledge base empty"}
        if kb_id:
            kb = next((k for k in kbs if k.get("id") == kb_id), None)
            if kb is None:
                return {"ok": False, "error": "kb not found"}
            pool = kb.get("chunks", [])
        else:
            pool = []
            for k in kbs:
                pool += k.get("chunks", [])
        if not pool:
            return {"ok": False, "error": "kb empty"}
        top_k = max(1, min(20, int(top_k or 4)))
        qv = self._embed([str(query)])[0]

        # -- cosine road (bigram-hash embedding) --
        scored = sorted([(_cosine(qv, c["vector"]), c) for c in pool],
                        key=lambda x: x[0], reverse=True)

        # -- BM25 road (RAG-02: dual-road retrieval + RRF fusion) --
        try:
            from bm25_retrieval import BM25Index, BM25Doc, reciprocal_rank_fusion
            bm25 = BM25Index()
            for c in pool:
                bm25.add(BM25Doc(id=c.get("path", "") + "::" + c.get("text", "")[:40],
                                 text=c.get("text", "")))
            bm25_results = bm25.search(str(query), top_k=max(top_k, len(pool)))
            bm25_ranked = [(doc.id, score) for doc, score in bm25_results]

            # build cosine ranked list
            cosine_ranked = []
            for i, (s, c) in enumerate(scored):
                cid = c.get("path", "") + "::" + c.get("text", "")[:40]
                cosine_ranked.append((cid, s))

            # RRF fusion
            fused = reciprocal_rank_fusion(
                [cosine_ranked, bm25_ranked],
                k=60,
                top_k=top_k,
            )

            # map back to chunk
            id_to_chunk = {}
            for c in pool:
                cid = c.get("path", "") + "::" + c.get("text", "")[:40]
                id_to_chunk[cid] = c

            results = []
            for cid, rrf_score in fused:
                c = id_to_chunk.get(cid)
                if c:
                    results.append({"path": c["path"], "score": round(rrf_score, 4),
                                    "snippet": self._truncate_by_tokens(c["text"])})
            if not results:
                # fallback to cosine-only
                results = [{"path": c["path"], "score": round(s, 4),
                            "snippet": self._truncate_by_tokens(c["text"])} for s, c in scored[:top_k]]
        except Exception:
            # BM25 not available -> fallback to cosine-only
            results = [{"path": c["path"], "score": round(s, 4),
                        "snippet": self._truncate_by_tokens(c["text"])} for s, c in scored[:top_k]]
        # RAG-06/08: MMR diversity pass (Hindsight MMR filter, zero-dep)
        try:
            from rag_layers import mmr_select
            results = mmr_select(results, top_k=top_k, lambda_param=0.7)
        except Exception:
            pass
        return {"ok": True, "results": results}
        # RAG-05: Layered memory -- include mental models as search results
        extra = []
        if include_mental_models:
            try:
                from mental_model import MentalModelEngine
                # Look for a MentalModelEngine instance via config or global
                mm_engine = self.config.get("_mental_model_engine") if isinstance(self.config, dict) else None
                if mm_engine is not None:
                    ctx_text = mm_engine.to_search_context(top_k=max(5, top_k))
                    if ctx_text:
                        extra.append({"path": "[mental-models]", "score": 0.999,
                                      "snippet": self._truncate_by_tokens(ctx_text, max_tokens=200)})
            except Exception:
                pass
        results = extra + results
        return {"ok": True, "results": results}

def register(ctx):
    engine = _RagKb(ctx.config)

    def _kb_search(payload=None, **kw):
        a = payload or {}
        return engine.search(a.get("query", ""), a.get("kbId"), a.get("topK") or 4)

    def _kb_index(payload=None, **kw):
        a = payload or {}
        return engine.index_path(a.get("path", ""), a.get("kbTitle"))

    def _kb_status(payload=None, **kw):
        return {"ok": True, "kbs": engine.list_kbs()}

    from tool_registry import ToolDefinition
    ctx.register_tool(ToolDefinition(
        name="kb_search", source="rag", handler=_kb_search,
        description="Semantic search over knowledge base(s). params: query(str,required), kbId(str,optional), topK(int,default4)."))
    ctx.register_tool(ToolDefinition(
        name="kb_index", source="rag", handler=_kb_index,
        description="Index a local directory/file into a knowledge base. params: path(str,required), kbTitle(str,optional)."))
    ctx.register_tool(ToolDefinition(
        name="kb_status", source="rag", handler=_kb_status,
        description="List knowledge bases with chunk/file counts."))
    return {"tools": ["kb_search", "kb_index", "kb_status"]}

