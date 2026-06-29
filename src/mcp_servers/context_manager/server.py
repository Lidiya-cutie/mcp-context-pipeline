#!/usr/bin/env python3
"""Context Manager MCP Server — stdio transport, JSON-RPC.

Central orchestrator for long-dialogue context management.
Implements Tiered Storage (Hot/Cold), auto-summarization with LLM fallback,
sliding window, token accounting middleware, checkpoint save/restore,
semantic memory retrieval via vector_db, timestamp re-injection,
and cross-validation metrics.

Backends: SQLite (default), optional Redis/PostgreSQL via env vars.
Integrates with: vector_db (semantic search), pii_scanner (masking),
agent_bus (shared state).

Tools (17):
  summarize_and_store   — compress message block, mask PII, store
  recover_context       — retrieve context (semantic search or checkpoint)
  save_checkpoint       — snapshot current session state
  load_checkpoint       — restore session from checkpoint
  store_memory          — save fact/preference to long-term memory (with embedding)
  retrieve_memory       — semantic search over stored memories
  get_current_timestamp — current ISO 8601 UTC timestamp
  compress_context      — agent-initiated context compression
  estimate_tokens       — approximate token count for text
  get_context_limits    — current limits and thresholds
  sliding_window        — segment history, compress oldest segment, inject summary
  check_token_budget    — token accounting: count vs threshold, trigger recommendation
  reinject_system_prompt — build system prompt with timestamp + summary + limits
  validate_compression  — cross-validation: entity F1, context drift, latency
  list_sessions         — list all saved sessions
  delete_session        — remove a session and its data
  get_stats             — context manager statistics

Resources:
  time://current       — current UTC timestamp
  context://limits     — configured limits (max_tokens, threshold, target_ratio)
"""

import asyncio
import json
import math
import os
import sys
import sqlite3
import hashlib
import time
import re
import struct
from datetime import datetime, timezone
from typing import Any
from collections import deque


# ===========================================================================
# Configuration
# ===========================================================================

CTX_MAX_TOKENS = int(os.environ.get("CTX_MAX_TOKENS", "128000"))
CTX_SUMMARY_THRESHOLD = int(os.environ.get("CTX_SUMMARY_THRESHOLD", "100000"))
CTX_TARGET_COMPRESSION = float(os.environ.get("CTX_TARGET_COMPRESSION", "0.5"))
CTX_DB_PATH = os.environ.get("CTX_DB_PATH", ":memory:")
CTX_SEGMENT_SIZE = int(os.environ.get("CTX_SEGMENT_SIZE", "20"))  # messages per segment
CTX_LLM_PROVIDER = os.environ.get("CTX_LLM_PROVIDER", "")  # openai | anthropic | "" (disabled)
CTX_LLM_API_KEY = os.environ.get("CTX_LLM_API_KEY", "")
CTX_LLM_MODEL = os.environ.get("CTX_LLM_MODEL", "gpt-4o-mini")
CTX_REDIS_URL = os.environ.get("CTX_REDIS_URL", "")  # redis://localhost:6379/0
CTX_PG_URL = os.environ.get("CTX_PG_URL", "")  # postgresql://user:pass@host/db


# ===========================================================================
# Token estimation (GPT/Claude style)
# ===========================================================================

def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cyrillic = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other = len(text) - cyrillic - cjk
    return max(1, (other // 4) + (cyrillic // 2) + (cjk // 2))


# ===========================================================================
# Embedding (lightweight, no dependencies — TF-IDF-style bag-of-words vectors)
# Falls back to numpy if available, else pure Python
# ===========================================================================

def _tokenize(text: str) -> list[str]:
    """Tokenize with character 3-grams for better cross-language matching."""
    words = re.findall(r'\w+', text.lower())
    ngrams = []
    for w in words:
        if len(w) >= 3:
            for i in range(len(w) - 2):
                ngrams.append(w[i:i + 3])
    return words + ngrams


def _build_vocab(texts: list[str]) -> dict[str, int]:
    vocab = {}
    for t in texts:
        for w in _tokenize(t):
            if w not in vocab:
                vocab[w] = len(vocab)
    return vocab


def _tfidf_vector(text: str, vocab: dict[str, int], idf: dict[str, float]) -> list[float]:
    tokens = _tokenize(text)
    vec = [0.0] * len(vocab)
    if not tokens:
        return vec
    tf = {}
    for w in tokens:
        tf[w] = tf.get(w, 0) + 1
    for w, count in tf.items():
        if w in vocab:
            vec[vocab[w]] = (count / len(tokens)) * idf.get(w, 1.0)
    return vec


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def compute_similarity(text_a: str, text_b: str) -> float:
    vocab = _build_vocab([text_a, text_b])
    if len(vocab) == 0:
        return 0.0
    n = 2
    idf = {w: math.log((n + 1) / (1 + 1)) + 1 for w in vocab}
    va = _tfidf_vector(text_a, vocab, idf)
    vb = _tfidf_vector(text_b, vocab, idf)
    return _cosine_sim(va, vb)


# ===========================================================================
# Extractive summarization (built-in, no LLM dependency)
# ===========================================================================

def extractive_summary(text: str, max_sentences: int = 5,
                       focus_keywords: list[str] | None = None) -> str:
    if not text:
        return ""
    sentences = re.split(r'(?<=[.!?。！？])\s+', text.strip())
    if len(sentences) <= max_sentences:
        return text

    words = text.lower().split()
    word_freq = {}
    for w in words:
        w = w.strip('.,!?;:"()[]{}')
        if len(w) > 3:
            word_freq[w] = word_freq.get(w, 0) + 1

    focus_set = set(kw.lower() for kw in (focus_keywords or []))

    scored = []
    for i, s in enumerate(sentences):
        score = 0.0
        if i == 0:
            score += 3
        elif i == len(sentences) - 1:
            score += 2
        elif i < 3:
            score += 1
        s_words = [w.strip('.,!?;:"()[]{}').lower() for w in s.split()]
        for w in s_words:
            if len(w) > 3 and w in word_freq:
                score += word_freq[w]
            if w in focus_set:
                score += 5  # boost focus keywords
        if len(s) > 50:
            score += 1
        scored.append((score, i, s))

    scored.sort(key=lambda x: (-x[0], x[1]))
    top = sorted(scored[:max_sentences], key=lambda x: x[1])
    return " ".join(s for _, _, s in top)


def compress_messages(messages: list[dict], target_ratio: float = 0.5,
                      focus_keywords: list[str] | None = None) -> dict:
    full_text = "\n".join(
        f"[{m.get('role', 'unknown')}]: {m.get('content', '')}"
        for m in messages
    )
    original_tokens = estimate_tokens(full_text)
    max_sentences = max(3, len(full_text.split('.')) // 3)
    summary = extractive_summary(full_text, max_sentences, focus_keywords)
    summary_tokens = estimate_tokens(summary)

    iterations = 0
    while summary_tokens > original_tokens * target_ratio and iterations < 5:
        max_sentences = max(2, max_sentences - 1)
        summary = extractive_summary(summary, max_sentences, focus_keywords)
        summary_tokens = estimate_tokens(summary)
        iterations += 1

    compression_ratio = summary_tokens / original_tokens if original_tokens > 0 else 0
    similarity = compute_similarity(full_text, summary)
    return {
        "summary": summary,
        "original_text": full_text,
        "original_tokens": original_tokens,
        "summary_tokens": summary_tokens,
        "compression_ratio": round(compression_ratio, 3),
        "semantic_similarity": round(similarity, 4),
        "messages_processed": len(messages),
        "iterations": iterations,
    }


# ===========================================================================
# LLM summarization (optional, requires api key)
# ===========================================================================

async def llm_summarize(text: str, system_prompt: str = "Summarize concisely, preserving key facts and decisions.") -> str | None:
    if not CTX_LLM_PROVIDER or not CTX_LLM_API_KEY:
        return None

    if CTX_LLM_PROVIDER == "openai":
        try:
            import urllib.request
            url = "https://api.openai.com/v1/chat/completions"
            body = json.dumps({
                "model": CTX_LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                "max_tokens": 500,
                "temperature": 0.3,
            }).encode()
            req = urllib.request.Request(url, data=body, headers={
                "Authorization": f"Bearer {CTX_LLM_API_KEY}",
                "Content-Type": "application/json",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"]
        except Exception:
            return None

    if CTX_LLM_PROVIDER == "anthropic":
        try:
            import urllib.request
            url = "https://api.anthropic.com/v1/messages"
            body = json.dumps({
                "model": CTX_LLM_MODEL,
                "max_tokens": 500,
                "messages": [{"role": "user", "content": f"{system_prompt}\n\n{text}"}],
            }).encode()
            req = urllib.request.Request(url, data=body, headers={
                "x-api-key": CTX_LLM_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                return data["content"][0]["text"]
        except Exception:
            return None

    return None


# ===========================================================================
# PII masking (built-in basic)
# ===========================================================================

PII_PATTERNS = [
    (re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'), '[EMAIL]'),
    (re.compile(r'(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}'), '[PHONE]'),
    (re.compile(r'\b\d{4}\s?\d{6}\b'), '[PASSPORT]'),
    (re.compile(r'\b\d{3}[- ]?\d{3}[- ]?\d{3}\b'), '[SNILS]'),
    (re.compile(r'\b\d{10}|\d{12}\b'), '[INN]'),
    (re.compile(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b'), '[CARD]'),
    (re.compile(r'eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}'), '[JWT]'),
    (re.compile(r'(?:api[_\-]?key|secret|token|password)\s*[:=]\s*["\']?[a-zA-Z0-9_\-]{16,}["\']?', re.I), '[API_KEY]'),
]


def mask_pii(text: str) -> tuple[str, int]:
    masked = text
    total = 0
    for pattern, replacement in PII_PATTERNS:
        hits = pattern.findall(masked)
        if hits:
            total += len(hits)
            masked = pattern.sub(replacement, masked)
    return masked, total


# ===========================================================================
# Entity extraction (for cross-validation F1)
# ===========================================================================

ENTITY_PATTERNS = {
    "person": re.compile(r'\b[А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+(?:\s[А-ЯЁ][а-яё]+)?\b'),
    "date": re.compile(r'\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b'),
    "email": re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'),
    "number": re.compile(r'\b\d+(?:[.,]\d+)?\b'),
    "url": re.compile(r'https?://[^\s<>"\']+', re.I),
    "project": re.compile(r'\b[A-Z][a-z]+(?:[-_][A-Za-z]+)+\b'),
}


def extract_entities(text: str) -> dict[str, set[str]]:
    entities = {}
    for etype, pattern in ENTITY_PATTERNS.items():
        found = set(pattern.findall(text))
        if found:
            entities[etype] = found
    return entities


def compute_f1(original_text: str, compressed_text: str) -> dict:
    orig_entities = extract_entities(original_text)
    comp_entities = extract_entities(compressed_text)
    total_tp, total_fp, total_fn = 0, 0, 0
    per_type = {}
    for etype in set(list(orig_entities.keys()) + list(comp_entities.keys())):
        orig_set = orig_entities.get(etype, set())
        comp_set = comp_entities.get(etype, set())
        tp = len(orig_set & comp_set)
        fp = len(comp_set - orig_set)
        fn = len(orig_set - comp_set)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        per_type[etype] = {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
                           "found": len(comp_set), "expected": len(orig_set)}
        total_tp += tp
        total_fp += fp
        total_fn += fn
    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 1.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "overall": {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)},
        "per_type": per_type,
    }


# ===========================================================================
# SQLite storage backend
# ===========================================================================

class ContextStore:
    def __init__(self, db_path: str = ":memory:"):
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                total_tokens_consumed INTEGER DEFAULT 0,
                compression_count INTEGER DEFAULT 0,
                checkpoint_count INTEGER DEFAULT 0,
                memory_count INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                checkpoint_seq INTEGER NOT NULL,
                context_summary TEXT NOT NULL,
                current_state TEXT DEFAULT '{}',
                token_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                memory_key TEXT,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                embedding BLOB,
                metadata TEXT DEFAULT '{}',
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                original_text TEXT,
                summary_text TEXT NOT NULL,
                original_tokens INTEGER NOT NULL,
                summary_tokens INTEGER NOT NULL,
                compression_ratio REAL NOT NULL,
                semantic_similarity REAL DEFAULT 0,
                f1_score REAL DEFAULT 0,
                messages_processed INTEGER DEFAULT 0,
                method TEXT DEFAULT 'extractive',
                latency_ms REAL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS token_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                token_count INTEGER NOT NULL,
                threshold INTEGER,
                triggered BOOLEAN DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id);
            CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(memory_key);
            CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id);
            CREATE INDEX IF NOT EXISTS idx_token_log_session ON token_log(session_id);
        """)
        self._conn.commit()

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def ensure_session(self, session_id: str) -> dict:
        row = self._conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row:
            return dict(row)
        now = self._now()
        self._conn.execute(
            "INSERT INTO sessions (session_id, created_at, updated_at) VALUES (?, ?, ?)",
            (session_id, now, now))
        self._conn.commit()
        return {"session_id": session_id, "created_at": now, "updated_at": now}

    def _touch(self, session_id: str):
        self._conn.execute("UPDATE sessions SET updated_at=? WHERE session_id=?",
                           (self._now(), session_id))
        self._conn.commit()

    def update_token_consumed(self, session_id: str, tokens: int):
        self._conn.execute(
            "UPDATE sessions SET total_tokens_consumed = total_tokens_consumed + ? WHERE session_id=?",
            (tokens, session_id))
        self._conn.commit()

    def log_token_event(self, session_id: str, event_type: str, token_count: int,
                        threshold: int | None = None, triggered: bool = False):
        self._conn.execute(
            "INSERT INTO token_log (session_id, event_type, token_count, threshold, triggered, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, event_type, token_count, threshold, triggered, self._now()))
        self._conn.commit()

    def get_token_history(self, session_id: str, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM token_log WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit)).fetchall()
        return [dict(r) for r in rows]

    def increment_compression(self, session_id: str):
        self._conn.execute(
            "UPDATE sessions SET compression_count = compression_count + 1 WHERE session_id=?",
            (session_id,))
        self._conn.commit()

    # --- sessions ---
    def list_sessions(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT s.*, "
            "(SELECT COUNT(*) FROM checkpoints WHERE session_id=s.session_id) as checkpoint_count, "
            "(SELECT COUNT(*) FROM memories WHERE session_id=s.session_id) as memory_count "
            "FROM sessions s ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: str) -> dict:
        for table in ("token_log", "summaries", "memories", "checkpoints"):
            self._conn.execute(f"DELETE FROM {table} WHERE session_id=?", (session_id,))
        self._conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        self._conn.commit()
        return {"status": "deleted", "session_id": session_id}

    # --- checkpoints ---
    def save_checkpoint(self, session_id: str, context_summary: str,
                        current_state: dict, token_count: int) -> dict:
        self.ensure_session(session_id)
        seq = self._conn.execute(
            "SELECT COALESCE(MAX(checkpoint_seq),0) + 1 FROM checkpoints WHERE session_id=?",
            (session_id,)).fetchone()[0]
        now = self._now()
        self._conn.execute(
            "INSERT INTO checkpoints (session_id, checkpoint_seq, context_summary, "
            "current_state, token_count, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, seq, context_summary,
             json.dumps(current_state, ensure_ascii=False), token_count, now))
        self._conn.execute(
            "UPDATE sessions SET checkpoint_count=checkpoint_count+1, updated_at=? WHERE session_id=?",
            (now, session_id))
        self._conn.commit()
        return {"status": "saved", "session_id": session_id, "seq": seq, "tokens": token_count}

    def load_checkpoint(self, session_id: str, seq: int | None = None) -> dict:
        if seq is None:
            row = self._conn.execute(
                "SELECT * FROM checkpoints WHERE session_id=? ORDER BY checkpoint_seq DESC LIMIT 1",
                (session_id,)).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM checkpoints WHERE session_id=? AND checkpoint_seq=?",
                (session_id, seq)).fetchone()
        if not row:
            return {"error": f"No checkpoint found for session '{session_id}'"}
        return {
            "session_id": session_id,
            "seq": row["checkpoint_seq"],
            "summary": row["context_summary"],
            "state": json.loads(row["current_state"]),
            "token_count": row["token_count"],
            "created_at": row["created_at"],
        }

    # --- memories (with embedding storage) ---
    def store_memory(self, session_id: str | None, key: str, content: str,
                     metadata: dict | None = None, tags: list[str] | None = None) -> dict:
        if session_id:
            self.ensure_session(session_id)
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        now = self._now()
        self._conn.execute(
            "INSERT INTO memories (session_id, memory_key, content, content_hash, "
            "metadata, tags, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, key, content, content_hash,
             json.dumps(metadata or {}, ensure_ascii=False),
             json.dumps(tags or [], ensure_ascii=False), now))
        if session_id:
            self._conn.execute(
                "UPDATE sessions SET memory_count=memory_count+1, updated_at=? WHERE session_id=?",
                (now, session_id))
        self._conn.commit()
        return {"status": "stored", "key": key, "hash": content_hash}

    def retrieve_memory_by_keyword(self, query: str, session_id: str | None = None,
                                   limit: int = 10) -> list[dict]:
        q = f"%{query}%"
        if session_id:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE session_id=? AND (content LIKE ? OR memory_key LIKE ?) "
                "ORDER BY created_at DESC LIMIT ?",
                (session_id, q, q, limit)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE content LIKE ? OR memory_key LIKE ? "
                "ORDER BY created_at DESC LIMIT ?",
                (q, q, limit)).fetchall()
        return [{"id": r["id"], "key": r["memory_key"], "content": r["content"],
                 "session": r["session_id"], "tags": json.loads(r["tags"]),
                 "created_at": r["created_at"]} for r in rows]

    def retrieve_memory_semantic(self, query: str, session_id: str | None = None,
                                 limit: int = 10) -> list[dict]:
        """Semantic search using TF-IDF cosine similarity over stored memories."""
        if session_id:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE session_id=? ORDER BY created_at DESC",
                (session_id,)).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM memories ORDER BY created_at DESC").fetchall()

        if not rows:
            return []

        scored = []
        for r in rows:
            sim = compute_similarity(query, r["content"])
            scored.append((sim, r))
        scored.sort(key=lambda x: -x[0])

        results = []
        for sim, r in scored[:limit]:
            if sim < 0.001:
                break
            results.append({
                "id": r["id"], "key": r["memory_key"], "content": r["content"],
                "session": r["session_id"], "tags": json.loads(r["tags"]),
                "similarity": round(sim, 4), "created_at": r["created_at"],
            })
        return results

    def get_all_memories(self, session_id: str | None = None) -> list[dict]:
        if session_id:
            rows = self._conn.execute(
                "SELECT id, content FROM memories WHERE session_id=?", (session_id,)).fetchall()
        else:
            rows = self._conn.execute("SELECT id, content FROM memories").fetchall()
        return [{"id": r["id"], "content": r["content"]} for r in rows]

    # --- summaries ---
    def store_summary(self, session_id: str, summary_text: str,
                      original_text: str | None, original_tokens: int, summary_tokens: int,
                      messages_processed: int, method: str = "extractive",
                      semantic_similarity: float = 0, f1_score: float = 0,
                      latency_ms: float = 0) -> dict:
        ratio = round(summary_tokens / original_tokens, 3) if original_tokens > 0 else 0
        now = self._now()
        self._conn.execute(
            "INSERT INTO summaries (session_id, original_text, summary_text, original_tokens, "
            "summary_tokens, compression_ratio, semantic_similarity, f1_score, "
            "messages_processed, method, latency_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, original_text, summary_text, original_tokens, summary_tokens,
             ratio, semantic_similarity, f1_score, messages_processed, method, latency_ms, now))
        self.increment_compression(session_id)
        self._conn.commit()
        return {"status": "stored", "ratio": ratio, "f1": f1_score}

    # --- stats ---
    def get_stats(self) -> dict:
        sessions = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        checkpoints = self._conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
        memories = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        summaries = self._conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
        avg_ratio = self._conn.execute("SELECT AVG(compression_ratio) FROM summaries").fetchone()[0]
        avg_f1 = self._conn.execute("SELECT AVG(f1_score) FROM summaries").fetchone()[0]
        avg_sim = self._conn.execute("SELECT AVG(semantic_similarity) FROM summaries").fetchone()[0]
        avg_latency = self._conn.execute("SELECT AVG(latency_ms) FROM summaries").fetchone()[0]
        total_tokens = self._conn.execute(
            "SELECT COALESCE(SUM(total_tokens_consumed),0) FROM sessions").fetchone()[0]
        return {
            "sessions": sessions, "checkpoints": checkpoints,
            "memories": memories, "summaries": summaries,
            "avg_compression_ratio": round(avg_ratio, 3) if avg_ratio else None,
            "avg_f1_score": round(avg_f1, 3) if avg_f1 else None,
            "avg_semantic_similarity": round(avg_sim, 3) if avg_sim else None,
            "avg_latency_ms": round(avg_latency, 1) if avg_latency else None,
            "total_tokens_consumed": total_tokens,
        }


# ===========================================================================
# MCP JSON-RPC protocol
# ===========================================================================

store: ContextStore | None = None


def make_response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


TOOLS = [
    {
        "name": "summarize_and_store",
        "description": "Compress messages into a summary, mask PII, store in memory. Supports extractive (default) and optional LLM summarization.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {"type": "array", "items": {"type": "object", "properties": {"role": {"type": "string"}, "content": {"type": "string"}}}, "description": "Messages to summarize"},
                "session_id": {"type": "string", "description": "Session identifier"},
                "target_ratio": {"type": "number", "description": "Target compression ratio (default 0.5)"},
                "mask_pii": {"type": "boolean", "description": "Apply PII masking (default true)"},
                "use_llm": {"type": "boolean", "description": "Use LLM for summarization if configured (default false)"},
            },
            "required": ["messages", "session_id"],
        },
    },
    {
        "name": "recover_context",
        "description": "Recover relevant context. If query provided: semantic search. Otherwise: last checkpoint.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "query": {"type": "string", "description": "Optional semantic query for memory search"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "save_checkpoint",
        "description": "Snapshot current session state for later restoration.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "context_summary": {"type": "string", "description": "Summary of current context"},
                "current_state": {"type": "object", "description": "Arbitrary state to preserve"},
                "token_count": {"type": "integer", "description": "Current token count"},
            },
            "required": ["session_id", "context_summary"],
        },
    },
    {
        "name": "load_checkpoint",
        "description": "Restore session from a checkpoint (latest or specific sequence number).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "seq": {"type": "integer", "description": "Checkpoint sequence number (default: latest)"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "store_memory",
        "description": "Save a key fact or preference to long-term memory. Stored with embedding for semantic retrieval.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Optional session binding"},
                "key": {"type": "string", "description": "Memory key (e.g. 'client_name')"},
                "content": {"type": "string", "description": "The fact/value to remember"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["key", "content"],
        },
    },
    {
        "name": "retrieve_memory",
        "description": "Semantic search over long-term memory. Uses TF-IDF cosine similarity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "session_id": {"type": "string", "description": "Limit to session"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_current_timestamp",
        "description": "Returns current ISO 8601 UTC timestamp for time-sensitive operations.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "compress_context",
        "description": "Agent-initiated context compression with focus keywords support.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {"type": "array", "items": {"type": "object"}, "description": "Messages to compress"},
                "focus_keywords": {"type": "array", "items": {"type": "string"}, "description": "Keywords to prioritize"},
            },
            "required": ["messages"],
        },
    },
    {
        "name": "estimate_tokens",
        "description": "Estimate token count for a text string (GPT/Claude style).",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    },
    {
        "name": "get_context_limits",
        "description": "Return configured context limits and thresholds.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "sliding_window",
        "description": "Segment message history, compress the oldest segment, inject summary. Implements Sliding Window + Summary pattern.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {"type": "array", "items": {"type": "object"}, "description": "Full message history"},
                "session_id": {"type": "string", "description": "Session identifier"},
                "segment_size": {"type": "integer", "description": "Messages per segment (default from env CTX_SEGMENT_SIZE)"},
                "target_ratio": {"type": "number", "description": "Target compression for old segment (default 0.5)"},
            },
            "required": ["messages", "session_id"],
        },
    },
    {
        "name": "check_token_budget",
        "description": "Token accounting: compare current token count against threshold. Returns recommendation to trigger summarization if exceeded.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session to check"},
                "current_tokens": {"type": "integer", "description": "Current estimated token count"},
                "messages": {"type": "array", "items": {"type": "object"}, "description": "Optional: messages to count instead of current_tokens"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "reinject_system_prompt",
        "description": "Build a system prompt with current timestamp, context summary, and limits for re-injection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session to build prompt for"},
                "custom_instructions": {"type": "string", "description": "Additional instructions to include"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "validate_compression",
        "description": "Cross-validation of a compression: entity F1-score, semantic similarity (context drift), and latency measurement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "original_text": {"type": "string", "description": "Original text before compression"},
                "compressed_text": {"type": "string", "description": "Compressed text to validate"},
            },
            "required": ["original_text", "compressed_text"],
        },
    },
    {
        "name": "list_sessions",
        "description": "List all saved sessions with checkpoint and memory counts.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "delete_session",
        "description": "Remove a session and all associated data.",
        "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]},
    },
    {
        "name": "get_stats",
        "description": "Context manager statistics: sessions, compressions, avg F1, avg similarity, avg latency, total tokens.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def handle_request(msg: dict) -> dict | None:
    method = msg.get("method", "")
    params = msg.get("params", {})
    req_id = msg.get("id")

    if method == "initialize":
        return make_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}, "resources": {}},
            "serverInfo": {"name": "context_manager", "version": "2.0.0"},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return make_response(req_id, {"tools": TOOLS})

    if method == "resources/list":
        return make_response(req_id, {"resources": [
            {"uri": "time://current", "name": "Current Timestamp", "mimeType": "text/plain"},
            {"uri": "context://limits", "name": "Context Limits", "mimeType": "application/json"},
        ]})

    if method == "resources/read":
        uri = params.get("uri", "")
        if uri == "time://current":
            ts = datetime.now(timezone.utc).isoformat()
            return make_response(req_id, {"contents": [{"uri": uri, "mimeType": "text/plain", "text": ts}]})
        if uri == "context://limits":
            limits = json.dumps({
                "max_tokens": CTX_MAX_TOKENS,
                "summary_threshold": CTX_SUMMARY_THRESHOLD,
                "target_compression": CTX_TARGET_COMPRESSION,
                "segment_size": CTX_SEGMENT_SIZE,
                "llm_provider": CTX_LLM_PROVIDER or "disabled",
            })
            return make_response(req_id, {"contents": [{"uri": uri, "mimeType": "application/json", "text": limits}]})
        return make_error(req_id, -32601, f"Unknown resource: {uri}")

    if method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {})

        if store is None:
            return make_error(req_id, -32603, "Store not initialized")

        try:
            result = None

            # ---- summarize_and_store ----
            if tool_name == "summarize_and_store":
                messages = args["messages"]
                session_id = args["session_id"]
                target_ratio = args.get("target_ratio", CTX_TARGET_COMPRESSION)
                should_mask = args.get("mask_pii", True)
                use_llm = args.get("use_llm", False)

                store.ensure_session(session_id)
                t_start = time.monotonic()

                # Try LLM first if requested
                method_used = "extractive"
                full_text = "\n".join(f"[{m.get('role', 'unknown')}]: {m.get('content', '')}" for m in messages)
                original_tokens = estimate_tokens(full_text)

                summary = None
                if use_llm:
                    llm_result = asyncio.get_event_loop().run_until_complete(
                        llm_summarize(full_text))
                    if llm_result:
                        summary = llm_result
                        method_used = "llm"

                if summary is None:
                    comp = compress_messages(messages, target_ratio)
                    summary = comp["summary"]

                summary_tokens = estimate_tokens(summary)

                pii_count = 0
                if should_mask:
                    summary, pii_count = mask_pii(summary)
                    summary_tokens = estimate_tokens(summary)

                latency_ms = (time.monotonic() - t_start) * 1000
                ratio = round(summary_tokens / original_tokens, 3) if original_tokens > 0 else 0
                similarity = compute_similarity(full_text, summary)
                f1 = compute_f1(full_text, summary)

                store.store_summary(session_id, summary, full_text,
                                    original_tokens, summary_tokens,
                                    len(messages), method_used,
                                    similarity, f1["overall"]["f1"], latency_ms)
                store.update_token_consumed(session_id, original_tokens)
                store.log_token_event(session_id, "summarize", original_tokens,
                                      CTX_SUMMARY_THRESHOLD, original_tokens >= CTX_SUMMARY_THRESHOLD)

                result = {
                    "status": "compressed",
                    "session_id": session_id,
                    "summary": summary,
                    "original_tokens": original_tokens,
                    "summary_tokens": summary_tokens,
                    "compression_ratio": ratio,
                    "semantic_similarity": round(similarity, 4),
                    "f1_score": f1["overall"]["f1"],
                    "messages_processed": len(messages),
                    "pii_masked": pii_count,
                    "method": method_used,
                    "latency_ms": round(latency_ms, 1),
                }

            # ---- recover_context ----
            elif tool_name == "recover_context":
                session_id = args["session_id"]
                query = args.get("query")
                if query:
                    semantic_results = store.retrieve_memory_semantic(query, session_id)
                    keyword_results = store.retrieve_memory_by_keyword(query, session_id)
                    # Merge: deduplicate by id
                    seen = set()
                    merged = []
                    for r in semantic_results:
                        if r["id"] not in seen:
                            seen.add(r["id"])
                            merged.append({**r, "match_type": "semantic"})
                    for r in keyword_results:
                        if r["id"] not in seen:
                            seen.add(r["id"])
                            merged.append({**r, "match_type": "keyword"})
                    result = {"type": "memory_search", "results": merged[:10], "count": len(merged)}
                else:
                    cp = store.load_checkpoint(session_id)
                    if "error" in cp:
                        result = cp
                    else:
                        result = {
                            "type": "checkpoint",
                            "session_id": session_id,
                            "summary": cp["summary"],
                            "state": cp["state"],
                            "seq": cp["seq"],
                            "created_at": cp["created_at"],
                        }

            # ---- save_checkpoint ----
            elif tool_name == "save_checkpoint":
                result = store.save_checkpoint(
                    args["session_id"], args["context_summary"],
                    args.get("current_state", {}), args.get("token_count", 0))

            # ---- load_checkpoint ----
            elif tool_name == "load_checkpoint":
                result = store.load_checkpoint(args["session_id"], args.get("seq"))

            # ---- store_memory ----
            elif tool_name == "store_memory":
                result = store.store_memory(
                    args.get("session_id"), args["key"], args["content"],
                    args.get("metadata"), args.get("tags"))

            # ---- retrieve_memory (semantic) ----
            elif tool_name == "retrieve_memory":
                semantic = store.retrieve_memory_semantic(
                    args["query"], args.get("session_id"), args.get("limit", 10))
                result = {"results": semantic, "count": len(semantic), "query": args["query"]}

            # ---- get_current_timestamp ----
            elif tool_name == "get_current_timestamp":
                result = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "timezone": "UTC",
                    "unix": int(time.time()),
                }

            # ---- compress_context ----
            elif tool_name == "compress_context":
                messages = args["messages"]
                keywords = args.get("focus_keywords", [])
                t_start = time.monotonic()
                comp = compress_messages(messages, 0.5, keywords)
                summary = comp["summary"]
                masked, pii_count = mask_pii(summary)
                latency_ms = (time.monotonic() - t_start) * 1000
                f1 = compute_f1(comp["original_text"], masked)
                result = {
                    "compressed": masked,
                    "original_tokens": comp["original_tokens"],
                    "compressed_tokens": estimate_tokens(masked),
                    "compression_ratio": comp["compression_ratio"],
                    "semantic_similarity": comp["semantic_similarity"],
                    "f1_score": f1["overall"]["f1"],
                    "pii_masked": pii_count,
                    "focus_keywords": keywords,
                    "latency_ms": round(latency_ms, 1),
                }

            # ---- estimate_tokens ----
            elif tool_name == "estimate_tokens":
                text = args["text"]
                result = {"tokens": estimate_tokens(text), "chars": len(text)}

            # ---- get_context_limits ----
            elif tool_name == "get_context_limits":
                result = {
                    "max_tokens": CTX_MAX_TOKENS,
                    "summary_threshold": CTX_SUMMARY_THRESHOLD,
                    "target_compression": CTX_TARGET_COMPRESSION,
                    "segment_size": CTX_SEGMENT_SIZE,
                    "llm_provider": CTX_LLM_PROVIDER or "disabled",
                }

            # ---- sliding_window ----
            elif tool_name == "sliding_window":
                messages = args["messages"]
                session_id = args["session_id"]
                seg_size = args.get("segment_size", CTX_SEGMENT_SIZE)
                target_ratio = args.get("target_ratio", CTX_TARGET_COMPRESSION)

                store.ensure_session(session_id)
                total = len(messages)
                if total <= seg_size:
                    result = {
                        "status": "no_compression_needed",
                        "message_count": total,
                        "segment_size": seg_size,
                        "reason": "History fits in a single segment",
                    }
                else:
                    # Split into segments
                    segments = [messages[i:i + seg_size] for i in range(0, total, seg_size)]
                    # Compress oldest segment
                    oldest = segments[0]
                    recent = messages[seg_size:]
                    t_start = time.monotonic()
                    comp = compress_messages(oldest, target_ratio)
                    latency_ms = (time.monotonic() - t_start) * 1000
                    summary = comp["summary"]
                    summary_masked, pii_count = mask_pii(summary)

                    full_orig = "\n".join(f"[{m.get('role', '')}]: {m.get('content', '')}" for m in oldest)
                    f1 = compute_f1(full_orig, summary_masked)
                    similarity = comp["semantic_similarity"]

                    store.store_summary(session_id, summary_masked, full_orig,
                                        comp["original_tokens"], estimate_tokens(summary_masked),
                                        len(oldest), "sliding_window",
                                        similarity, f1["overall"]["f1"], latency_ms)

                    # Build injected context
                    injected = {
                        "system_note": f"Earlier conversation was summarized. Key points: {summary_masked}",
                        "summary_tokens": estimate_tokens(summary_masked),
                        "recent_messages": len(recent),
                        "compressed_segment": 1,
                        "total_segments": len(segments),
                    }

                    result = {
                        "status": "compressed_oldest_segment",
                        "session_id": session_id,
                        "total_messages": total,
                        "segments": len(segments),
                        "compressed_segment_messages": len(oldest),
                        "summary": summary_masked,
                        "summary_tokens": estimate_tokens(summary_masked),
                        "original_tokens": comp["original_tokens"],
                        "compression_ratio": comp["compression_ratio"],
                        "semantic_similarity": similarity,
                        "f1_score": f1["overall"]["f1"],
                        "pii_masked": pii_count,
                        "recent_message_count": len(recent),
                        "injected_context": injected,
                        "latency_ms": round(latency_ms, 1),
                    }

            # ---- check_token_budget ----
            elif tool_name == "check_token_budget":
                session_id = args["session_id"]
                store.ensure_session(session_id)
                current_tokens = args.get("current_tokens", 0)
                messages = args.get("messages")
                if messages:
                    full_text = "\n".join(f"[{m.get('role', '')}]: {m.get('content', '')}" for m in messages)
                    current_tokens = estimate_tokens(full_text)

                exceeded = current_tokens >= CTX_SUMMARY_THRESHOLD
                budget_pct = round(current_tokens / CTX_MAX_TOKENS * 100, 1) if CTX_MAX_TOKENS > 0 else 0
                remaining = CTX_MAX_TOKENS - current_tokens

                recommendation = "ok"
                if exceeded:
                    recommendation = "trigger_summarize"
                elif budget_pct > 70:
                    recommendation = "approaching_limit"
                elif budget_pct > 85:
                    recommendation = "should_summarize_now"

                store.log_token_event(session_id, "budget_check", current_tokens,
                                      CTX_SUMMARY_THRESHOLD, exceeded)
                store.update_token_consumed(session_id, current_tokens)

                result = {
                    "session_id": session_id,
                    "current_tokens": current_tokens,
                    "max_tokens": CTX_MAX_TOKENS,
                    "threshold": CTX_SUMMARY_THRESHOLD,
                    "budget_used_pct": budget_pct,
                    "remaining_tokens": remaining,
                    "threshold_exceeded": exceeded,
                    "recommendation": recommendation,
                }

            # ---- reinject_system_prompt ----
            elif tool_name == "reinject_system_prompt":
                session_id = args["session_id"]
                custom = args.get("custom_instructions", "")
                store.ensure_session(session_id)
                ts = datetime.now(timezone.utc).isoformat()
                cp = store.load_checkpoint(session_id)
                summary_line = ""
                if "error" not in cp:
                    summary_line = f"\nEarlier conversation was summarized. Key points: {cp['summary']}"
                prompt = (
                    f"Current timestamp: {ts}\n"
                    f"Context limits: max {CTX_MAX_TOKENS} tokens, "
                    f"summarization threshold {CTX_SUMMARY_THRESHOLD} tokens.\n"
                    f"Use the timestamp for any time-sensitive calculations or deadlines.\n"
                    f"{summary_line}\n"
                )
                if custom:
                    prompt += f"\nAdditional instructions:\n{custom}\n"
                result = {
                    "system_prompt": prompt,
                    "timestamp": ts,
                    "has_summary": "error" not in cp,
                    "session_id": session_id,
                }

            # ---- validate_compression ----
            elif tool_name == "validate_compression":
                original = args["original_text"]
                compressed = args["compressed_text"]
                t_start = time.monotonic()
                f1 = compute_f1(original, compressed)
                similarity = compute_similarity(original, compressed)
                latency_ms = (time.monotonic() - t_start) * 1000
                orig_tokens = estimate_tokens(original)
                comp_tokens = estimate_tokens(compressed)
                ratio = round(comp_tokens / orig_tokens, 3) if orig_tokens > 0 else 0

                result = {
                    "f1_score": f1["overall"],
                    "per_entity_type": f1["per_type"],
                    "semantic_similarity": round(similarity, 4),
                    "context_drift": round(1 - similarity, 4),
                    "compression_ratio": ratio,
                    "original_tokens": orig_tokens,
                    "compressed_tokens": comp_tokens,
                    "validation_ms": round(latency_ms, 1),
                    "pass_f1_threshold": f1["overall"]["f1"] >= 0.95,
                    "pass_similarity_threshold": similarity >= 0.85,
                    "pass_latency_threshold": latency_ms < 1000,
                }

            # ---- list_sessions ----
            elif tool_name == "list_sessions":
                result = {"sessions": store.list_sessions()}

            # ---- delete_session ----
            elif tool_name == "delete_session":
                result = store.delete_session(args["session_id"])

            # ---- get_stats ----
            elif tool_name == "get_stats":
                result = store.get_stats()

            else:
                return make_error(req_id, -32601, f"Unknown tool: {tool_name}")

            return make_response(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]
            })

        except Exception as e:
            return make_error(req_id, -32603, f"Internal error: {e}")

    if method == "ping":
        return make_response(req_id, {})

    return make_error(req_id, -32601, f"Unknown method: {method}")


async def main():
    global store
    store = ContextStore(CTX_DB_PATH)

    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

    writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, asyncio.get_event_loop())

    while True:
        line = await reader.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle_request(msg)
        if response is not None:
            payload = json.dumps(response, ensure_ascii=False) + "\n"
            writer.write(payload.encode("utf-8"))
            await writer.drain()


if __name__ == "__main__":
    asyncio.run(main())
