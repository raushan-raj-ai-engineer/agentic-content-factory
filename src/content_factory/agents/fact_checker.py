from __future__ import annotations

import json
import re

from content_factory.agents.base import Agent
from content_factory.llm.base import LLMProvider
from content_factory.models.content import FactCheckResult, YouTubeScript
from content_factory.orchestration.state import WorkflowState
from content_factory.research.trend_signals import get_signal


MONTH_PATTERN = (
    r"(?:january|february|march|april|may|june|july|august|"
    r"september|october|november|december)"
)


class FactCheckerAgent(Agent):
    """
    Strict evidence-bounded checker.

    If the first script contains unsupported current-event claims, it gets
    one local auto-repair pass. If material issues remain, the workflow is
    hard-stopped so auto approval cannot publish unsupported claims.
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @property
    def name(self) -> str:
        return "Fact Checker Agent"

    async def execute(self, state: WorkflowState) -> WorkflowState:
        if state.script is None:
            raise ValueError("Script is required before fact checking.")

        first = await self._check(state)

        if first.approved and not first.issues:
            state.fact_check = first
            state.status = "fact_checked"
            print(f"[FACT] Passed with score={first.score}")
            return state

        # V20.2: zero factual issues must never trigger an LLM rewrite.
        if len(first.issues) == 0:
            _cf_fact = getattr(state, 'fact_check', None)
            if _cf_fact is None:
                _cf_fact = (
                    locals().get('first')
                    or locals().get('result')
                    or locals().get('fact_result')
                    or locals().get('fact_check_result')
                )
                if _cf_fact is None:
                    raise RuntimeError('Fact checker zero-issue result was not recoverable')
            state.fact_check = _cf_fact
            try:
                _cf_fact.approved = True
                _cf_fact.score = max(int(getattr(_cf_fact, 'score', 0) or 0), 95)
                _cf_fact.issues = []
            except Exception:
                try:
                    state.fact_check = _cf_fact.model_copy(update={'approved': True, 'score': 100, 'issues': []})
                except Exception as _cf_exc:
                    raise RuntimeError('Could not normalize zero-issue FactCheckResult') from _cf_exc
            state.status = 'fact_checked'
            print('[FACT] PASS: 0 material issue(s); repair=SKIPPED')
            return state
        print(
            f"[FACT] Found {len(first.issues)} issue(s). "
            "Auto-repairing script once."
        )

        repaired = await self._repair_script(
            state,
            first.issues,
        )
        state.script = repaired

        second = await self._check(state)

        if second.issues:
            second.approved = False
            second.score = min(int(second.score), 70)

        state.fact_check = second

        if not second.approved or second.issues:
            state.status = "fact_check_blocked"
            # Important for AUTO mode: do not let a later automatic approval
            # override a failed factual gate.
            state.stop_requested = True
            print(
                f"[FACT] BLOCKED after repair: "
                f"{len(second.issues)} issue(s) remain."
            )
        else:
            state.status = "fact_checked"
            print(f"[FACT] Auto-repair passed; score={second.score}")

        return state

    async def _check(
        self,
        state: WorkflowState,
    ) -> FactCheckResult:
        deterministic_issues = self._deterministic_checks(state)

        prompt = f"""
Fact-check this YouTube script strictly against the supplied evidence.

TOPIC
{state.topic or "unknown"}

SCRIPT
{json.dumps(state.script.model_dump(), ensure_ascii=False, indent=2)}

TOPIC-SPECIFIC AUTHORITATIVE FACTS
{self._authoritative_facts(state.topic or "")}

CURRENT TREND / NEWS EVIDENCE
{self._trend_evidence(state)}

FRESH ENRICHED NEWS EVIDENCE
{self._enriched_evidence(state)}

TOPIC GROUNDING
{json.dumps(state.metadata.get("topic_grounding", {}), ensure_ascii=False, indent=2)}

SCRIPT REVIEW CONCERNS — ADVISORY, VERIFY THEM AGAINST EVIDENCE
{self._review_concerns(state)}

YOUTUBE DISCOVERY EVIDENCE
{self._youtube_evidence(state)}

DETERMINISTIC ISSUES ALREADY FOUND
{json.dumps(deterministic_issues, ensure_ascii=False, indent=2)}

RULES
1. Do not use general world knowledge to rescue an unsupported script claim.
2. Exact dates, named sources, quotes, company responses, motives, release
   changes, security claims, product changes, and causal impacts require
   explicit support in supplied evidence.
3. A YouTube upload date is not evidence that the underlying event happened
   on that date.
4. YouTube titles are discovery evidence, not authoritative proof.
5. Reported/alleged information must be phrased with uncertainty.
6. Speculation must be clearly labeled as analysis, not fact.
7. Reviewer concerns are advisory, not automatically true. Resolve each
   factual concern against the supplied evidence rather than ignoring it.
8. If ANY material unsupported claim remains, approved=false.
9. Include every deterministic issue in issues.
10. If there are no material issues, approved=true.
"""

        result = await self._llm.generate_structured(
            prompt,
            FactCheckResult,
            system_prompt=(
                "You are a strict evidence-grounded fact checker. "
                "Unsupported specifics are failures."
            ),
        )

        combined: list[str] = []
        seen: set[str] = set()

        for issue in [*deterministic_issues, *result.issues]:
            clean = str(issue).strip()
            key = clean.lower()
            if clean and key not in seen:
                seen.add(key)
                combined.append(clean)

        result.issues = combined

        if combined:
            result.approved = False
            result.score = min(int(result.score), 70)

        return result

    async def _repair_script(
        self,
        state: WorkflowState,
        issues: list[str],
    ) -> YouTubeScript:
        prompt = f"""
Rewrite the script to remove ALL unsupported factual claims.

TOPIC
{state.topic or "unknown"}

CURRENT SCRIPT
{state.script.model_dump_json(indent=2)}

ISSUES
{json.dumps(issues, ensure_ascii=False, indent=2)}

TOPIC-SPECIFIC AUTHORITATIVE FACTS
{self._authoritative_facts(state.topic or "")}

CURRENT TREND / NEWS EVIDENCE
{self._trend_evidence(state)}

FRESH ENRICHED NEWS EVIDENCE
{self._enriched_evidence(state)}

TOPIC GROUNDING
{json.dumps(state.metadata.get("topic_grounding", {}), ensure_ascii=False, indent=2)}

YOUTUBE DISCOVERY EVIDENCE
{self._youtube_evidence(state)}

REPAIR RULES
1. Preserve the same topic, useful structure, and approximately the same length.
2. Delete unsupported dates, names, quotes, source attributions, company
   responses, motives, causal impacts, and product/release claims.
3. Do not replace one unsupported detail with another.
4. If something is only reported/alleged, explicitly say that.
5. Where evidence is insufficient, discuss uncertainty, implications,
   media-literacy, what is confirmed vs unconfirmed, and how viewers can
   evaluate claims without inventing facts.
6. Do not duplicate the conclusion in a numbered section.
7. Return only the YouTubeScript JSON schema.
"""

        return await self._llm.generate_structured(
            prompt,
            YouTubeScript,
            system_prompt=(
                "Repair factual grounding only. "
                "Never invent replacement facts."
            ),
        )

    @classmethod
    def _deterministic_checks(
        cls,
        state: WorkflowState,
    ) -> list[str]:
        text = json.dumps(
            state.script.model_dump(),
            ensure_ascii=False,
        )
        lower = text.lower()
        evidence = (
            cls._trend_evidence(state)
            + "\n"
            + cls._enriched_evidence(state)
            + "\n"
            + cls._youtube_evidence(state)
            + "\n"
            + cls._authoritative_facts(state.topic or "")
        )
        evidence_lower = evidence.lower()

        issues: list[str] = []

        topic = (state.topic or "").lower()
        if "playwright" in topic and "mcp" in topic:
            if "multi-context page" in lower or "multi context page" in lower:
                issues.append(
                    "Playwright MCP means Model Context Protocol, "
                    "not Multi-Context Page."
                )

            if (
                "playwright mcp is an open standard" in lower
                or "playwright mcp, an open standard" in lower
            ):
                issues.append(
                    "MCP is the open standard; Playwright MCP is an MCP server."
                )

        # Exact natural-language dates need to appear in headline/title evidence.
        date_mentions = set(
            m.group(0).lower()
            for m in re.finditer(
                MONTH_PATTERN + r"\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4})?",
                lower,
            )
        )

        for date_text in sorted(date_mentions):
            bare = re.sub(r"(st|nd|rd|th)", "", date_text)
            if (
                date_text not in evidence_lower
                and bare not in evidence_lower
            ):
                issues.append(
                    f"Exact event date '{date_text}' is not explicitly "
                    "supported by supplied headline/title evidence."
                )

        response_claims = (
            "responded publicly",
            "issued a statement",
            "released a statement",
            "acknowledged the leak",
            "acknowledged the leaks",
            "expressed disappointment",
        )

        if any(phrase in lower for phrase in response_claims):
            support_words = (
                "statement",
                "respond",
                "acknowledg",
                "rockstar says",
                "rockstar confirms",
            )
            if not any(word in evidence_lower for word in support_words):
                issues.append(
                    "The script claims an official/public company response "
                    "without explicit supporting evidence."
                )

        causal_patterns = (
            "influenced the game's final design",
            "influenced the game’s final design",
            "shaped the game's final version",
            "shaped the game’s final version",
            "incorporated into the game's development",
            "incorporated into the game’s development",
            "affected the game's marketing strategy",
            "affected the game’s marketing strategy",
            "forced the company to",
        )

        for phrase in causal_patterns:
            if phrase in lower and phrase not in evidence_lower:
                issues.append(
                    f"Unsupported causal/speculative claim: '{phrase}'."
                )

        return issues

    @staticmethod
    def _authoritative_facts(topic: str) -> str:
        normalized = topic.lower()

        if "playwright" in normalized and "mcp" in normalized:
            return """
- MCP means Model Context Protocol.
- MCP is an open standard.
- Playwright MCP is an MCP server providing browser automation with Playwright.
- It uses structured accessibility snapshots.
- Standard setup: npx @playwright/mcp@latest
- Node.js 20+ and an MCP client are standard prerequisites.
- TypeScript and GitHub Copilot are not universal prerequisites.
- Planner/Generator/Healer are not established built-in Playwright MCP agents.
"""
        return (
            "No topic-specific authoritative fact pack is configured. "
            "Claims must be bounded by the supplied current evidence."
        )

    @staticmethod
    def _trend_evidence(state: WorkflowState) -> str:
        signal = get_signal(state.topic or "")
        if signal is None:
            return "No trend-headline evidence available."

        lines = [
            f"Trend topic: {signal.topic}",
            f"Google Trends searches: {signal.google_trends_traffic}",
            f"Google Trends rank: {signal.google_trends_rank}",
        ]

        for index, headline in enumerate(
            signal.related_headlines[:10],
            start=1,
        ):
            lines.append(f"Headline {index}: {headline}")

        return "\n".join(lines)

    @staticmethod
    def _enriched_evidence(
        state: WorkflowState,
    ) -> str:
        items = state.metadata.get(
            "enriched_evidence",
            [],
        )

        if not items:
            return "No extra Google News RSS evidence captured."

        return "\n".join(
            (
                f"{index}. title={item.get('title', '')!r} | "
                f"source={item.get('source', '') or 'unknown'} | "
                f"published={item.get('published_at', '') or 'unknown'} | "
                f"description={str(item.get('description', ''))[:420]!r}"
            )
            for index, item in enumerate(
                items[:16],
                start=1,
            )
        )

    @staticmethod
    def _review_concerns(
        state: WorkflowState,
    ) -> str:
        review = getattr(
            state,
            "script_review",
            None,
        )

        if review is None:
            return "No script-review concerns available."

        issues = [
            str(
                item
            ).strip()
            for item in review.issues
            if str(
                item
            ).strip()
        ]

        if not issues:
            return (
                f"Reviewer factual_quality={review.factual_quality}; "
                "no factual concerns listed."
            )

        return (
            f"Reviewer factual_quality={review.factual_quality}\\n"
            + "\\n".join(
                f"- {item}"
                for item in issues[:8]
            )
        )

    @staticmethod
    def _youtube_evidence(state: WorkflowState) -> str:
        if state.research is None:
            return "No YouTube evidence available."

        evidence = state.research.top_candidate.evidence[:12]
        if not evidence:
            return "No YouTube evidence available."

        return "\n".join(
            (
                f"{index}. title={item.title!r} | "
                f"channel={item.channel or 'unknown'} | "
                f"uploaded={item.published_at or 'unknown'} | "
                f"url={item.url}"
            )
            for index, item in enumerate(evidence, start=1)
        )
