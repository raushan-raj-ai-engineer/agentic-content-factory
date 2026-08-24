from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from content_factory.agents.base import Agent
from content_factory.llm.base import LLMProvider
from content_factory.orchestration.state import WorkflowState
from content_factory.utils.unicode_tokens import unicode_tokens


class PackagingVariant(BaseModel):
    label: str
    angle: str
    title: str
    thumbnail_text: str = ""
    thumbnail_prompt: str
    promise_alignment: str


class PackagingSet(BaseModel):
    variants: list[PackagingVariant] = Field(
        min_length=3,
        max_length=3,
    )
    default_index: int = 0
    description_opening: str


class PackagingOptimizerAgent(Agent):
    """
    Build three materially different title/thumbnail packages.

    The default title becomes state.script.title BEFORE fact checking, so the
    existing fact checker sees the final default packaging.
    """

    def __init__(
        self,
        llm: LLMProvider,
    ) -> None:
        self._llm = llm

    @property
    def name(self) -> str:
        return "Packaging Optimizer Agent"

    async def execute(
        self,
        state: WorkflowState,
    ) -> WorkflowState:
        if state.script is None:
            raise ValueError(
                "Script is required before packaging optimization."
            )

        growth = state.metadata.get(
            "growth_plan",
            {},
        )

        script_summary = self._script_summary(
            state
        )

        prompt = f"""
Create THREE accurate YouTube title + thumbnail packages for A/B testing.

TOPIC
{state.topic or "unknown"}

TARGET VIEWER LANGUAGE
{self._target_language_name(state)}

GROWTH PLAN
{json.dumps(growth, ensure_ascii=False, indent=2)}

FINAL SCRIPT SUMMARY
{script_summary}

FRESH TOPIC EVIDENCE
{self._evidence_context(state)}

TOPIC GROUNDING
{json.dumps(state.metadata.get("topic_grounding", {}), ensure_ascii=False, indent=2)}

CURRENT TITLE
{state.script.title}

RULES
1. Every title and thumbnail promise must be fully supported by the script
   AND must match the topic identity shown in the fresh evidence.
2. Never invent a genre/category/identity for the topic. For example, never
   call an action/crime film a historical film unless evidence explicitly says so.
3. Never invent a fact, quote, result, number, secret, confirmation, leak,
   controversy, emotion or outcome.
3. Make all three packages meaningfully different:
   A = searchable / clear intent
   B = curiosity / question / tension
   C = broad viewer benefit / consequence / payoff
4. Titles should usually be concise, preferably ~45-70 characters when
   natural. Put important words early.
5. Do not use dishonest ALL CAPS, excessive punctuation, fake shock or
   "You Won't Believe..." style clickbait.
6. thumbnail_text should be 0-4 short words. It should complement the title,
   not repeat the full title.
7. Thumbnail composition must have ONE clear focal idea, large readable
   subject, mobile-friendly layout and room for text.
8. If a real person/event is involved, do not invent an expression/event that
   did not happen. Prefer factual editorial context.
9. For cartoons/gaming, create original topic-inspired artwork rather than
   copying exact copyrighted screenshots/character art.
10. default_index must be 0, 1 or 2.
11. description_opening should be 1-2 natural sentences that accurately state
   the value of the video; no keyword stuffing.
12. ALL viewer-facing package text — title, thumbnail_text,
    description_opening, angle and promise_alignment — must be in the selected
    TARGET VIEWER LANGUAGE, except unavoidable proper nouns.
13. Do not translate a proper noun/title into a different identity.
14. Return only PackagingSet JSON.
"""

        print(
            f"[PERF] Packaging prompt chars={len(prompt)}"
        )

        packages = await self._llm.generate_structured(
            prompt,
            PackagingSet,
            system_prompt=(
                "Create accurate high-appeal YouTube packaging. "
                f"Write all viewer-facing package text in "
                f"{self._target_language_name(state)}. "
                "Optimize for watch-worthy expectations, not clickbait."
            ),
        )

        packages.default_index = max(
            0,
            min(
                2,
                packages.default_index,
            ),
        )

        clean_variants = []

        for index, variant in enumerate(
            packages.variants[:3]
        ):
            title = re.sub(
                r"\s+",
                " ",
                variant.title,
            ).strip()

            if not title:
                title = state.script.title

            # Hard cap prevents broken UI; don't silently create huge titles.
            if len(title) > 95:
                title = title[:92].rstrip(
                    " -:;,.!?"
                ) + "..."

            thumb_text = re.sub(
                r"\s+",
                " ",
                variant.thumbnail_text,
            ).strip()

            words = thumb_text.split()

            if len(words) > 4:
                thumb_text = " ".join(
                    words[:4]
                )

            if not self._title_grounded(
                title=title,
                state=state,
            ):
                title = self._safe_titles(
                    state
                )[index]

                print(
                    f"[PACKAGING] Rejected unsupported title angle; "
                    f"using safe evidence-grounded variant {index + 1}."
                )

            clean_variants.append(
                {
                    "label": (
                        variant.label.strip()
                        or chr(
                            ord("A") + index
                        )
                    ),
                    "angle": variant.angle.strip(),
                    "title": title,
                    "thumbnail_text": thumb_text,
                    "thumbnail_prompt": variant.thumbnail_prompt.strip(),
                    "promise_alignment": variant.promise_alignment.strip(),
                }
            )

        state.metadata["packaging"] = {
            "variants": clean_variants,
            "default_index": packages.default_index,
            "description_opening": packages.description_opening.strip(),
        }

        default_title = clean_variants[
            packages.default_index
        ]["title"]

        state.script.title = default_title

        print(
            "[PACKAGING] 3 A/B packages ready; "
            f"default={chr(ord('A') + packages.default_index)}"
        )

        for index, variant in enumerate(
            clean_variants
        ):
            print(
                f"[PACKAGING] {chr(ord('A') + index)} "
                f"title={variant['title']!r} "
                f"thumb_text={variant['thumbnail_text']!r}"
            )

        state.status = "packaging_optimized"
        return state

    @classmethod
    def _title_grounded(
        cls,
        *,
        title: str,
        state: WorkflowState,
    ) -> bool:
        corpus = (
            (state.topic or "")
            + " "
            + cls._evidence_context(
                state
            )
        ).lower()

        corpus_tokens = set(
            unicode_tokens(
                corpus,
                min_length=2,
            )
        )

        allowed_generic = {
            # English
            "what", "know", "knows", "latest", "update", "explained",
            "review", "inside", "today", "movie", "film", "story",
            "details", "current", "reports", "report", "really", "about",
            "does", "could", "would", "this", "that", "with", "from",
            "your", "into", "after", "before", "why", "how", "look",
            # Portuguese
            "que", "sabemos", "sobre", "últimos", "ultimos", "detalhes",
            "atuais", "relatos", "hoje", "entenda", "saiba", "agora",
            # Spanish
            "qué", "sabemos", "sobre", "últimos", "ultimos", "detalles",
            "actuales", "informes", "hoy", "ahora",
            # French
            "savons", "sur", "derniers", "détails", "details", "actuels",
            "rapports", "aujourd", "hui",
            # Indonesian
            "apa", "yang", "kita", "tahu", "tentang", "terbaru",
            "detail", "laporan", "hari", "ini",
            # Hindi / Bengali / Urdu / Arabic / Japanese
            "क्या", "जानते", "बारे", "ताज़ा", "ताजा", "विवरण", "रिपोर्ट",
            "आज", "কী", "জানি", "সম্পর্কে", "সর্বশেষ", "বিস্তারিত",
            "প্রতিবেদন", "আজ", "کیا", "جانتے", "بارے", "تازہ",
            "تفصیلات", "رپورٹس", "آج", "ماذا", "نعرف", "حول", "أحدث",
            "تفاصيل", "تقارير", "اليوم", "最新", "詳細", "現在", "知る",
        }

        candidate = [
            token
            for token in unicode_tokens(
                title.lower(),
                min_length=2,
            )
            if token not in allowed_generic
        ]

        novel = [
            token
            for token in candidate
            if token not in corpus_tokens
        ]

        return len(
            set(
                novel
            )
        ) <= 1

    @classmethod
    def _safe_titles(
        cls,
        state: WorkflowState,
    ) -> list[str]:
        topic = (
            state.topic
            or state.script.title
        ).strip()

        language = str(
            state.metadata.get(
                "target_language",
                "en",
            )
            or "en"
        ).lower()

        templates = {
            "en": (
                "{topic}: What Current Reports Say",
                "What We Know About {topic}",
                "{topic}: The Latest Confirmed Details",
            ),
            "hi": (
                "{topic}: अभी की रिपोर्ट क्या कहती हैं",
                "{topic} के बारे में अब तक क्या पता है",
                "{topic}: ताज़ा पुष्टि की गई जानकारी",
            ),
            "es": (
                "{topic}: Lo que dicen los informes actuales",
                "Lo que sabemos sobre {topic}",
                "{topic}: Los últimos detalles confirmados",
            ),
            "pt": (
                "{topic}: O que dizem os relatos atuais",
                "O que sabemos sobre {topic}",
                "{topic}: Os últimos detalhes confirmados",
            ),
            "id": (
                "{topic}: Apa kata laporan terbaru",
                "Yang kita ketahui tentang {topic}",
                "{topic}: Detail terbaru yang terkonfirmasi",
            ),
            "ja": (
                "{topic}：現在の報道で分かっていること",
                "{topic}について分かっていること",
                "{topic}：最新の確認済み情報",
            ),
            "ar": (
                "{topic}: ماذا تقول التقارير الحالية",
                "ما نعرفه عن {topic}",
                "{topic}: أحدث التفاصيل المؤكدة",
            ),
            "bn": (
                "{topic}: বর্তমান প্রতিবেদনে যা জানা যাচ্ছে",
                "{topic} সম্পর্কে আমরা যা জানি",
                "{topic}: সর্বশেষ নিশ্চিত তথ্য",
            ),
            "fr": (
                "{topic} : ce que disent les rapports actuels",
                "Ce que nous savons sur {topic}",
                "{topic} : les derniers détails confirmés",
            ),
            "ur": (
                "{topic}: موجودہ رپورٹس کیا کہتی ہیں",
                "{topic} کے بارے میں ہم کیا جانتے ہیں",
                "{topic}: تازہ ترین تصدیق شدہ تفصیلات",
            ),
        }

        selected = templates.get(
            language,
            templates["en"],
        )

        values = [
            template.format(
                topic=topic
            )
            for template in selected
        ]

        return [
            value[:92].rstrip(
                " -:;,.!?"
            )
            for value in values
        ]

    @staticmethod
    def _target_language_name(
        state: WorkflowState,
    ) -> str:
        name = str(
            state.metadata.get(
                "target_language_name",
                "",
            )
            or ""
        ).strip()

        if name:
            return name

        code = str(
            state.metadata.get(
                "target_language",
                "en",
            )
            or "en"
        ).lower()

        names = {
            "en": "English",
            "hi": "Hindi",
            "es": "Spanish",
            "pt": "Portuguese",
            "id": "Indonesian",
            "ja": "Japanese",
            "ar": "Arabic",
            "bn": "Bengali",
            "fr": "French",
            "ur": "Urdu",
            "de": "German",
            "vi": "Vietnamese",
            "tr": "Turkish",
            "ta": "Tamil",
            "te": "Telugu",
            "mr": "Marathi",
            "pa": "Punjabi",
            "gu": "Gujarati",
            "kn": "Kannada",
            "ml": "Malayalam",
            "ru": "Russian",
            "zh": "Chinese",
        }

        return names.get(
            code,
            "English",
        )

    @staticmethod
    def _evidence_context(
        state: WorkflowState,
    ) -> str:
        """
        Packaging needs topic identity + strongest packaging words, not full
        article descriptions. Keep a small high-signal evidence pack.
        """
        lines = []
        seen = set()

        for item in state.metadata.get(
            "enriched_evidence",
            [],
        )[:8]:
            title = re.sub(
                r"\s+",
                " ",
                str(
                    item.get(
                        "title"
                    )
                    or ""
                ),
            ).strip()

            if (
                title
                and title.lower()
                not in seen
            ):
                seen.add(
                    title.lower()
                )
                lines.append(
                    title[
                        :180
                    ]
                )

            if len(
                lines
            ) >= 6:
                break

        if state.research is not None:
            for item in (
                state.research.top_candidate.evidence[
                    :8
                ]
            ):
                title = re.sub(
                    r"\s+",
                    " ",
                    item.title,
                ).strip()

                if (
                    title
                    and title.lower()
                    not in seen
                ):
                    seen.add(
                        title.lower()
                    )
                    lines.append(
                        title[
                            :180
                        ]
                    )

                if len(
                    lines
                ) >= 9:
                    break

        grounding = state.metadata.get(
            "topic_grounding",
            {},
        )

        keywords = grounding.get(
            "top_keywords",
            [],
        )[
            :10
        ]

        if keywords:
            lines.append(
                "Grounding keywords: "
                + ", ".join(
                    str(
                        item
                    )
                    for item in keywords
                )
            )

        return "\n".join(
            lines
        )

    @staticmethod
    def _script_summary(
        state: WorkflowState,
    ) -> str:
        """
        Packaging only needs the promise, structure and payoff. Do not resend
        hundreds of words from every body section to Qwen.
        """
        script = state.script

        section_titles = ", ".join(
            section.title.strip()
            for section
            in script.sections[
                :8
            ]
            if section.title.strip()
        )

        return f"""
HOOK
{script.hook[:260]}

INTRO
{script.introduction[:320]}

SECTION TITLES
{section_titles}

CONCLUSION / PAYOFF
{script.conclusion[:320]}

CTA
{script.call_to_action[:180]}
"""

