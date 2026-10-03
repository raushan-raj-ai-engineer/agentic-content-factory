from __future__ import annotations

import html
import os
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote_plus

import httpx

from content_factory.agents.base import Agent
from content_factory.orchestration.state import WorkflowState
from content_factory.modes import is_study_mode


class EvidenceEnrichmentAgent(Agent):
    """Enrich selected trend with fresh public Google News RSS metadata."""

    MAX_ITEMS = 18

    @property
    def name(self) -> str:
        return "Evidence Enrichment Agent"

    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        topic = (
            state.topic
            or (
                state.research.top_candidate.topic
                if state.research is not None
                else ""
            )
        ).strip()

        if is_study_mode(state):
            state.metadata["enriched_evidence"] = []
            state.metadata["evidence_summary"] = {
                "topic": topic,
                "count": 0,
                "sources": [],
                "mode": "study",
            }
            state.status = "evidence_enriched"
            print(
                "[EVIDENCE] Study mode: skipped fresh-news enrichment; "
                "using stable technical/curriculum grounding."
            )
            return state

        if not topic:
            state.metadata["enriched_evidence"] = []
            return state

        geo = os.getenv(
            "CONTENT_FACTORY_GEO",
            "IN",
        ).strip().upper() or "IN"

        items: list[dict[str, Any]] = []
        seen: set[str] = set()

        async with httpx.AsyncClient(
            timeout=18.0,
            follow_redirects=True,
            trust_env=True,
            headers={
                "User-Agent": (
                    "AgenticContentFactory/5.0 "
                    "(public trend research)"
                )
            },
        ) as client:
            for query in self._queries(topic):
                url = (
                    "https://news.google.com/rss/search"
                    f"?q={quote_plus(query)}"
                    f"&hl=en-{geo}"
                    f"&gl={geo}"
                    f"&ceid={geo}:en"
                )

                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    rss_root = ET.fromstring(response.text)
                except Exception as exc:
                    print(
                        f"[EVIDENCE] RSS query failed "
                        f"({query!r}): {exc.__class__.__name__}"
                    )
                    continue

                for node in rss_root.findall(".//item"):
                    title = self._clean(
                        node.findtext("title") or ""
                    )
                    if not title:
                        continue

                    key = self._dedupe_key(title)
                    if key in seen:
                        continue
                    seen.add(key)

                    description = self._clean(
                        node.findtext("description") or ""
                    )
                    source_node = node.find("source")
                    source = (
                        self._clean(source_node.text or "")
                        if source_node is not None
                        else ""
                    )

                    items.append(
                        {
                            "title": title,
                            "description": description[:700],
                            "source": source,
                            "url": (node.findtext("link") or "").strip(),
                            "published_at": (
                                node.findtext("pubDate") or ""
                            ).strip(),
                            "query": query,
                        }
                    )

                    if len(items) >= self.MAX_ITEMS:
                        break

                if len(items) >= self.MAX_ITEMS:
                    break

        state.metadata["enriched_evidence"] = items
        state.metadata["evidence_summary"] = {
            "topic": topic,
            "count": len(items),
            "sources": sorted(
                {
                    str(item.get("source") or "")
                    for item in items
                    if item.get("source")
                }
            )[:12],
        }

        print(
            f"[EVIDENCE] Enriched selected topic with "
            f"{len(items)} fresh Google News item(s)."
        )

        state.status = "evidence_enriched"
        return state

    @staticmethod
    def _queries(topic: str) -> list[str]:
        queries = [
            f'"{topic}"',
            topic,
        ]

        lower = topic.lower()

        if any(
            token in lower
            for token in (
                "movie",
                "film",
                "actor",
                "actress",
            )
        ):
            queries.append(
                f"{topic} review release"
            )
        elif any(
            token in lower
            for token in (
                " vs ",
                " match",
                "football",
                "cricket",
            )
        ):
            queries.append(
                f"{topic} match"
            )
        else:
            queries.append(
                f"{topic} latest"
            )

        result = []
        seen = set()

        for query in queries:
            key = query.lower()
            if key not in seen:
                seen.add(key)
                result.append(query)

        return result[:3]

    @staticmethod
    def _clean(value: str) -> str:
        value = re.sub(
            r"<[^>]+>",
            " ",
            value,
        )
        value = html.unescape(value)
        return re.sub(
            r"\s+",
            " ",
            value,
        ).strip()

    @staticmethod
    def _dedupe_key(value: str) -> str:
        return re.sub(
            r"[^a-z0-9]+",
            "",
            value.lower(),
        )[:180]
