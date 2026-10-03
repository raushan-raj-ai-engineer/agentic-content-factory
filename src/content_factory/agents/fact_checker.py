from __future__ import annotations

import json
import re

from content_factory.agents.base import Agent
from content_factory.llm.base import LLMProvider
from content_factory.models.content import FactCheckResult, YouTubeScript
from content_factory.modes import is_study_mode
from content_factory.orchestration.state import WorkflowState
from content_factory.research.trend_signals import get_signal


NO_ISSUE_STATUS_PATTERNS = (
    re.compile(r"^no material false or unsupported current claims remain\.?$", re.I),
    re.compile(r"^no material false or unsupported claims remain\.?$", re.I),
    re.compile(r"^no material factual issues remain\.?$", re.I),
    re.compile(r"^no material issues remain\.?$", re.I),
    re.compile(r"^no unsupported current claims remain\.?$", re.I),
    re.compile(r"^no unsupported claims remain\.?$", re.I),
    re.compile(r"^no factual errors remain\.?$", re.I),
    re.compile(r"^no factual issues remain\.?$", re.I),
    re.compile(r"^no issues remain\.?$", re.I),
)


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

        print(
            f"[FACT] Mode={'study' if is_study_mode(state) else 'current'}"
        )
        first = await self._check(state)

        if first.approved and not first.issues:
            state.fact_check = first
            state.status = "fact_checked"
            print(f"[FACT] Passed with score={first.score}")
            return state

        # An empty issue list does not reverse the checker's rejection.
        if not first.issues:
            state.fact_check = first
            state.status = "fact_check_blocked"
            state.stop_requested = True
            print("[FACT] BLOCKED: checker rejected without actionable repair details")
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
        study_mode = is_study_mode(state)

        if study_mode:
            checking_policy = """
STUDY-MODE FACT-CHECK POLICY
- This is an evergreen technical tutorial, not a breaking-news report.
- Validate stable technical definitions, architecture, algorithms, code behavior,
  and best-practice explanations against the authoritative fact pack and your
  established technical knowledge.
- Do NOT reject a correct stable technical concept merely because it is absent
  from Google News or a YouTube title.
- Fresh/current claims (dates, launches, adoption counts, company announcements,
  benchmark numbers, quotations, or claims that something happened recently)
  still require explicit supplied evidence.
- Prefer removing unnecessary current-event claims rather than turning the
  tutorial into media-literacy commentary.
- Material technical errors must still fail the check.
"""
        else:
            checking_policy = """
CURRENT-EVENT FACT-CHECK POLICY
- Bound factual claims to the supplied evidence.
- Unsupported current-event specifics are failures.
"""

        prompt = f"""
Fact-check this YouTube script using the appropriate content policy.

{checking_policy}

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
1. In study mode, stable technical knowledge may be used to validate stable
   technical claims; in current-event mode, do not use general knowledge to
   rescue unsupported current claims.
2. Exact dates, named sources, quotes, company responses, motives, release
   changes, security incidents, adoption numbers, product changes, and causal
   impacts require explicit support in supplied evidence.
3. A YouTube upload date is not evidence that the underlying event happened
   on that date.
4. YouTube titles are discovery evidence, not authoritative proof.
5. Reported/alleged current information must be phrased with uncertainty.
6. Speculation must be clearly labeled as analysis, not fact.
7. Reviewer concerns are advisory, not automatically true. Resolve each
   concern against the relevant evidence/technical knowledge.
8. If ANY material false or unsupported current claim remains, approved=false.
9. Include every deterministic issue in issues.
10. If there are no material issues, approved=true.
11. IMPORTANT: when approved=true, issues MUST be an empty list []. Do not put success/status sentences such as "No material issues remain" inside issues.
"""

        result = await self._llm.generate_structured(
            prompt,
            FactCheckResult,
            system_prompt=(
                "You are a senior technical fact checker. "
                + (
                    "For evergreen tutorials, distinguish stable technical knowledge "
                    "from time-sensitive claims and do not demand news evidence for "
                    "correct fundamentals."
                    if study_mode
                    else "Unsupported current-event specifics are failures."
                )
            ),
        )

        combined: list[str] = []
        seen: set[str] = set()

        raw_llm_issues = [str(issue).strip() for issue in result.issues if str(issue).strip()]
        normalized_statuses: list[str] = []

        for issue in [*deterministic_issues, *raw_llm_issues]:
            clean = str(issue).strip()
            key = clean.lower()
            if not clean or key in seen:
                continue
            seen.add(key)

            # Some models occasionally put a success/status sentence in the
            # issues array. Treat only a narrow set of explicit no-issue
            # statements as status text; never suppress actionable concerns.
            if issue not in deterministic_issues and self._is_no_issue_status(clean):
                normalized_statuses.append(clean)
                continue

            combined.append(clean)

        result.issues = combined

        if combined:
            result.approved = False
            result.score = min(int(result.score), 70)
        elif raw_llm_issues and normalized_statuses and len(normalized_statuses) == len(raw_llm_issues):
            # The payload is semantically a pass even if the model emitted an
            # inconsistent approved=false flag alongside a no-issue sentence.
            result.approved = True
            print(
                "[FACT] Normalized non-actionable no-issue status text; "
                "no material fact-check issues remain."
            )

        return result

    @staticmethod
    def _is_no_issue_status(text: str) -> bool:
        normalized = " ".join(text.strip().split())
        return any(pattern.fullmatch(normalized) for pattern in NO_ISSUE_STATUS_PATTERNS)

    async def _repair_script(
        self,
        state: WorkflowState,
        issues: list[str],
    ) -> YouTubeScript:
        study_mode = is_study_mode(state)
        repair_policy = (
            "For this evergreen technical tutorial, preserve correct stable technical "
            "teaching and REMOVE unnecessary news/report/date language. Rebuild any "
            "affected section around definition, mental model, mechanism, example, "
            "implementation, verification, and edge cases. Do not replace the lesson "
            "with uncertainty/media-literacy filler."
            if study_mode
            else "Keep the script evidence-bounded and remove unsupported current claims."
        )

        prompt = f"""
Rewrite the script to remove ALL unsupported or incorrect factual claims.

MODE-SPECIFIC REPAIR POLICY
{repair_policy}

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
5. In study mode, when current evidence is insufficient, omit the current-event
   claim and continue teaching stable technical fundamentals. In current-event
   mode, discuss uncertainty and what is confirmed vs unconfirmed.
6. Do not duplicate the conclusion in a numbered section.
7. Preserve beginner-friendly theory before implementation and include
   verification plus concrete edge/failure examples when applicable.
8. Return only the YouTubeScript JSON schema.
"""

        return await self._llm.generate_structured(
            prompt,
            YouTubeScript,
            system_prompt=(
                "Repair factual grounding without inventing replacement facts. "
                + (
                    "Keep evergreen technical teaching useful and concept-first."
                    if study_mode
                    else "Keep current-event claims evidence-bounded."
                )
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

        # Study examples sometimes accidentally turn into live/current claims
        # (for example: "Tokyo today: -22°C"). A precise number paired with
        # today/current/right-now language is time-sensitive and must be sourced
        # or rewritten as an explicitly hypothetical example.
        current_numeric = re.compile(
            r"[^.!?]{0,90}\b(?:today|right now|currently|current)\b[^.!?]{0,90}"
            r"(?:[-+]?\d+(?:\.\d+)?\s*(?:°[cf]|%|usd|eur|gbp|inr|dollars?|euros?|pounds?))",
            re.IGNORECASE,
        )
        for match in current_numeric.finditer(text):
            claim = re.sub(r"\s+", " ", match.group(0)).strip()
            if claim and claim.lower() not in evidence_lower:
                issues.append(
                    "Unsourced live/current numeric example must be removed or made explicitly hypothetical: "
                    + claim[:160]
                )

        return issues

    @staticmethod
    def _authoritative_facts(topic: str) -> str:
        normalized = topic.lower()

        if "playwright" in normalized and "mcp" in normalized:
            return """
- MCP means Model Context Protocol.
- MCP is an open protocol for connecting AI applications to external tools/data.
- Playwright MCP is an MCP server providing browser automation with Playwright.
- It uses structured page/accessibility information for browser interaction.
- A common setup command is: npx @playwright/mcp@latest
- An MCP client is required.
- TypeScript and GitHub Copilot are not universal prerequisites.
- Planner/Generator/Healer are not established built-in Playwright MCP agents.
"""
        if "model context protocol" in normalized or normalized.strip() == "mcp" or " mcp" in normalized:
            return """
- MCP means Model Context Protocol.
- MCP standardizes how an AI application can connect to external context and capabilities.
- The architecture is commonly described using hosts, clients, and servers.
- MCP servers can expose tools, resources, and prompts to clients.
- Tool calls let a model-driven application request an action exposed by a server.
- Resources provide readable context/data; prompts provide reusable prompt templates.
- MCP uses structured protocol messages; JSON-RPC 2.0 is part of the protocol design.
- MCP does not make an AI system automatically safe or correct; permissions, validation, and testing still matter.
"""
        if "rag" in normalized or "retrieval augmented" in normalized:
            return """
- RAG means retrieval-augmented generation.
- A RAG system retrieves relevant external information and supplies it as context for generation.
- Embeddings are a common way to represent semantic similarity for retrieval.
- Vector databases are common for embedding search but are not the only possible retrieval mechanism.
- Retrieval quality and answer quality are separate concerns and should be evaluated separately.
- RAG can reduce some unsupported answers but does not guarantee factual correctness.
"""
        if "ai agent" in normalized or "agents" in normalized:
            return """
- An AI agent is a system in which a model can select actions/tools as part of a task loop.
- Tools expose capabilities such as search, APIs, databases, code execution, or business actions.
- Memory is optional; not every agent requires persistent memory.
- Agent testing should validate tool selection, arguments, sequencing, task completion, and safety boundaries.
- Tool outputs and permissions require validation; an agent is not automatically reliable because it can call tools.
"""
        return (
            "No topic-specific fact pack is configured. For evergreen study videos, "
            "validate stable technical fundamentals using established technical knowledge; "
            "time-sensitive claims still require supplied evidence."
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
