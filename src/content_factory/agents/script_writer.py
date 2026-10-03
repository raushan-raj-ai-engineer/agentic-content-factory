from __future__ import annotations

import os
import re

from content_factory.agents.base import Agent
from content_factory.agents.script_writer_chunked import generate_chunked_script
from content_factory.llm.base import LLMProvider
from content_factory.models.content import YouTubeScript
from pydantic import BaseModel, Field
from content_factory.modes import is_study_mode
from content_factory.orchestration.state import WorkflowState
from content_factory.research.trend_signals import get_signal


class _SectionAddition(BaseModel):
    section_title: str
    added_narration: str


class _TargetedExpansion(BaseModel):
    additions: list[_SectionAddition] = Field(default_factory=list)


class ScriptWriterAgent(Agent):
    """Generate an evidence-bounded script with realistic narration length."""

    # Study/technical videos need room for viewers to inspect diagrams and code.
    WORDS_PER_MINUTE = 150
    MIN_DURATION_RATIO = 0.95
    MAX_DURATION_RATIO = 1.05

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @property
    def name(self) -> str:
        return "Script Writer Agent"

    async def execute(self, state: WorkflowState) -> WorkflowState:
        if state.strategy is None:
            raise ValueError("Content strategy is required.")

        if not state.strategy_approved:
            raise ValueError(
                "Strategy must be approved before script generation."
            )

        strategy = state.strategy

        print(
            f"[SCRIPT] Mode={'study' if is_study_mode(state) else 'current'}"
        )

        grounding = state.metadata.get(
            "topic_grounding",
            {},
        )

        target_minutes = max(
            1,
            int(
                grounding.get(
                    "target_duration_minutes",
                    strategy.estimated_duration_minutes,
                )
                or strategy.estimated_duration_minutes
            ),
        )

        target_wpm = 144 if is_study_mode(state) else self.WORDS_PER_MINUTE
        target_words = target_minutes * target_wpm

        min_words = round(
            target_words * (0.90 if is_study_mode(state) else 0.78)
        )
        max_words = round(
            target_words * (1.08 if is_study_mode(state) else 1.05)
        )

        script = await generate_chunked_script(
            self,
            state,
            min_words=min_words,
            max_words=max_words,
            target_minutes=target_minutes,
        )

        word_count = self._word_count(script)

        if is_study_mode(state) and word_count < min_words:
            script = await self._targeted_expand_study_script(
                state=state,
                script=script,
                missing_words=min_words - word_count,
            )
            word_count = self._word_count(script)

        severe_shortfall = (
            word_count
            < round(
                min_words
                * 0.82
            )
        )
        severe_overrun = (
            word_count
            > round(
                max_words
                * 1.08
            )
        )

        # V21: never launch another giant full-script Ollama rewrite.
        should_repair = False

        if (
            severe_shortfall
            and not should_repair
        ):
            print(
                f"[SCRIPT] Length {word_count} words is far below "
                f"{min_words}-{max_words} even after targeted section expansion. "
                "Keeping factual completeness instead of padding with filler; "
                "final duration will follow actual narration."
            )

        elif (
            (
                severe_shortfall
                or severe_overrun
            )
            and should_repair
        ):
            print(
                f"[SCRIPT] Length {word_count} words; "
                f"evidence-adjusted target {min_words}-{max_words}. "
                "Repairing once."
            )

            repair_prompt = self._build_prompt(
                state=state,
                min_words=min_words,
                max_words=max_words,
                current_script=script,
            )

            repaired = await self._llm.generate_structured(
                repair_prompt,
                YouTubeScript,
                system_prompt=(
                    f"Adjust only length and clarity in "
                    f"{self._target_language_name(state)}. "
                    "Preserve one consistent target language across every "
                    "viewer-facing field. Preserve evidence limits. "
                    "Do not add any new factual claim."
                ),
            )

            repaired_count = self._word_count(repaired)

            if self._distance_to_range(
                repaired_count,
                min_words,
                max_words,
            ) <= self._distance_to_range(
                word_count,
                min_words,
                max_words,
            ):
                script = repaired
                word_count = repaired_count

        actual_minutes = self._estimated_duration_minutes(
            word_count
        )

        previous_minutes = int(
            script.estimated_duration_minutes
            or actual_minutes
        )

        script.estimated_duration_minutes = actual_minutes

        print(
            f"[SCRIPT] Final narration length: {word_count} words "
            f"(evidence-adjusted target {min_words}-{max_words}); "
            f"duration={actual_minutes}m"
        )

        if previous_minutes != actual_minutes:
            print(
                f"[SCRIPT] Duration reconciled: "
                f"{previous_minutes}m -> {actual_minutes}m "
                "from actual narration length."
            )

        state.metadata["script_length"] = {
            "words": word_count,
            "target_minutes": target_minutes,
            "actual_minutes": actual_minutes,
            "min_words": min_words,
            "max_words": max_words,
            "duration_source": grounding.get("duration_source", "strategy"),
            "strategy_completion_ratio": round(
                word_count / max(1, target_words), 3
            ),
        }

        state.script = script
        state.status = "script_generated"
        return state

    async def _targeted_expand_study_script(
        self,
        *,
        state: WorkflowState,
        script: YouTubeScript,
        missing_words: int,
    ) -> YouTubeScript:
        """Expand only thin study sections instead of rewriting the whole script."""
        if missing_words <= 0 or not script.sections:
            return script

        ranked = sorted(
            script.sections,
            key=lambda section: len(
                re.findall(r"\b[\w@./+-]+\b", section.content)
            ),
        )[: min(3, len(script.sections))]
        candidates = "\n\n".join(
            f"SECTION: {section.title}\n{section.content}" for section in ranked
        )
        requested = min(max(missing_words, 120), 900)
        prompt = f"""
The approved study strategy requires more teaching depth, but the current script is short.
Add approximately {requested} NEW spoken words across ONLY the listed sections.

TOPIC: {state.strategy.topic if state.strategy else state.topic}
TARGET AUDIENCE: {state.strategy.audience if state.strategy else ''}

THIN SECTIONS
{candidates}

RULES
1. Return additions only; do not rewrite or delete existing narration.
2. section_title must exactly match one title shown above.
3. Deepen mechanisms, worked traces, theory-to-code mapping, verification, or concrete edge cases.
4. Do not add filler, repeated definitions, hype, current statistics, release claims, quotations, or unsupported facts.
5. Keep beginner-friendly spoken English and connect naturally from the existing section.
6. Total new narration should be close to {requested} words.
"""
        try:
            expansion = await self._llm.generate_structured(
                prompt,
                _TargetedExpansion,
                system_prompt=(
                    "You expand only underdeveloped sections of an approved educational "
                    "script. Preserve factual boundaries and return structured JSON only."
                ),
            )
        except Exception as exc:
            print(
                "[SCRIPT DEPTH] targeted expansion unavailable: "
                f"{exc.__class__.__name__}; keeping factual draft"
            )
            return script

        by_title = {section.title: section for section in script.sections}
        added_words = 0
        for addition in expansion.additions:
            section = by_title.get(addition.section_title)
            text = addition.added_narration.strip()
            if section is None or not text:
                continue
            section.content = section.content.rstrip() + " " + text
            added_words += len(re.findall(r"\b[\w@./+-]+\b", text))

        if added_words:
            print(
                f"[SCRIPT DEPTH] targeted expansion added {added_words} words "
                f"across {min(len(expansion.additions), 3)} thin section(s)."
            )
        return script

    def _build_prompt(
        self,
        *,
        state: WorkflowState,
        min_words: int,
        max_words: int,
        current_script: YouTubeScript | None,
    ) -> str:
        strategy = state.strategy

        current = ""
        if current_script is not None:
            current = (
                "\nCURRENT SCRIPT TO EXPAND/TRIM WITHOUT ADDING FACTS\n"
                f"{current_script.model_dump_json(indent=2)}\n"
            )

        study_mode = is_study_mode(state)
        grounding_policy = (
            """
STUDY MODE GROUNDING
- This is an evergreen technical lesson. Current trend/news evidence is discovery context, not the lesson outline.
- You MAY explain stable technical definitions, architecture, algorithms, code behavior, and common engineering practices using established technical knowledge.
- Do NOT invent fresh/current facts such as release dates, adoption numbers, product launches, benchmark claims, quotations, or company announcements. Use supplied evidence only if such current facts are truly needed.
- Prefer teaching the underlying concept over discussing news about the concept.
"""
            if study_mode
            else """
CURRENT-EVENT GROUNDING
- Treat supplied trend/news evidence as the factual boundary for time-sensitive claims.
- Do not invent unsupported specifics.
"""
        )

        return f"""
Create an accurate YouTube narration script.

{grounding_policy}

APPROVED STRATEGY
Topic: {strategy.topic}
Audience: {strategy.audience}
Angle: {strategy.angle}
Hook: {strategy.hook}
Content type: {strategy.content_type}
Target duration: {strategy.estimated_duration_minutes} minutes

SPOKEN LENGTH
Complete spoken narration MUST be approximately {min_words}-{max_words} words.

TOPIC-SPECIFIC AUTHORITATIVE FACTS
{self._authoritative_facts(state.topic or strategy.topic)}

CURRENT TREND / NEWS EVIDENCE
{self._trend_evidence(state)}

FRESH ENRICHED NEWS EVIDENCE
{self._enriched_evidence(state)}

TOPIC GROUNDING
{self._grounding_context(state)}

YOUTUBE DISCOVERY EVIDENCE
{self._youtube_evidence(state)}
{current}

LANGUAGE AND VOICE-FRIENDLY WRITING
{self._language_instruction(state)}

SUBJECT-MATTER-EXPERT TEACHING RULES
1. For educational, technical, coding, AI, automation, architecture, data, science, or engineering topics, teach as a subject-matter expert rather than as a newsreader.
2. Open with a concrete, informative learner problem plus the mechanism/payoff. Prefer a declarative hook over a rhetorical question. Do not use generic openings such as "Have you ever wondered", "Did you know", "What if", or "Imagine", and do not spend the first lines welcoming viewers or restating the title.
3. Unless the approved audience is explicitly advanced, assume the viewer is a beginner. Immediately after the hook, give THEORY FIRST as exactly three short declarative ideas: (1) plain-language definition, (2) key idea/distinction, (3) why it matters/usefulness. Only after those three points may the detailed mechanism or flow begin.
4. Establish the mental model before implementation detail: WHY the mechanism works, WHAT changes, then HOW to implement or verify it.
5. For AI topics, define specialized terms (for example retrieval, embedding, context window, agent, tool call, evaluation) before relying on them. Explain the data/control flow before code or framework names.
6. Prefer short spoken sentences with deliberate transitions. Dense code, formulas, commands, metrics, or architecture steps must be surrounded by plain-language explanation.
5. When useful, include one misconception, failure mode, boundary condition, or tradeoff. Do not invent one when evidence is insufficient.
6. End technical sections with a verification idea: a test, observation, prediction, or check the viewer can perform.
7. Avoid hype, filler, generic motivational claims, and unsupported superlatives.
8. Keep terminology precise and consistent. Define an acronym or specialized term the first time it matters to understanding.
9. For tutorial-style topics, organize the learning arc as: problem/hook → plain-language theory → one simple analogy or mental model when useful → worked example or flow → implementation/details → verification → concrete edge cases/tradeoffs → recap/practice.
10. BEGINNER MINI-ARC INSIDE EACH SUBSTANTIVE SECTION: first explain WHAT the concept means as 2-3 short theory points using plain language; only after that explain HOW IT FLOWS as a concrete cause → action → result sequence. Then add one example/implementation or verification point when useful. Do not open a section with a diagram-like list of components before defining the idea.
11. When code is shown, explicitly connect the visual/theoretical step to the exact variable, branch, function, or line that implements it. Never drop code on screen without explaining what earlier reasoning it represents.
12. Give concrete beginner-friendly edge examples instead of naming edge-case categories only. For example, show what should happen for an empty input, one-item input, missing result, or boundary value when those cases apply.

STUDY ENGAGEMENT CONTRACT
For study lessons: use the first 35 spoken words to show a concrete failure or
surprising result and promise one demonstrable skill. Pay off that promise in
the worked example; never invent metrics or use clickbait. Do not force quiz questions, pause-and-predict prompts, or rhetorical questions between sections.
Maintain engagement through concrete examples, visible cause/effect, small reveals, and clear transitions.
Finish with an optional transfer exercise using a changed input and a way to verify it.
Keep these activities inside the approved duration/word budget.

VOICE / CHARACTER RULES
1. Write for natural spoken delivery, not formal article prose.
2. The main narrator should remain the primary storyteller.
3. For genuinely fictional/cartoon/storytelling dialogue only, a speaker may
   be written as `CharacterName: dialogue`. Reuse the exact same character
   label whenever that character speaks so the Voice Director can keep the
   same voice.
4. Do NOT invent dialogue or quotes for real people, companies, athletes,
   politicians, developers, witnesses, or news subjects.
5. Current-news/factual videos should normally use narrator-only delivery
   unless an exact quote is explicitly supported by evidence.
6. Avoid changing language inside a sentence except unavoidable names,
   product names, commands, or commonly used audience terms.
7. The APPROVED STRATEGY may contain English helper text even when the selected
   audience language is not English. Translate/re-express that helper wording
   naturally into the selected narration language. Do not preserve English
   strategy sentences merely because they appear above.
8. Do not mention internal discovery mechanics such as Google Trends rank,
   candidate score, search-volume estimate, validation confidence, or pipeline
   metadata unless that metric is itself the subject of the video.

STRICT GROUNDING RULES
0. First establish what the topic actually IS. In study mode, use the topic, authoritative fact pack, and stable technical knowledge; in current-event mode, use the supplied evidence. Do not turn
   an action/crime movie into a historical film, a sports fixture into a
   transfer story, or a legal petition into a political event. If topic
   identity is uncertain, use conservative wording.
1. Never invent a date, person, channel, organization, quote, leak source,
   company statement, release detail, gameplay detail, statistic, motive,
   consequence, or causal impact.
2. A time-sensitive or event-specific factual detail may be stated only when the supplied evidence explicitly contains it. Stable technical fundamentals in study mode may be explained from established technical knowledge.
3. A YouTube video's upload date proves only when that video was uploaded;
   it does NOT prove when the underlying event happened.
4. A YouTube title is discovery/context evidence, not authoritative proof.
5. For current-event claims that are only reported/alleged, use wording like
   "reports say", "the circulating material appears to", or
   "the available reports describe" rather than asserting certainty.
6. Never claim that a company responded, acknowledged something, changed its
   strategy, or changed a product because of an event unless evidence says so.
7. Never infer that leaks/feedback changed a final design or release plan.
8. If current-event evidence is thin, omit unsupported current claims. In study mode, continue with stable concept teaching, examples, code, verification, and limitations instead of filling the lesson with news uncertainty.
9. Do not repeat the conclusion as a numbered section and then repeat it again
   in the conclusion field. Use the sections for substantive content only.
10. Return only the required JSON schema.
"""

    @classmethod
    def _language_instruction(
        cls,
        state: WorkflowState,
    ) -> str:
        target = cls._target_language_name(
            state
        )

        if target.lower().startswith(
            "hindi"
        ):
            return (
                "Narration language: Hindi (India). "
                "Use natural conversational Devanagari Hindi; keep unavoidable "
                "English product names, game titles, commands and technical "
                "terms unchanged where that sounds natural. Do not translate "
                "proper nouns into misleading forms. Every normal narration "
                "sentence must remain Hindi."
            )

        locale = str(
            state.metadata.get("target_locale", "") or ""
        ).strip().replace("-", "_").lower()

        if locale == "en_us" or "united states" in target.lower():
            return (
                "Narration language: English (United States). "
                "Use natural American English spelling, vocabulary, rhythm, and "
                "examples. Prefer forms such as color, center, analyze, and "
                "program when context permits. Define technical jargon before "
                "using it, keep sentences easy to speak aloud, and do not drift "
                "into another regional English variety unless a proper noun or "
                "quoted technical term requires it."
            )

        return (
            f"Narration language: {target}. "
            "Keep ALL viewer-facing narration naturally in this selected "
            "language. Proper nouns may remain unchanged. Do not switch back "
            "to English for introductions, section bodies, conclusions or CTA."
        )

    @staticmethod
    def _target_language_name(
        state: WorkflowState,
    ) -> str:
        override = os.getenv(
            "CONTENT_FACTORY_LANGUAGE",
            "auto",
        ).strip().lower()

        aliases = {
            "en": "English",
            "en_us": "English (United States)",
            "en-us": "English (United States)",
            "english": "English",
            "en_gb": "English (United Kingdom)",
            "en-gb": "English (United Kingdom)",
            "hi": "Hindi (India)",
            "hi_in": "Hindi (India)",
            "hindi": "Hindi (India)",
            "hinglish": "Hindi/Hinglish",
            "es": "Spanish",
            "es_es": "Spanish",
            "es_mx": "Spanish",
            "spanish": "Spanish",
            "pt": "Portuguese",
            "pt_br": "Portuguese",
            "portuguese": "Portuguese",
            "id": "Indonesian",
            "id_id": "Indonesian",
            "indonesian": "Indonesian",
            "ja": "Japanese",
            "ja_jp": "Japanese",
            "japanese": "Japanese",
            "ar": "Arabic",
            "ar_sa": "Arabic",
            "arabic": "Arabic",
            "bn": "Bengali",
            "bn_bd": "Bengali",
            "bengali": "Bengali",
            "fr": "French",
            "fr_fr": "French",
            "french": "French",
            "ur": "Urdu",
            "ur_pk": "Urdu",
            "urdu": "Urdu",
            "de": "German",
            "german": "German",
            "vi": "Vietnamese",
            "vietnamese": "Vietnamese",
            "tr": "Turkish",
            "turkish": "Turkish",
            "ta": "Tamil",
            "tamil": "Tamil",
            "te": "Telugu",
            "telugu": "Telugu",
            "mr": "Marathi",
            "marathi": "Marathi",
            "pa": "Punjabi",
            "punjabi": "Punjabi",
            "gu": "Gujarati",
            "gujarati": "Gujarati",
            "kn": "Kannada",
            "kannada": "Kannada",
            "ml": "Malayalam",
            "malayalam": "Malayalam",
            "ru": "Russian",
            "russian": "Russian",
            "zh": "Chinese",
            "chinese": "Chinese",
        }

        if override != "auto":
            return aliases.get(
                override,
                override,
            )

        metadata_name = str(
            state.metadata.get(
                "target_language_name",
                "",
            )
            or ""
        ).strip()

        if metadata_name:
            return metadata_name

        metadata_code = str(
            state.metadata.get(
                "target_language",
                "",
            )
            or ""
        ).strip().lower()

        if metadata_code:
            return aliases.get(
                metadata_code,
                metadata_code,
            )

        # Backward-compatible fallback for runs without V8.4 metadata.
        strategy = state.strategy
        audience = (
            strategy.audience
            if strategy is not None
            else ""
        )
        topic = (
            state.topic
            or (
                strategy.topic
                if strategy is not None
                else ""
            )
        )

        context = f"{audience} {topic}".lower()

        for marker, name in (
            ("hindi", "Hindi (India)"),
            ("हिंदी", "Hindi (India)"),
            ("हिन्दी", "Hindi (India)"),
            ("spanish", "Spanish"),
            ("español", "Spanish"),
            ("portuguese", "Portuguese"),
            ("português", "Portuguese"),
            ("indonesian", "Indonesian"),
            ("japanese", "Japanese"),
            ("arabic", "Arabic"),
            ("bengali", "Bengali"),
            ("french", "French"),
            ("urdu", "Urdu"),
            ("german", "German"),
            ("vietnamese", "Vietnamese"),
            ("turkish", "Turkish"),
            ("tamil", "Tamil"),
            ("telugu", "Telugu"),
            ("marathi", "Marathi"),
            ("punjabi", "Punjabi"),
            ("gujarati", "Gujarati"),
            ("kannada", "Kannada"),
            ("malayalam", "Malayalam"),
            ("russian", "Russian"),
            ("chinese", "Chinese"),
        ):
            if marker in context:
                return name

        return "English"

    @staticmethod
    def _authoritative_facts(topic: str) -> str:
        normalized = topic.lower()

        if "playwright" in normalized and "mcp" in normalized:
            return """
- MCP means Model Context Protocol.
- MCP is an open protocol for connecting AI applications with external context/capabilities.
- Playwright MCP is an MCP server providing browser automation with Playwright.
- It can expose browser interaction through structured page/accessibility information.
- A common setup command is: npx @playwright/mcp@latest
- An MCP client is required.
- TypeScript and GitHub Copilot are not universal prerequisites.
- Planner, Generator, and Healer are not established built-in Playwright MCP agents.
"""
        if "model context protocol" in normalized or normalized.strip() == "mcp" or " mcp" in normalized:
            return """
- MCP means Model Context Protocol.
- MCP standardizes how an AI application can connect to external context and capabilities.
- The architecture is commonly described using hosts, clients, and servers.
- MCP servers can expose tools, resources, and prompts to clients.
- Tools represent callable actions; resources expose readable context/data; prompts provide reusable prompt templates.
- MCP uses structured protocol messages and JSON-RPC 2.0 semantics.
- Permissions, input validation, output validation, and testing are still required; MCP does not make tools automatically safe.
"""
        if "rag" in normalized or "retrieval augmented" in normalized:
            return """
- RAG means retrieval-augmented generation.
- RAG retrieves external information and adds it to the model's context before generation.
- Embeddings are a common method for semantic retrieval.
- Vector databases are common but not mandatory; other search/retrieval systems can be used.
- Retrieval quality and generation quality should be evaluated separately.
- RAG does not guarantee factual correctness.
"""
        if "ai agent" in normalized or "agents" in normalized:
            return """
- An AI agent can use a model to choose actions/tools while working toward a task.
- Tools can expose APIs, search, databases, browser actions, code execution, or business operations.
- Persistent memory is optional, not a requirement for every agent.
- Agent testing should cover tool choice, arguments, ordering, completion, error handling, permissions, and unsafe instructions.
"""
        return (
            "No special fact pack is configured. In study mode, use established "
            "technical knowledge for stable fundamentals and avoid unsupported "
            "time-sensitive claims."
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

        if not signal.related_headlines:
            lines.append(
                "No related Google Trends news headlines were captured."
            )

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

        lines = []

        for index, item in enumerate(
            items[:16],
            start=1,
        ):
            lines.append(
                (
                    f"{index}. title={item.get('title', '')!r} | "
                    f"source={item.get('source', '') or 'unknown'} | "
                    f"published={item.get('published_at', '') or 'unknown'} | "
                    f"description={str(item.get('description', ''))[:420]!r}"
                )
            )

        return "\n".join(lines)

    @staticmethod
    def _grounding_context(
        state: WorkflowState,
    ) -> str:
        value = state.metadata.get(
            "topic_grounding",
            {},
        )

        if not value:
            return "No deterministic grounding metadata available."

        return (
            f"Evidence count: {value.get('evidence_count', 0)}\n"
            f"Top evidence keywords: {', '.join(value.get('top_keywords', [])[:12])}\n"
            f"Strategy corrected: {value.get('corrected', False)}\n"
            f"Unsupported strategy terms removed: "
            f"{', '.join(value.get('unsupported_strategy_terms', [])[:12])}"
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
                f"views={item.view_count} | url={item.url}"
            )
            for index, item in enumerate(evidence, start=1)
        )

    @staticmethod
    def _word_count(script: YouTubeScript) -> int:
        parts = [
            script.hook,
            script.introduction,
            *(section.content for section in script.sections),
            script.conclusion,
            script.call_to_action,
        ]
        return len(re.findall(r"\b[\w@./+-]+\b", " ".join(parts)))

    @staticmethod
    def _should_attempt_length_repair(
        *,
        word_count: int,
        min_words: int,
        max_words: int,
    ) -> bool:
        if word_count > round(
            max_words
            * 1.08
        ):
            return True

        if word_count >= min_words:
            return False

        # A near-target miss can often be repaired cleanly. A 40-50% shortfall
        # tends to trigger another expensive generation without enough grounded
        # content; accept a shorter, truthful video instead.
        ratio = (
            word_count
            / max(
                min_words,
                1,
            )
        )

        return ratio >= 0.70

    @staticmethod
    def _estimated_duration_minutes(
        word_count: int,
    ) -> int:
        # Observed local narrator pace is closer to ~145 wpm than 165.
        return max(
            1,
            round(
                max(
                    word_count,
                    1,
                )
                / 145.0
            ),
        )

    @staticmethod
    def _distance_to_range(
        value: int,
        low: int,
        high: int,
    ) -> int:
        if low <= value <= high:
            return 0
        if value < low:
            return low - value
        return value - high
