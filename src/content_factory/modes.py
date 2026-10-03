from __future__ import annotations

from typing import Any

STUDY_CATEGORIES = {"technical", "ai", "software_testing"}

_STUDY_TOPIC_TERMS = {
    "ai", "artificial intelligence", "llm", "rag", "retrieval", "embedding",
    "vector database", "agent", "agentic", "mcp", "model context protocol",
    "python", "javascript", "typescript", "java", "programming", "software",
    "api", "database", "sql", "cloud", "aws", "azure", "kubernetes",
    "docker", "github", "git", "linux", "security", "playwright", "selenium",
    "pytest", "testing", "automation", "devops", "machine learning",
    "deep learning", "algorithm", "data structure", "frontend", "backend",
}

def infer_content_mode(*, category: str | None = None, topic: str | None = None) -> str:
    category_value = (category or "").strip().lower()
    if category_value in STUDY_CATEGORIES:
        return "study"

    topic_value = (topic or "").strip().lower()
    if topic_value and any(term in topic_value for term in _STUDY_TOPIC_TERMS):
        return "study"

    return "current"

def is_study_mode(state: Any) -> bool:
    metadata = getattr(state, "metadata", {}) or {}
    if str(metadata.get("content_mode") or "").strip().lower() == "study":
        return True
    requested = str(metadata.get("requested_category") or "").strip().lower()
    return requested in STUDY_CATEGORIES
