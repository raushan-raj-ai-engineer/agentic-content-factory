from __future__ import annotations

import os
import re

from content_factory.agents.base import Agent
from content_factory.agents.script_writer_chunked import generate_chunked_script
from content_factory.llm.base import LLMProvider
from content_factory.models.content import YouTubeScript
from content_factory.orchestration.state import WorkflowState
from content_factory.research.trend_signals import get_signal


class ScriptWriterAgent(Agent):
    """Generate an evidence-bounded script with realistic narration length."""

    WORDS_PER_MINUTE = 165
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

        target_words = (
            target_minutes
            * self.WORDS_PER_MINUTE
        )

        min_words = round(
            target_words
            * 0.78
        )
        max_words = round(
            target_words
            * 1.05
        )

        script = await generate_chunked_script(
            self,
            state,
            min_words=min_words,
            max_words=max_words,
            target_minutes=target_minutes,
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
                f"{min_words}-{max_words}. Skipping a second full rewrite "
                "to avoid filler, unsupported expansion, and duplicate "
                "Ollama latency. Duration will follow actual narration."
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
        }

        state.script = script
        state.status = "script_generated"
        return state

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

        return f"""
Create an accurate YouTube narration script.

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
0. First establish what the topic actually IS from the evidence. Do not turn
   an action/crime movie into a historical film, a sports fixture into a
   transfer story, or a legal petition into a political event. If topic
   identity is uncertain, use conservative wording.
1. Never invent a date, person, channel, organization, quote, leak source,
   company statement, release detail, gameplay detail, statistic, motive,
   consequence, or causal impact.
2. An exact factual detail may be stated only when the supplied evidence
   explicitly contains that detail.
3. A YouTube video's upload date proves only when that video was uploaded;
   it does NOT prove when the underlying event happened.
4. A YouTube title is discovery/context evidence, not authoritative proof.
5. For current-event claims that are only reported/alleged, use wording like
   "reports say", "the circulating material appears to", or
   "the available reports describe" rather than asserting certainty.
6. Never claim that a company responded, acknowledged something, changed its
   strategy, or changed a product because of an event unless evidence says so.
7. Never infer that leaks/feedback changed a final design or release plan.
8. If evidence is thin, explain only what is known and label uncertainty.
   It is better to be cautious than to fill eight minutes with invented facts.
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
            "en_us": "English",
            "english": "English",
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
- MCP is an open standard for connecting AI applications with tools/data.
- Playwright MCP is an MCP server providing browser automation with Playwright.
- It enables LLMs to interact with pages using structured accessibility snapshots.
- Standard setup uses: npx @playwright/mcp@latest
- Node.js 20+ and an MCP client are standard prerequisites.
- TypeScript and GitHub Copilot are not universal prerequisites.
- Planner, Generator, and Healer are not established built-in Playwright MCP agents.
"""
        return (
            "No special fact pack is configured. "
            "Use only the supplied trend/news/YouTube evidence."
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
