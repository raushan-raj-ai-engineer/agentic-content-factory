from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from difflib import SequenceMatcher

from pydantic import BaseModel, Field, model_validator

from content_factory.cartoon.characters import (
    background_ids,
    character_registry,
    default_cast,
)
from content_factory.cartoon.language import (
    CartoonLanguagePack,
)
from content_factory.cartoon.models import (
    CartoonDialogueLine,
    CartoonEpisodePlan,
    CartoonReaction,
    CartoonScene,
    CartoonSceneBatch,
    CartoonSceneBrief,
)
from content_factory.cartoon.llm import (
    CartoonLLMProvider,
)
from content_factory.cartoon.router import resolve_story_profile
from content_factory.cartoon.channel_profiles import channel_prompt_block, channel_character_name
from content_factory.cartoon.quality_reset_v17 import (
    enforce_dialogue_budget,
    dialogue_word_count,
    apply_hindi_mass_location_policy,
)
from content_factory.cartoon.capabilities import enrich_plan
from content_factory.cartoon.scene_dynamics import apply_scene_dynamics
from content_factory.cartoon.characters import background_ids


class _V173CreativeLine(BaseModel):
    character_id: str
    text: str = Field(min_length=1, max_length=260)
    emotion: str = "neutral"

    @model_validator(mode="before")
    @classmethod
    def _v1712_normalize_line_shape(cls, value: object) -> object:
        """Accept harmless llama3.2 key drift without accepting weak content.

        Local creative calls sometimes return `speaker` instead of
        `character_id`, or `line`/`content` instead of `text`. The deterministic
        story planner already owns the allowed speakers, so normalizing these
        aliases is safer than discarding an otherwise usable scene.
        """
        if isinstance(value, str):
            return {"character_id": "", "text": value, "emotion": "neutral"}
        if not isinstance(value, dict):
            return value
        item = dict(value)
        if not str(item.get("character_id", "")).strip():
            for key in ("speaker", "speaker_id", "character", "name", "role"):
                candidate = item.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    item["character_id"] = candidate.strip()
                    break
        if not str(item.get("text", "")).strip():
            for key in ("line", "content", "utterance", "dialogue_text", "message"):
                candidate = item.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    item["text"] = candidate.strip()
                    break
        if not isinstance(item.get("emotion"), str) or not str(item.get("emotion", "")).strip():
            item["emotion"] = "neutral"
        return item


class _V173CreativeScene(BaseModel):
    id: int
    dialogue: list[_V173CreativeLine] = Field(min_length=4, max_length=8)
    reaction_character_id: str | None = None
    reaction_expression: str = "shocked"


class _V173CreativeBatch(BaseModel):
    scenes: list[_V173CreativeScene] = Field(min_length=1, max_length=2)



class _V18SpineBeat(BaseModel):
    """Compact causal beat used to keep independently generated scenes coherent."""

    trigger: str = Field(min_length=2, max_length=180)
    misunderstanding: str = Field(min_length=2, max_length=180)
    consequence: str = Field(min_length=2, max_length=180)
    button: str = Field(min_length=2, max_length=160)

    @model_validator(mode="before")
    @classmethod
    def _normalize_spine_beat(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        item = dict(value)
        aliases = {
            "trigger": ("instruction", "setup", "prompt", "action", "request"),
            "misunderstanding": ("mistake", "wrong_interpretation", "misread", "wrong_action"),
            "consequence": ("result", "visible_consequence", "payoff", "outcome"),
            "button": ("ending", "punchline", "callback", "end_button"),
        }
        for target, keys in aliases.items():
            if not str(item.get(target, "")).strip():
                for key in keys:
                    candidate = item.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        item[target] = candidate.strip()
                        break
        return item


class _V18EpisodeSpine(BaseModel):
    """Ordered scene beats; caller owns scene ids and locations."""

    beats: list[_V18SpineBeat] = Field(min_length=3, max_length=15)

    @model_validator(mode="before")
    @classmethod
    def _normalize_spine_wrapper(cls, value: object) -> object:
        if isinstance(value, list):
            return {"beats": value}
        if not isinstance(value, dict):
            return value
        item = dict(value)
        if not isinstance(item.get("beats"), list):
            for key in ("scenes", "story_beats", "arc", "steps"):
                candidate = item.get(key)
                if isinstance(candidate, list):
                    item["beats"] = candidate
                    break
        return item


class _V179SingleCreative(BaseModel):
    """V17.9 single-scene creative payload with no model-owned scene ID.

    llama3.2 sometimes keeps emitting the older {"scenes":[{"id":N,...}]}
    wrapper even when asked for one scene. Accept that legacy wrapper, ignore its ID,
    and let the deterministic caller own the real scene number. A slightly lenient
    3-10 turn parse boundary prevents good dialogue from being thrown away solely
    because the local model missed the preferred 6-8 turn count; public QA still
    enforces density and semantics afterwards.
    """

    # V17.12 parser boundary is deliberately more tolerant than public QA.
    # Parse 2-12 turns so schema/key drift is recoverable; final story QA still
    # requires at least 5 meaningful turns and semantic continuity before render.
    dialogue: list[_V173CreativeLine] = Field(min_length=2, max_length=12)
    reaction_character_id: str | None = None
    reaction_expression: str = "shocked"

    @model_validator(mode="before")
    @classmethod
    def _flatten_legacy_wrapper(cls, value: object) -> object:
        if isinstance(value, list):
            return {"dialogue": value}
        if not isinstance(value, dict):
            return value
        item = dict(value)
        # Accept alternate top-level names used by llama3.2 in otherwise valid JSON.
        if not isinstance(item.get("dialogue"), list):
            for key in ("lines", "turns", "messages", "conversation"):
                candidate = item.get(key)
                if isinstance(candidate, list):
                    item["dialogue"] = candidate
                    break
        if isinstance(item.get("dialogue"), list):
            return item
        # A single top-level line is still parseable; QA/repair decides whether
        # density is good enough, rather than the schema throwing it away.
        if isinstance(item.get("text"), str) and item.get("text", "").strip():
            return {"dialogue": [item, {"character_id": "", "text": "ठीक है, आगे बताइए।", "emotion": "neutral"}]}
        scene = item.get("scene")
        if isinstance(scene, dict):
            first = dict(scene)
            first.pop("id", None)
            return first
        scenes = item.get("scenes")
        if isinstance(scenes, list) and scenes and isinstance(scenes[0], dict):
            # Deliberately ignore the model-provided scene id. With batch_size=1
            # the caller already knows exactly which brief this dialogue belongs to.
            first = dict(scenes[0])
            first.pop("id", None)
            return first
        return item


class CartoonStoryPlanner:
    """
    V9.0.4 quality architecture.

    Keeps V9.0.3's low-compute design:
      - no LLM outline call
      - 9 story scenes for a 3-minute episode
      - 3 normal dialogue/acting calls

    Adds:
      - explicit unique scene progression
      - target duration budgeting
      - anti-repetition guard
      - conditional batch-only quality repair
      - deterministic reactions/emotions/camera movement
      - topic-aware role selection
    """

    BATCH_SIZE = 3

    @staticmethod
    def _compact_channel_direction(language_code: str) -> str:
        """V17.6 compact creative contract for batch generation.

        V15/V16's full director block is excellent reference material but was
        ~5k chars by itself. Repeating it inside every structured batch pushed
        qwen3:8b against the old 3072 context. Keep the same creative intent in
        a compact, execution-focused form.
        """
        if os.getenv("CONTENT_FACTORY_CARTOON_CHANNEL", "auto").strip().lower() == "hindi_mass":
            return (
                "HINDI MASS COMEDY V17.10: Write original, naturally spoken Hindi/Hinglish/Magahi/Bhojpuri "
                "exactly as requested. Open on an immediate visible problem, not an introduction. Preserve recurring "
                "personalities: Guddu quick-witted and active, Bittu confidently wrong, Babuji literal old-school "
                "authority, Mai practical deadpan. Build cause-and-effect comedy: concrete setup -> mistaken assumption "
                "or bad attempt -> reaction -> escalation -> reversal/callback -> payoff. Every scene must physically or "
                "socially change the situation. Use 6-8 short reciprocal turns and roughly 50-65 spoken words per ~20s "
                "scene. Put at least two laugh beats in a scene: one mid-scene reversal and one ending button. Rotate joke "
                "mechanisms instead of repeating 'arey/kya kar raha hai' reactions. Do not copy memes, creators, films or "
                "known punchlines. Do not explain the joke, preach a moral, or end with summary dialogue. Keep family-safe "
                "and monetization-friendly. If the premise uses an AI assistant, keep the AI as a phone/device instruction source; Guddu, Bittu, Mai or Babuji must not suddenly speak as if they are the AI. Each new scene should use a fresh household action or misunderstanding instead of recycling the same prop/phrase. Trends are optional premise inspiration only when they naturally fit the topic."
            )
        return channel_prompt_block(language_code)

    @staticmethod
    def _compact_premise_lock_for_prompt(premise_lock: dict[str, object]) -> dict[str, object]:
        # scene_lines and other route payloads are useful for deterministic fallback
        # but unnecessarily consume LLM context; scene briefs already carry the beat details.
        keep = (
            "key", "premise", "goal", "route", "audience", "tags", "pacing",
            "action_story", "capability_world", "explicit_locations", "locations",
            "persistent_props", "preferred_cast",
        )
        return {k: premise_lock[k] for k in keep if k in premise_lock}

    @staticmethod
    def _compact_rescue_prompt(
        *, topic: str, language: CartoonLanguagePack, compact_cast: list[dict[str, object]],
        briefs: list[CartoonSceneBrief], continuity: str, target_scene_seconds: float, is_final: bool,
    ) -> str:
        final = "End the last scene with a callback/payoff." if is_final else "Do not resolve the whole story yet."
        return f"""
V17.2 COMPACT RESCUE — return ONLY schema-valid JSON.
TOPIC: {topic}
LANGUAGE: {language.display_name}
CAST: {json.dumps(compact_cast, ensure_ascii=False)}
SCENES: {json.dumps([b.model_dump() for b in briefs], ensure_ascii=False)}
CONTINUITY: {(continuity or 'Opening batch')[-500:]}
RULES:
- Return exactly {len(briefs)} scenes and exact IDs/locations/character IDs.
- Preserve the topic and each scene brief; no unrelated subplot.
- Hindi mass: 6-8 natural turns and about 50-65 spoken words per ~{target_scene_seconds:.0f}s scene.
- Use setup -> reaction -> escalation -> payoff, character-specific banter, and no copied jokes.
- Keep JSON compact: short setup strings, no explanations outside the schema.
- {final}
"""

    _ALLOWED_SFX = {
        "boing",
        "pop",
        "whoosh",
        "impact",
        "awkward_pause",
        "footsteps",
        "door",
        "comic_sting",
        "monkey_chatter",
        "thali_clang",
    }

    def __init__(
        self,
        llm: CartoonLLMProvider,
    ) -> None:
        self._llm = llm
        self.last_report: dict[str, object] = {}

    async def create_plan(
        self,
        *,
        topic: str,
        language: CartoonLanguagePack,
        target_minutes: int = 3,
        cast: list[str] | None = None,
    ) -> CartoonEpisodePlan:
        """
        V9.0.6 story-lock + fail-safe rule:
        recoverable LLM output problems never abort episode-plan creation.
        """
        registry = character_registry()

        premise_lock = self._resolve_story_premise(
            topic=topic,
            language_code=language.code,
        )
        premise_lock = apply_hindi_mass_location_policy(topic, premise_lock)

        if cast is not None:
            cast_ids = list(cast)
        else:
            preferred_cast = [
                str(item)
                for item in premise_lock.get("preferred_cast", default_cast(limit=5))
            ]
            cast_ids = [item for item in preferred_cast if item in registry][:5]
            if len(cast_ids) < 2:
                cast_ids = default_cast(limit=5)

        unknown = [
            item
            for item in cast_ids
            if item not in registry
        ]

        if unknown:
            raise ValueError(
                "Unknown cartoon character(s): "
                + ", ".join(unknown)
            )

        scene_target = max(
            6,
            min(
                15,
                target_minutes * 3,
            ),
        )

        target_total_seconds = max(
            60,
            target_minutes * 60,
        )

        target_scene_seconds = min(
            20.0,
            max(
                10.0,
                target_total_seconds / scene_target,
            ),
        )

        compact_cast = [
            {
                "id": registry[item].id,
                "display_name": channel_character_name(registry[item].id, registry[item].display_name),
                "role": registry[item].role,
                "traits": list(
                    registry[item].personality[:2]
                ),
            }
            for item in cast_ids
        ]

        briefs = self._build_scene_briefs(
            topic=topic,
            cast_ids=cast_ids,
            scene_target=scene_target,
            premise_lock=premise_lock,
        )

        hindi_mass = os.getenv("CONTENT_FACTORY_CARTOON_CHANNEL", "auto").strip().lower() == "hindi_mass"
        # V17.3: two scenes per local-LLM call for Hindi mass. The old 3-scene
        # production-schema call was too expensive for qwen3:8b on laptop Ollama.
        # V17.7: one compact scene per call is materially more reliable on
        # llama3.2-class local models (especially 8GB Apple Silicon) than asking
        # for two 6-8 turn scenes in one strict JSON response. Quality wins over
        # shaving a few local calls; transport failures remain bounded.
        creative_batch_size = 1 if hindi_mass else self.BATCH_SIZE
        batches = [
            briefs[index:index + creative_batch_size]
            for index in range(0, len(briefs), creative_batch_size)
        ]

        self.last_report = {
            "version": "9.5.1",
            "mode": "fail_safe",
            "normal_llm_batch_attempts": len(batches),
            "llm_batch_failures": 0,
            "llm_batch_rescue_calls": 0,
            "reconciled_batches": 0,
            "dropped_extra_scenes": 0,
            "fallback_scenes": 0,
            "quality_local_repairs": 0,
            "llm_quality_repair_calls": 0,
            "final_targeted_repair_calls": 0,
            "final_targeted_repair_accepts": 0,
            "warnings": [],
            "premise_key": premise_lock["key"],
            "premise": premise_lock["premise"],
            "premise_goal": premise_lock["goal"],
            "continuity_semantic_repairs": 0,
            "route": premise_lock.get("route", "general_comedy"),
            "audience": premise_lock.get("audience", "all"),
            "story_tags": premise_lock.get("tags", []),
            "pacing": premise_lock.get("pacing", "balanced"),
        }

        print(
            "[CARTOON V9.2] "
            f"Story lock={premise_lock['key']!r}; "
            f"goal={premise_lock['goal']!r}."
        )
        print(
            "[CARTOON V9.2] "
            f"Fail-safe skeleton: {scene_target} scenes; "
            f"{len(batches)} LLM batch attempt(s); "
            "LLM quality-repair calls=0."
        )
        print(
            "[CARTOON V9] "
            f"Story duration budget: ~{target_total_seconds}s total, "
            f"~{target_scene_seconds:.1f}s per story scene."
        )

        scenes: list[CartoonScene] = []
        continuity = ""
        recent_lines: list[str] = []

        llm_fast_ready = True
        if hindi_mass:
            llm_fast_ready = await self._llm.fast_preflight()
            print(
                "[CARTOON LLM V17.3] "
                f"preflight={'PASS' if llm_fast_ready else 'FAIL'}; "
                "mode=CAUSAL_SPINE_SINGLE_SCENE_V18; batch_size=1; scene_id_owner=CALLER; per_batch_repairs=OFF; final_targeted_repairs=BOUNDED; fast_ctx=3072"
            )
            if not llm_fast_ready:
                self.last_report["warnings"].append(
                    "V17.3 local Ollama preflight failed; skipping repeated slow calls and using deterministic recovery."
                )

        episode_spine: list[dict[str, str]] = []
        if hindi_mass:
            episode_spine = await self._v18_build_episode_spine(
                topic=topic,
                language=language,
                briefs=briefs,
                llm_fast_ready=llm_fast_ready,
            )
            self.last_report["episode_spine_status"] = (
                "generated" if episode_spine else "brief_fallback"
            )
            self.last_report["episode_spine_beats"] = len(episode_spine)

        for batch_number, batch_briefs in enumerate(
            batches,
            start=1,
        ):
            started = time.perf_counter()

            if hindi_mass:
                prompt = self._v173_creative_prompt(
                    topic=topic,
                    language=language,
                    compact_cast=compact_cast,
                    briefs=batch_briefs,
                    continuity=continuity,
                    recent_lines=recent_lines,
                    target_scene_seconds=target_scene_seconds,
                    is_final=(batch_number == len(batches)),
                    spine_beat=(
                        episode_spine[int(batch_briefs[0].id) - 1]
                        if 0 < int(batch_briefs[0].id) <= len(episode_spine)
                        else None
                    ),
                    episode_spine=episode_spine,
                )
                print(
                    "[CARTOON V17.3] "
                    f"Generating creative batch {batch_number}/{len(batches)} "
                    f"(scenes {batch_briefs[0].id}-{batch_briefs[-1].id}, "
                    f"prompt={len(prompt)} chars, schema=SINGLE_SCENE_NO_ID)..."
                )
                raw_batch = None
                if llm_fast_ready:
                    try:
                        creative = await self._llm.generate_fast_structured(
                            prompt=prompt,
                            response_model=_V179SingleCreative,
                            system_prompt=(
                                f"You are an original Indian comedy dialogue writer. Write natural {language.display_name} "
                                "banter only. Return JSON only; no explanation."
                            ),
                            rescue=False,
                        )
                        raw_batch = self._v179_expand_single_creative(
                            creative=creative, brief=batch_briefs[0], language=language,
                            topic=topic, target_scene_seconds=target_scene_seconds,
                        )
                        print(
                            "[CARTOON LLM V17.3] "
                            f"batch={batch_number}; compact_primary=SUCCESS"
                        )
                    except Exception as exc:
                        print(
                            "[CARTOON LLM V17.3] "
                            f"batch={batch_number}; compact_primary=FAIL; error={type(exc).__name__}; "
                            f"reason={str(exc)[:180]!r}; bounded_rescue=YES"
                        )
                        # Exactly one bounded rescue. Never repeat 600-second calls.
                        try:
                            rescue_prompt = self._v173_creative_rescue_prompt(
                                topic=topic, language=language, compact_cast=compact_cast,
                                briefs=batch_briefs, continuity=continuity,
                                is_final=(batch_number == len(batches)),
                                spine_beat=(
                                    episode_spine[int(batch_briefs[0].id) - 1]
                                    if 0 < int(batch_briefs[0].id) <= len(episode_spine)
                                    else None
                                ),
                            )
                            creative = await self._llm.generate_fast_structured(
                                prompt=rescue_prompt,
                                response_model=_V179SingleCreative,
                                system_prompt=f"Return compact valid JSON with natural {language.display_name} dialogue only.",
                                rescue=True,
                            )
                            raw_batch = self._v179_expand_single_creative(
                                creative=creative, brief=batch_briefs[0], language=language,
                                topic=topic, target_scene_seconds=target_scene_seconds,
                            )
                            print(
                                "[CARTOON LLM V17.3] "
                                f"batch={batch_number}; bounded_rescue=SUCCESS"
                            )
                        except Exception as rescue_exc:
                            self.last_report["llm_batch_failures"] = int(self.last_report["llm_batch_failures"]) + 1
                            self.last_report["warnings"].append(
                                f"batch {batch_number}: V17.3 compact primary+rescue failed: "
                                f"{type(rescue_exc).__name__}: {str(rescue_exc)[:160]}"
                            )
                            # V17.7: schema/validation failure proves the model is
                            # reachable; it must NOT trip the transport circuit breaker.
                            # Otherwise one imperfect JSON response disables every later
                            # creative batch and guarantees a generic episode. Only a
                            # transport/runtime failure on the rescue call disables later
                            # calls.
                            validation_only = isinstance(rescue_exc, ValueError)
                            print(
                                "[CARTOON RECOVERY V17.7] "
                                f"batch={batch_number}; compact_primary+rescue=FAIL; "
                                f"validation_only={'YES' if validation_only else 'NO'}; "
                                f"later_batches={'KEEP_LLM' if validation_only else 'DISABLE_LLM'}; "
                                "local_recovery=YES"
                            )
                            if not validation_only:
                                llm_fast_ready = False
            else:
                prompt = self._batch_prompt(
                    topic=topic, language=language, compact_cast=compact_cast,
                    briefs=batch_briefs, continuity=continuity, recent_lines=recent_lines,
                    target_scene_seconds=target_scene_seconds,
                    is_final=(batch_number == len(batches)),
                )
                print(
                    "[CARTOON V9] "
                    f"Generating batch {batch_number}/{len(batches)} "
                    f"(scenes {batch_briefs[0].id}-{batch_briefs[-1].id}, prompt={len(prompt)} chars)..."
                )
                raw_batch = None
                try:
                    raw_batch = await self._llm.generate_structured(
                        prompt=prompt, response_model=CartoonSceneBatch,
                        system_prompt=(
                            f"Write original, performance-ready, native-feeling {language.display_name} cartoon dialogue. "
                            "Honor the exact scene briefs. Return only structured JSON."
                        ),
                        max_retries=1,
                    )
                except Exception as exc:
                    self.last_report["llm_batch_failures"] = int(self.last_report["llm_batch_failures"]) + 1
                    self.last_report["warnings"].append(
                        f"batch {batch_number}: {type(exc).__name__}: {str(exc)[:160]}"
                    )
                    print(
                        "[CARTOON RECOVERY] "
                        f"Batch {batch_number} LLM failed; using local recovery."
                    )

            batch, stats = self._reconcile_batch_to_briefs(
                raw_batch=raw_batch,
                briefs=batch_briefs,
                cast_ids=cast_ids,
                language=language,
                topic=topic,
                target_scene_seconds=target_scene_seconds,
            )

            if stats["reconciled"]:
                self.last_report["reconciled_batches"] = int(
                    self.last_report["reconciled_batches"]
                ) + 1

            self.last_report["dropped_extra_scenes"] = int(
                self.last_report["dropped_extra_scenes"]
            ) + int(stats["dropped_extra_scenes"])

            self.last_report["fallback_scenes"] = int(
                self.last_report["fallback_scenes"]
            ) + int(stats["fallback_scenes"])

            issues = self._quality_issues(
                batch=batch,
                recent_lines=recent_lines,
                language=language,
                topic=topic,
            )

            # V17.1: protect the LLM's real dialogue from being replaced by
            # generic local fallback. Only ask the LLM for one focused rewrite
            # when a Hindi comedy batch is genuinely under-filled.
            hindi_mass = os.getenv("CONTENT_FACTORY_CARTOON_CHANNEL", "auto").strip().lower() == "hindi_mass"
            density_issues: list[str] = []
            if hindi_mass:
                for _scene in batch.scenes:
                    _wc = dialogue_word_count([_scene])
                    if len(_scene.dialogue) < 5 or _wc < 45:
                        density_issues.append(
                            f"scene {_scene.id} underfilled Hindi comedy dialogue: "
                            f"turns={len(_scene.dialogue)}, words={_wc}"
                        )
                issues.extend(density_issues)

            # V17.6: Hindi mass previously detected weak batches but never
            # performed a fast rewrite because the old repair branch explicitly
            # excluded hindi_mass. Use at most one bounded compact repair call.
            fast_repair_issues = [
                issue for issue in issues
                if any(token in issue for token in (
                    "fewer than 5 Hindi comedy turns",
                    "underfilled Hindi comedy dialogue",
                    "repeated/near-duplicate dialogue",
                    "speaker run",
                    "single-speaker",
                    "expositional long lines",
                    "premise dialogue anchor",
                    "topic-named protagonist",
                    "mostly Romanized",
                    "repeated phrase loop",
                    "off-premise drift",
                    "premise anchor",
                    "AI-assistant instruction source",
                    "Babuji too little agency",
                ))
            ]
            # V18 architecture: do not spend an LLM repair call immediately
            # after each independently generated scene. Build all scenes first,
            # evaluate the complete causal arc, then repair only final weak scenes.
            if (
                hindi_mass
                and llm_fast_ready
                and fast_repair_issues
                and os.getenv("CONTENT_FACTORY_V18_BATCH_REPAIR", "0").strip() == "1"
            ):
                before_issues = (
                    len(self._v176_hindi_comedy_issues(batch=batch))
                    + len(self._v178_semantic_issues(batch=batch, language=language, topic=topic))
                    + len(self._v1710_ai_home_issues(batch=batch, topic=topic))
                )
                before_words = dialogue_word_count(batch.scenes)
                try:
                    repair_prompt = self._v176_fast_repair_prompt(
                        topic=topic,
                        language=language,
                        briefs=batch_briefs,
                        current_batch=batch,
                        issues=fast_repair_issues,
                        continuity=continuity,
                        is_final=(batch_number == len(batches)),
                    )
                    try:
                        creative = await self._llm.generate_fast_structured(
                            prompt=repair_prompt,
                            response_model=_V179SingleCreative,
                            system_prompt=(
                                f"Rewrite weak {language.display_name} cartoon dialogue as concise original situational comedy. "
                                "Return compact JSON only."
                            ),
                            rescue=False,
                        )
                    except ValueError as primary_exc:
                        print(
                            "[CARTOON STORY REPAIR V18] "
                            f"batch={batch_number}; primary=FAIL_VALIDATION; "
                            f"reason={str(primary_exc)[:160]!r}; bounded_rescue=YES"
                        )
                        creative = await self._llm.generate_fast_structured(
                            prompt=self._v1711_compact_repair_rescue_prompt(
                                topic=topic,
                                language=language,
                                brief=batch_briefs[0],
                                reasons=fast_repair_issues,
                            ),
                            response_model=_V179SingleCreative,
                            system_prompt=(
                                f"Return only short valid JSON for one {language.display_name} comedy scene."
                            ),
                            rescue=True,
                        )
                    candidate = self._v179_expand_single_creative(
                        creative=creative,
                        brief=batch_briefs[0],
                        language=language,
                        topic=topic,
                        target_scene_seconds=target_scene_seconds,
                    )
                    candidate, _candidate_stats = self._reconcile_batch_to_briefs(
                        raw_batch=candidate,
                        briefs=batch_briefs,
                        cast_ids=cast_ids,
                        language=language,
                        topic=topic,
                        target_scene_seconds=target_scene_seconds,
                    )
                    after_issues = (
                        len(self._v176_hindi_comedy_issues(batch=candidate))
                        + len(self._v178_semantic_issues(batch=candidate, language=language, topic=topic))
                        + len(self._v1710_ai_home_issues(batch=candidate, topic=topic))
                    )
                    after_words = dialogue_word_count(candidate.scenes)
                    # V17.12: never accept a "repair" that wins the issue
                    # counter by deleting most of the scene. For an already
                    # substantial scene retain at least 70% of its words and
                    # stay above the public 45-word floor. Very short scenes may
                    # grow freely, but still must reach the floor.
                    retention_floor = max(45, int(round(before_words * 0.70)))
                    content_retained = after_words >= retention_floor
                    quality_improved = after_issues < before_issues
                    if quality_improved and content_retained:
                        batch = candidate
                        self.last_report["llm_quality_repair_calls"] = int(
                            self.last_report["llm_quality_repair_calls"]
                        ) + 1
                        issues = self._quality_issues(
                            batch=batch, recent_lines=recent_lines, language=language, topic=topic
                        )
                        print(
                            "[CARTOON STORY V18] "
                            f"batch={batch_number}; fast_comedy_repair=ACCEPTED; "
                            f"issues={before_issues}->{after_issues}; words={before_words}->{after_words}; floor={retention_floor}"
                        )
                    else:
                        print(
                            "[CARTOON STORY V18] "
                            f"batch={batch_number}; fast_comedy_repair=REJECTED; "
                            f"issues={before_issues}->{after_issues}; words={before_words}->{after_words}; floor={retention_floor}"
                        )
                except Exception as exc:
                    self.last_report["warnings"].append(
                        f"V17.6 fast comedy repair skipped: {type(exc).__name__}: {str(exc)[:180]}"
                    )

            if density_issues and not hindi_mass:
                before_words = dialogue_word_count(batch.scenes)
                try:
                    repair_prompt = self._repair_prompt(
                        topic=topic,
                        language=language,
                        compact_cast=compact_cast,
                        briefs=batch_briefs,
                        continuity=continuity,
                        recent_lines=recent_lines,
                        current_batch=batch,
                        issues=issues,
                        target_scene_seconds=target_scene_seconds,
                        is_final=(batch_number == len(batches)),
                    )
                    repaired_raw = await self._llm.generate_structured(
                        prompt=repair_prompt,
                        response_model=CartoonSceneBatch,
                        system_prompt=(
                            f"Rewrite this batch as original, entertaining, performance-ready "
                            f"{language.display_name} comedy. Preserve exact IDs/locations. "
                            "Use character-specific banter, interruptions, reactions and callbacks; "
                            "do not add filler."
                        ),
                        max_retries=0,
                    )
                    repaired_batch, _repair_stats = self._reconcile_batch_to_briefs(
                        raw_batch=repaired_raw,
                        briefs=batch_briefs,
                        cast_ids=cast_ids,
                        language=language,
                        topic=topic,
                        target_scene_seconds=target_scene_seconds,
                    )
                    after_words = dialogue_word_count(repaired_batch.scenes)
                    if after_words > before_words:
                        batch = repaired_batch
                        self.last_report["llm_quality_repair_calls"] = int(
                            self.last_report["llm_quality_repair_calls"]
                        ) + 1
                        print(
                            "[CARTOON QUALITY V17.1] "
                            f"Batch {batch_number}: LLM density repair accepted; "
                            f"words={before_words}->{after_words}."
                        )
                        issues = self._quality_issues(
                            batch=batch, recent_lines=recent_lines, language=language, topic=topic
                        )
                    else:
                        print(
                            "[CARTOON QUALITY V17.1] "
                            f"Batch {batch_number}: LLM density repair rejected "
                            f"because it did not improve spoken-word coverage."
                        )
                except Exception as exc:
                    self.last_report["warnings"].append(
                        f"V17.1 density repair skipped: {type(exc).__name__}: {str(exc)[:180]}"
                    )

            semantic_issue_ids = {
                int(match.group(1))
                for issue in issues
                if (
                    "premise anchor" in issue
                    or "off-premise drift" in issue
                )
                for match in [
                    re.search(
                        r"scene\s+(\d+)",
                        issue,
                        flags=re.IGNORECASE,
                    )
                ]
                if match
            }

            repaired = self._repair_quality_locally(
                batch=batch,
                briefs=batch_briefs,
                language=language,
                topic=topic,
                issues=issues,
                target_scene_seconds=target_scene_seconds,
            )

            self.last_report["continuity_semantic_repairs"] = int(
                self.last_report["continuity_semantic_repairs"]
            ) + len(semantic_issue_ids)

            if repaired:
                self.last_report["quality_local_repairs"] = int(
                    self.last_report["quality_local_repairs"]
                ) + repaired

                print(
                    "[CARTOON QUALITY] "
                    f"Batch {batch_number}: local dialogue repairs={repaired}; "
                    "no extra LLM call."
                )

            self._apply_performance_direction(
                batch=batch,
                briefs=batch_briefs,
                target_scene_seconds=target_scene_seconds,
            )
            self._apply_route_sfx(batch=batch, premise_lock=premise_lock)

            self._enforce_brief_contract(
                batch=batch,
                briefs=batch_briefs,
            )

            scenes.extend(batch.scenes)

            continuity = self._continuity_tail(batch)

            recent_lines.extend(
                line.text.strip()
                for scene in batch.scenes
                for line in scene.dialogue
                if line.text.strip()
            )
            recent_lines = recent_lines[-12:]

            print(
                "[CARTOON V9] "
                f"Batch {batch_number}/{len(batches)} "
                f"complete in {time.perf_counter() - started:.1f}s."
            )

        scenes = self._finalize_episode_scenes(
            scenes=scenes,
            briefs=briefs,
            language=language,
            topic=topic,
            target_scene_seconds=target_scene_seconds,
        )

        scenes, v17_budget = enforce_dialogue_budget(
            scenes=scenes,
            target_minutes=target_minutes,
            language_code=language.code,
            cast_ids=cast_ids,
        )
        if v17_budget.get("enabled"):
            print(
                "[CARTOON DURATION V17] "
                f"requested={target_total_seconds}s; "
                f"words_before={v17_budget.get('before', 0)}; "
                f"words_after={v17_budget.get('after', 0)}; "
                f"min_words={v17_budget.get('min_words', 0)}; "
                f"expanded_lines={v17_budget.get('expanded_lines', 0)}"
            )

        visual_by_scene = premise_lock.get("visual_by_scene", {})
        visual_actions = premise_lock.get("visual_actions", {})
        props_by_scene = premise_lock.get("props_by_scene", {})
        for scene in scenes:
            values = visual_by_scene.get(str(scene.id), []) if isinstance(visual_by_scene, dict) else []
            scene.visual_characters = [str(item) for item in values if str(item) in registry][:5]
            if isinstance(visual_actions, dict):
                scene.visual_action = str(
                    visual_actions.get(str(scene.id), scene.visual_action)
                )
            if isinstance(props_by_scene, dict):
                props = props_by_scene.get(str(scene.id), [])
                if isinstance(props, list):
                    merged_props = list(scene.props)
                    for item in props:
                        value = str(item)
                        if value not in merged_props:
                            merged_props.append(value)
                    scene.props = merged_props[:6]

        plan = CartoonEpisodePlan(
            title=self._bounded_scene_text(
                topic, max_chars=120, fallback="Cartoon episode"
            ),
            topic=topic.strip(),
            language_code=language.code,
            language_name=language.display_name,
            genre=str(premise_lock.get("route","general_comedy")),
            route=str(premise_lock.get("route","general_comedy")),
            audience=str(premise_lock.get("audience","all")),
            story_tags=[str(x) for x in premise_lock.get("tags",[])][:12],
            premise=self._bounded_scene_text(
                premise_lock.get("premise", topic),
                max_chars=800,
                fallback=topic.strip() or "Requested cartoon premise",
            ),
            characters=list(cast_ids),
            scenes=scenes,
            ending_callback=(
                "Return to the opening conflict with a final comic reversal."
            ),
        )

        # V17.12 tolerant repair parsing + content-retention guard. Recompute targets after
        # every attempt so later weak scenes are not starved by a frozen top-4
        # list. Primary fast mode gets the same output budget that already
        # succeeds for normal scene generation; compact rescue is used only
        # after validation failure.
        if hindi_mass and llm_fast_ready:
            brief_by_id = {int(item.id): item for item in briefs}
            # V17.12: allow a second chance when a scene fails validation or an
            # accepted partial repair still leaves it weak. Keep the total call
            # budget at six so an 8GB local Mac is not punished with an
            # unbounded repair loop. First attempts are distributed across weak
            # scenes before second attempts.
            targeted_attempts: dict[int, int] = {}
            max_targeted_calls = min(4, max(1, len(plan.scenes)))
            for _targeted_index in range(max_targeted_calls):
                current_weak = self.v178_plan_weak_reasons(plan=plan, language=language)
                candidates = [
                    sid for sid in sorted(
                        current_weak,
                        key=lambda sid: (targeted_attempts.get(int(sid), 0), -len(current_weak[sid]), sid),
                    )
                    if targeted_attempts.get(int(sid), 0) < 2
                ]
                if not candidates:
                    break
                scene_id = int(candidates[0])
                targeted_attempts[scene_id] = targeted_attempts.get(scene_id, 0) + 1
                reasons = list(current_weak.get(scene_id, []))
                brief = brief_by_id.get(scene_id)
                current_index = next(
                    (i for i, item in enumerate(plan.scenes) if int(item.id) == scene_id),
                    None,
                )
                if not reasons or brief is None or current_index is None:
                    continue
                current_scene = plan.scenes[current_index]
                previous_scene = plan.scenes[current_index - 1] if current_index > 0 else None
                next_scene = plan.scenes[current_index + 1] if current_index + 1 < len(plan.scenes) else None
                prompt = self._v1710_targeted_repair_prompt(
                    topic=topic,
                    language=language,
                    brief=brief,
                    current_scene=current_scene,
                    reasons=reasons,
                    previous_scene=previous_scene,
                    next_scene=next_scene,
                    spine_beat=(
                        episode_spine[scene_id - 1]
                        if 0 < scene_id <= len(episode_spine)
                        else None
                    ),
                )
                self.last_report["final_targeted_repair_calls"] = int(
                    self.last_report.get("final_targeted_repair_calls", 0)
                ) + 1
                try:
                    try:
                        creative = await self._llm.generate_fast_structured(
                            prompt=prompt,
                            response_model=_V179SingleCreative,
                            system_prompt=(
                                f"Rewrite one weak {language.display_name} comedy scene. "
                                "Return only valid compact JSON with a dialogue array."
                            ),
                            rescue=False,
                        )
                        print(
                            "[CARTOON STORY REPAIR V18] "
                            f"scene={scene_id}; primary=SUCCESS"
                        )
                    except ValueError as primary_exc:
                        print(
                            "[CARTOON STORY REPAIR V18] "
                            f"scene={scene_id}; primary=FAIL_VALIDATION; "
                            f"reason={str(primary_exc)[:180]!r}; bounded_rescue=YES"
                        )
                        creative = await self._llm.generate_fast_structured(
                            prompt=self._v1711_compact_targeted_rescue_prompt(
                                topic=topic,
                                language=language,
                                brief=brief,
                                current_scene=current_scene,
                                reasons=reasons,
                            ),
                            response_model=_V179SingleCreative,
                            system_prompt=(
                                f"Return only short valid JSON for one {language.display_name} comedy scene."
                            ),
                            rescue=True,
                        )
                        print(
                            "[CARTOON STORY REPAIR V18] "
                            f"scene={scene_id}; bounded_rescue=SUCCESS"
                        )

                    candidate_batch = self._v179_expand_single_creative(
                        creative=creative,
                        brief=brief,
                        language=language,
                        topic=topic,
                        target_scene_seconds=target_scene_seconds,
                    )
                    candidate_scene = candidate_batch.scenes[0]
                    candidate_scenes = list(plan.scenes)
                    candidate_scenes[current_index] = candidate_scene
                    candidate_plan = plan.model_copy(update={"scenes": candidate_scenes})
                    after_map = self.v178_plan_weak_reasons(
                        plan=candidate_plan,
                        language=language,
                    )
                    before_scene_count = len(reasons)
                    after_scene_count = len(after_map.get(scene_id, []))
                    global_before = sum(len(v) for v in current_weak.values())
                    global_after = sum(len(v) for v in after_map.values())
                    candidate_words = dialogue_word_count([candidate_scene])
                    candidate_turns = len(candidate_scene.dialogue)
                    before_core = self._v18_core_semantic_reasons(reasons)
                    after_scene_reasons = list(after_map.get(scene_id, []))
                    after_core = self._v18_core_semantic_reasons(after_scene_reasons)
                    core_resolved = not after_core
                    accepted = (
                        after_scene_count < before_scene_count
                        and global_after <= global_before
                        and candidate_turns >= 5
                        and candidate_words >= 45
                        and core_resolved
                    )
                    if accepted:
                        plan = candidate_plan
                        self.last_report["llm_quality_repair_calls"] = int(
                            self.last_report["llm_quality_repair_calls"]
                        ) + 1
                        self.last_report["final_targeted_repair_accepts"] = int(
                            self.last_report.get("final_targeted_repair_accepts", 0)
                        ) + 1
                    print(
                        "[CARTOON STORY REPAIR V18] "
                        f"scene={scene_id}; status={'ACCEPTED' if accepted else 'REJECTED'}; "
                        f"reasons={before_scene_count}->{after_scene_count}; "
                        f"global={global_before}->{global_after}; "
                        f"core={len(before_core)}->{len(after_core)}; "
                        f"turns={candidate_turns}; words={candidate_words}"
                    )
                except Exception as exc:
                    self.last_report["warnings"].append(
                        f"V17.12 targeted repair scene {scene_id} skipped: "
                        f"{type(exc).__name__}: {str(exc)[:240]}"
                    )
                    print(
                        "[CARTOON STORY REPAIR V18] "
                        f"scene={scene_id}; status=FAILED; error={type(exc).__name__}; "
                        f"reason={str(exc)[:220]!r}"
                    )

        planned_seconds = sum(
            scene.shot_duration_seconds
            for scene in plan.scenes
        )

        self.last_report["final_scene_count"] = len(plan.scenes)
        self.last_report["planned_story_seconds"] = planned_seconds
        self.last_report["degraded"] = bool(
            self.last_report["llm_batch_failures"]
            or self.last_report["fallback_scenes"]
            or self.last_report["quality_local_repairs"]
            or self.last_report["dropped_extra_scenes"]
        )

        if os.getenv("CONTENT_FACTORY_CARTOON_CHANNEL", "auto").strip().lower() == "hindi_mass":
            weak_reasons = self.v178_plan_weak_reasons(
                plan=plan,
                language=language,
            )
            weak_scene_ids = sorted(weak_reasons)
            story_status = (
                "PASS"
                if not weak_scene_ids and int(self.last_report["fallback_scenes"]) <= 1
                else "REVIEW_REQUIRED"
            )
            self.last_report["story_quality_status"] = story_status
            self.last_report["weak_story_scene_ids"] = weak_scene_ids
            self.last_report["weak_story_reasons"] = {
                str(scene_id): reasons
                for scene_id, reasons in weak_reasons.items()
            }
            print(
                "[CARTOON STORY QA V18] "
                f"status={story_status}; weak_scenes={weak_scene_ids or 'none'}; "
                f"fallback_scenes={self.last_report['fallback_scenes']}; "
                f"fast_quality_repairs={self.last_report['llm_quality_repair_calls']}; "
                f"targeted_calls={self.last_report.get('final_targeted_repair_calls', 0)}; "
                f"targeted_accepts={self.last_report.get('final_targeted_repair_accepts', 0)}; "
                f"spine={self.last_report.get('episode_spine_status', 'n/a')}"
            )
            if weak_reasons:
                compact_reasons = {
                    scene_id: reasons[:2]
                    for scene_id, reasons in weak_reasons.items()
                }
                print(
                    "[CARTOON STORY QA V18] "
                    f"reasons={compact_reasons}"
                )

        print(
            "[CARTOON RECOVERY] "
            f"final_scenes={len(plan.scenes)}, "
            f"fallback_scenes={self.last_report['fallback_scenes']}, "
            f"dropped_extra={self.last_report['dropped_extra_scenes']}, "
            f"llm_failures={self.last_report['llm_batch_failures']}."
        )
        print(
            "[CARTOON QUALITY] "
            f"local_repairs={self.last_report['quality_local_repairs']}; "
            f"planned story duration={planned_seconds:.0f}s."
        )

        plan, coverage = enrich_plan(
            plan,
            known_backgrounds=set(background_ids()),
        )
        self.last_report["capability_coverage"] = coverage
        dynamics = apply_scene_dynamics(plan)
        self.last_report["scene_dynamics"] = dynamics
        print(
            "[CARTOON SCENE DYNAMICS V11.2] "
            f"locations={dynamics['distinct_locations']}; "
            f"changes={dynamics['location_changes']}; "
            f"motions={dynamics['environment_motions']}; "
            "topic_agnostic=YES; extra_llm_calls=0."
        )
        print(
            "[CARTOON COVERAGE V11.1] "
            f"worlds={coverage['worlds']}; "
            f"mean={coverage['mean_coverage_score']:.3f}; "
            f"min={coverage['min_coverage_score']:.3f}; "
            f"full={coverage['full_scenes']}; "
            f"partial={coverage['partial_scenes']}; "
            f"fallback={coverage['fallback_scenes']}; "
            f"readiness={coverage['production_readiness']}; "
            "retraining_required=NO; extra_llm_calls=0."
        )
        print(
            "[CARTOON BENCHMARK V11.1] "
            "scene_multi_world=ON; compositional_actions=ON; "
            "monetization_gate=ON; quality_reduction=NO."
        )

        return plan

    @classmethod
    def create_fallback_plan(
        cls,
        *,
        topic: str,
        language: CartoonLanguagePack,
        target_minutes: int,
        cast: list[str],
    ) -> CartoonEpisodePlan:
        """
        Emergency whole-episode fallback requiring no LLM.
        """
        scene_target = max(
            6,
            min(
                15,
                target_minutes * 3,
            ),
        )

        target_total_seconds = max(
            60,
            target_minutes * 60,
        )

        target_scene_seconds = min(
            20.0,
            max(
                10.0,
                target_total_seconds / scene_target,
            ),
        )

        premise_lock = cls._resolve_story_premise(
            topic=topic,
            language_code=language.code,
        )
        premise_lock = apply_hindi_mass_location_policy(topic, premise_lock)

        briefs = cls._build_scene_briefs(
            topic=topic,
            cast_ids=cast,
            scene_target=scene_target,
            premise_lock=premise_lock,
        )

        scenes = [
            cls._fallback_scene_from_brief(
                brief=brief,
                language=language,
                topic=topic,
                target_scene_seconds=target_scene_seconds,
                variant=index,
            )
            for index, brief in enumerate(briefs)
        ]

        visual_by_scene = premise_lock.get("visual_by_scene", {})
        visual_actions = premise_lock.get("visual_actions", {})
        props_by_scene = premise_lock.get("props_by_scene", {})
        for scene in scenes:
            values = visual_by_scene.get(str(scene.id), []) if isinstance(visual_by_scene, dict) else []
            scene.visual_characters = [str(item) for item in values][:5]
            if isinstance(visual_actions, dict):
                scene.visual_action = str(
                    visual_actions.get(str(scene.id), scene.visual_action)
                )
            if isinstance(props_by_scene, dict):
                props = props_by_scene.get(str(scene.id), [])
                if isinstance(props, list):
                    merged_props = list(scene.props)
                    for item in props:
                        value = str(item)
                        if value not in merged_props:
                            merged_props.append(value)
                    scene.props = merged_props[:6]

        plan = CartoonEpisodePlan(
            title=cls._bounded_scene_text(
                topic, max_chars=120, fallback="Cartoon episode"
            ),
            topic=topic.strip(),
            language_code=language.code,
            language_name=language.display_name,
            genre=str(premise_lock.get("route","general_comedy")),
            route=str(premise_lock.get("route","general_comedy")),
            audience=str(premise_lock.get("audience","all")),
            story_tags=[str(x) for x in premise_lock.get("tags",[])][:12],
            premise=cls._bounded_scene_text(
                premise_lock.get("premise", topic),
                max_chars=800,
                fallback=topic.strip() or "Requested cartoon premise",
            ),
            characters=list(cast),
            scenes=scenes,
            ending_callback=(
                "Return to the opening conflict with a final comic reversal."
            ),
        )
        plan, _ = enrich_plan(
            plan,
            known_backgrounds=set(background_ids()),
        )
        apply_scene_dynamics(plan)
        return plan

    @classmethod
    def _reconcile_batch_to_briefs(
        cls,
        *,
        raw_batch: CartoonSceneBatch | None,
        briefs: list[CartoonSceneBrief],
        cast_ids: list[str],
        language: CartoonLanguagePack,
        topic: str,
        target_scene_seconds: float,
    ) -> tuple[CartoonSceneBatch, dict[str, int | bool]]:
        returned = (
            list(raw_batch.scenes)
            if raw_batch is not None
            else []
        )

        returned_ids = [
            scene.id
            for scene in returned
        ]
        expected_ids = [
            brief.id
            for brief in briefs
        ]

        reconciled = (
            returned_ids[:len(briefs)] != expected_ids
            or len(returned) != len(briefs)
        )

        if reconciled:
            print(
                "[CARTOON RECOVERY] "
                f"Reconciling batch: expected_ids={expected_ids}, "
                f"returned_ids={returned_ids}."
            )

        scenes: list[CartoonScene] = []
        fallback_count = 0

        for index, brief in enumerate(briefs):
            if index < len(returned):
                scene = returned[index]
                scene.id = brief.id
                scene.location_id = brief.location_id
                scene.beat = brief.beat

                cls._normalize_scene_speakers(
                    scene=scene,
                    expected_speakers=brief.speakers,
                )

                scenes.append(scene)
            else:
                fallback_count += 1
                scenes.append(
                    cls._fallback_scene_from_brief(
                        brief=brief,
                        language=language,
                        topic=topic,
                        target_scene_seconds=target_scene_seconds,
                        variant=index,
                    )
                )

        return (
            CartoonSceneBatch(
                scenes=scenes
            ),
            {
                "reconciled": reconciled,
                "dropped_extra_scenes": max(
                    0,
                    len(returned) - len(briefs),
                ),
                "fallback_scenes": fallback_count,
            },
        )

    @classmethod
    def _finalize_episode_scenes(
        cls,
        *,
        scenes: list[CartoonScene],
        briefs: list[CartoonSceneBrief],
        language: CartoonLanguagePack,
        topic: str,
        target_scene_seconds: float,
    ) -> list[CartoonScene]:
        by_id = {
            scene.id: scene
            for scene in scenes
        }

        final: list[CartoonScene] = []

        for index, brief in enumerate(briefs):
            scene = by_id.get(brief.id)

            if scene is None:
                scene = cls._fallback_scene_from_brief(
                    brief=brief,
                    language=language,
                    topic=topic,
                    target_scene_seconds=target_scene_seconds,
                    variant=index,
                )

            scene.id = brief.id
            scene.location_id = brief.location_id
            scene.beat = brief.beat
            scene.shot_duration_seconds = target_scene_seconds

            cls._normalize_scene_speakers(
                scene=scene,
                expected_speakers=brief.speakers,
            )

            final.append(scene)

        return final

    @classmethod
    def _repair_quality_locally(
        cls,
        *,
        batch: CartoonSceneBatch,
        briefs: list[CartoonSceneBrief],
        language: CartoonLanguagePack,
        topic: str,
        issues: list[str],
        target_scene_seconds: float,
    ) -> int:
        affected_ids: set[int] = set()

        for issue in issues:
            # V17.8: do not destroy usable LLM dialogue merely because a
            # semantic/premise check failed. V17.7 replaced such scenes with a
            # generic three-line fallback, which is exactly how scenes 4-6
            # collapsed into filler. Semantic failures are repaired by the
            # bounded LLM pass above; if they remain, preserve the evidence and
            # let the final story gate block rendering.
            if "fewer than 2 dialogue" not in issue:
                continue

            match = re.search(
                r"scene\s+(\d+)",
                issue,
                flags=re.IGNORECASE,
            )

            if match:
                affected_ids.add(
                    int(match.group(1))
                )

        if not affected_ids:
            return 0

        brief_by_id = {
            brief.id: brief
            for brief in briefs
        }

        repaired = 0

        for index, scene in enumerate(batch.scenes):
            if scene.id not in affected_ids:
                continue

            fallback = cls._fallback_scene_from_brief(
                brief=brief_by_id[scene.id],
                language=language,
                topic=topic,
                target_scene_seconds=target_scene_seconds,
                variant=index,
            )

            scene.dialogue = fallback.dialogue
            repaired += 1

        return repaired

    @staticmethod
    def _normalize_scene_speakers(
        *,
        scene: CartoonScene,
        expected_speakers: list[str],
    ) -> None:
        if not expected_speakers:
            return

        for index, line in enumerate(scene.dialogue):
            if line.character_id not in expected_speakers:
                line.character_id = expected_speakers[
                    index % len(expected_speakers)
                ]

        if (
            scene.reaction is not None
            and scene.reaction.character_id not in expected_speakers
        ):
            scene.reaction.character_id = expected_speakers[-1]

    @classmethod
    def _fallback_scene_from_brief(
        cls,
        *,
        brief: CartoonSceneBrief,
        language: CartoonLanguagePack,
        topic: str,
        target_scene_seconds: float,
        variant: int,
    ) -> CartoonScene:
        first = brief.speakers[0]
        second = (
            brief.speakers[1]
            if len(brief.speakers) > 1
            else first
        )

        premise_lock = cls._resolve_story_premise(
            topic=topic,
            language_code=language.code,
        )

        lines = cls._scene_specific_dialogue(
            language_code=language.code,
            scene_id=brief.id,
            beat=brief.beat,
            premise_lock=premise_lock,
        )

        dialogue = [
            CartoonDialogueLine(
                character_id=first,
                text=lines[0],
                emotion="smirk",
                pose=("pointing" if brief.id % 2 else "thinking"),
                pause_after_seconds=0.22,
            ),
            CartoonDialogueLine(
                character_id=second,
                text=lines[1],
                emotion=(
                    "angry"
                    if brief.beat in {"escalation", "punchline"}
                    else "confused"
                ),
                pose=("shocked" if brief.beat in {"reaction", "punchline"} else "pointing"),
                pause_after_seconds=0.26,
            ),
            CartoonDialogueLine(
                character_id=first,
                text=lines[2],
                emotion=(
                    "shocked"
                    if brief.beat == "reaction"
                    else "happy"
                ),
                pose=(
                    "shocked"
                    if brief.beat in {"reaction", "punchline", "callback"}
                    else ("pointing" if brief.id % 2 else "thinking")
                ),
                pause_after_seconds=(0.42 if brief.beat in {"reaction", "punchline", "callback"} else 0.26),
            ),
        ]

        reaction = None

        if brief.beat in {
            "reaction",
            "punchline",
            "callback",
        }:
            reaction = CartoonReaction(
                character_id=second,
                expression=(
                    "laughing"
                    if brief.beat == "callback"
                    else "shocked"
                ),
                duration_seconds=0.7,
                camera="reaction_close_up",
                sfx="comic_sting",
            )

        return CartoonScene(
            id=brief.id,
            location_id=brief.location_id,
            beat=brief.beat,
            camera=brief.camera_hint,
            shot_duration_seconds=target_scene_seconds,
            setup=brief.summary,
            dialogue=dialogue,
            reaction=reaction,
            sfx_cues=(
                ["comic_sting"]
                if brief.beat in {"punchline", "callback"}
                else []
            ),
            camera_action=brief.camera_action_hint,
            transition="hard_cut",
            visual_action=brief.visual_action,
            props=list(brief.props),
            blocking_mode=brief.blocking_mode,
        )

    @staticmethod
    def _resolve_story_premise(*, topic: str, language_code: str) -> dict[str, object]:
        return resolve_story_profile(topic=topic, language_code=language_code)

    @classmethod
    def _scene_specific_dialogue(
        cls,
        *,
        language_code: str,
        scene_id: int,
        beat: str,
        premise_lock: dict[str, object],
    ) -> tuple[str, str, str]:
        """
        Distinct fallback per story scene. This is intentionally NOT keyed only
        by beat, because beat-only fallback caused scenes 1/2 and other repaired
        scenes to repeat the same generic dialogue.
        """
        key = str(premise_lock.get("key", ""))

        route_lines = premise_lock.get("scene_lines", {})
        if isinstance(route_lines, dict):
            values = route_lines.get(str(scene_id))
            if isinstance(values, list) and len(values) >= 3:
                return (str(values[0]), str(values[1]), str(values[2]))

        if key == "game_designer":
            packs = {
                "hindi": {
                    1: (
                        "मैं गेम डिजाइनर बनना चाहता हूँ—सिर्फ गेम खेलना नहीं, उन्हें बनाना।",
                        "पहले घर पर ये समझाना कि गेम खेलना और गेम बनाना दो अलग बातें हैं।",
                        "इसीलिए आज बात नहीं, अपना बनाया गेम दिखाऊँगा।",
                    ),
                    2: (
                        "माँ, मुझे इसी काम में सच में मज़ा भी आता है और मैं सीख भी रहा हूँ।",
                        "मुझे शौक से दिक्कत नहीं, बस करियर में कमाई और स्थिरता भी चाहिए।",
                        "ठीक है, मैं छह महीने का सीखने और कमाने का प्लान भी दिखाऊँगा।",
                    ),
                    3: (
                        "घर वाले भाषण से नहीं मानेंगे; अपना मोबाइल गेम चला के दिखा।",
                        "और अगर डेमो अटक गया तो?",
                        "तो तू बोल देना—बग भी बता रहा है कि लड़का सच में डेवलपमेंट कर रहा है।",
                    ),
                    4: (
                        "बाबूजी पूछेंगे कि गेम डिजाइन से महीने की कमाई कितनी पक्की है।",
                        "और शर्मा जी के इंजीनियर बेटे की सैलरी का उदाहरण फ्री में आएगा।",
                        "इस बार तुलना सुनूँगा भी और अपना प्लान नंबरों में दिखाऊँगा भी।",
                    ),
                    5: (
                        "देखो, यह छोटा मोबाइल गेम मैंने खुद डिजाइन और बनाया है।",
                        "अरे, इसमें मेरा नाम डाल दे—कम से कम मैं भी हीरो तो बनूँ।",
                        "पहले गेम चलने दे, फिर तुझे विलेन का रोल पक्का दूँगा।",
                    ),
                    6: (
                        "लो, सबसे जरूरी समय पर डेमो अटक गया।",
                        "वाह! करियर शुरू होने से पहले ही पहला ऑफिस वाला सिस्टम डाउन मिल गया।",
                        "हँस ले, बग ठीक करके फिर दिखाऊँगा—यही तो असली काम है।",
                    ),
                    7: (
                        "मैं समझ रहा था यह बस मोबाइल में लगा रहता है; इसने तो सच में कुछ बनाया है।",
                        "डेमो गिरा जरूर, पर मेहनत नकली नहीं लग रही।",
                        "बस यही चाहता हूँ—पहले मेरा काम देखिए, फिर फैसला कीजिए।",
                    ),
                    8: (
                        "शर्मा जी का इंजीनियर बेटा मेरे गेम का UI पूछ रहा था—उसे अपना प्रोजेक्ट बनाना है।",
                        "जिस लड़के से हम तेरी तुलना करते थे, वही अब तुझसे सलाह ले रहा है?",
                        "लगता है आज तुलना ने पहली बार दिशा बदल ली।",
                    ),
                    9: (
                        "मुझे छह महीने दीजिए; रोज काम और प्रगति दिखाऊँगा।",
                        "ठीक है, लेकिन हर शुक्रवार नया करियर घोषित नहीं होना चाहिए।",
                        "डील—और पहली कमाई की मिठाई पूरे घर की।",
                    ),
                },
                "english": {
                    1: (
                        "I want to become a game designer—not just play games, actually build them.",
                        "First convince the family that playing and building are two different things.",
                        "That is why I am showing my own game instead of giving another speech.",
                    ),
                    2: (
                        "This is the work I genuinely enjoy and I am getting better at it.",
                        "Enjoyment is fine; a career also needs a plan for income and stability.",
                        "Then I will show a six-month learning and earning plan too.",
                    ),
                    3: (
                        "Do not give them a speech. Run the mobile game you built.",
                        "And if the demo freezes?",
                        "Say the bug proves you are doing real development.",
                    ),
                    4: (
                        "Dad will ask how predictable the income is.",
                        "And Sharma ji's engineer son will arrive in the comparison for free.",
                        "This time I will answer the comparison with an actual plan and numbers.",
                    ),
                    5: (
                        "Look, I designed and built this small mobile game myself.",
                        "Put my name in it; at least make me the hero.",
                        "Let the game survive first, then I will reserve the villain role for you.",
                    ),
                    6: (
                        "Perfect timing—the demo froze exactly when I needed it.",
                        "Nice. Your career got its first system outage before the first salary.",
                        "Laugh now. Fixing the bug is part of the actual job.",
                    ),
                    7: (
                        "I thought he was only sitting on the phone; he has actually built something.",
                        "The demo failed, but the effort does not look fake.",
                        "That is all I wanted—judge the work before judging the career.",
                    ),
                    8: (
                        "Sharma ji's engineer son asked me about my game's UI for his project.",
                        "The same boy we keep comparing you with is asking you for advice?",
                        "Looks like the comparison finally changed direction.",
                    ),
                    9: (
                        "Give me six months and judge me by consistent work and progress.",
                        "Deal, but no brand-new career announcement every Friday.",
                        "Deal—and the first earning pays for sweets for everyone.",
                    ),
                },
                "hinglish": {
                    1: (
                        "Main game designer banna chahta hoon—sirf game khelna nahi, banana.",
                        "Pehle ghar walon ko playing aur building ka difference samjha.",
                        "Isliye aaj speech nahi, apna banaya game dikhaunga.",
                    ),
                    2: (
                        "Mujhe genuinely isi kaam mein maza aata hai aur skill bhi improve ho rahi hai.",
                        "Maza theek hai, career mein income aur stability ka plan bhi chahiye.",
                        "Done, six-month learning aur earning plan bhi dikhaunga.",
                    ),
                    3: (
                        "Speech mat de; jo mobile game banaya hai woh run karke dikha.",
                        "Aur demo hang ho gaya toh?",
                        "Bol dena bug proof hai ki banda real development kar raha hai.",
                    ),
                    4: (
                        "Babuji income poochhenge aur Sharma ji ka engineer beta comparison mein aa jayega.",
                        "Comparison free hai, bas salary figure extra loud hota hai.",
                        "Iss baar plan aur numbers se answer karunga.",
                    ),
                    5: (
                        "Ye small mobile game maine khud design aur build kiya hai.",
                        "Mera naam daal de, kam se kam hero bana de.",
                        "Pehle game chalne de, villain role tera fixed hai.",
                    ),
                    6: (
                        "Perfect timing—demo abhi hang hona tha.",
                        "Career start se pehle first system-down experience bhi mil gaya.",
                        "Has le; bug fix karna bhi real kaam ka part hai.",
                    ),
                    7: (
                        "Mujhe laga phone hi chala raha tha; isne sach mein kuch build kiya hai.",
                        "Demo gira, but effort fake nahi lag raha.",
                        "Bas pehle kaam dekho, phir career judge karo.",
                    ),
                    8: (
                        "Sharma ji ka engineer beta mere game ka UI pooch raha tha.",
                        "Jisse comparison hoti thi, wahi ab advice le raha hai?",
                        "Aaj comparison ne U-turn le liya.",
                    ),
                    9: (
                        "Six months do; daily work aur progress dikhaunga.",
                        "Deal, bas har Friday naya career announce mat karna.",
                        "Deal—and first earning ki mithai sabke liye.",
                    ),
                },
            }

            language_pack = packs.get(
                language_code,
                packs.get("english", {}),
            )

            if scene_id in language_pack:
                return language_pack[scene_id]

        # Generic route fallback must remain premise-safe. V11.3.2 still used
        # an old career/family dialogue pack here, which could turn an action
        # chase into two people discussing jobs.
        if key.startswith("route_"):
            return cls._universal_fallback_dialogue(
                language_code=language_code,
                beat=beat,
                action_story=bool(premise_lock.get("action_story", False)),
            )

        return cls._fallback_dialogue(
            language_code=language_code,
            beat=beat,
        )

    @staticmethod
    def _universal_fallback_dialogue(
        *,
        language_code: str,
        beat: str,
        action_story: bool,
    ) -> tuple[str, str, str]:
        action_packs = {
            "english": {
                "setup": ("Whoa—move! The trouble just started!", "Don't explain it, follow it!", "I'm going—keep your eyes on it!"),
                "escalation": ("It slipped ahead again!", "Take the other side; I'll follow!", "No stopping now—move!"),
                "misdirection": ("I thought it went this way!", "Wrong turn—look over there!", "Fine, new route. Keep moving!"),
                "reaction": ("That almost worked!", "Almost is doing a lot of work there.", "Less talking—one more try!"),
                "punchline": ("We've chased it everywhere and it still has the advantage!", "At least the whole place got free entertainment.", "Wait—look what it's doing now!"),
                "callback": ("After all that running, this is how it ends?", "Apparently the joke was running faster than us.", "Fine. Nobody is ever forgetting this."),
            },
            "hindi": {
                "setup": ("अरे, चलो! गड़बड़ अभी शुरू हुई है!", "समझाना बाद में, पहले उसके पीछे चलो!", "मैं जा रहा हूँ—नज़र मत हटाना!"),
                "escalation": ("वो फिर आगे निकल गया!", "तुम दूसरी तरफ से घेरो, मैं पीछे जाता हूँ!", "अब रुकना मत—दौड़ो!"),
                "misdirection": ("मुझे लगा इधर गया!", "गलत तरफ—उधर देखो!", "ठीक है, रास्ता बदलो और चलते रहो!"),
                "reaction": ("बस थोड़ा सा रह गया था!", "हाँ, बस जीत को छोड़कर सब मिल गया.", "बात कम, एक कोशिश और!"),
                "punchline": ("इतना दौड़े फिर भी चाल उसी की चल रही है!", "कम से कम पूरे इलाके का मनोरंजन हो गया.", "रुको—अब ये क्या कर रहा है!"),
                "callback": ("इतनी दौड़ के बाद अंत ऐसा होगा?", "लगता है मज़ाक हमसे तेज भाग रहा था.", "ठीक है, ये किस्सा कोई नहीं भूलेगा."),
            },
            "hinglish": {
                "setup": ("Arre move! Gadbad abhi start hui hai!", "Explanation baad mein, pehle uske peeche!", "Main ja raha hoon—nazar mat hatana!"),
                "escalation": ("Woh phir aage nikal gaya!", "Tum doosri side se ghero, main follow karta hoon!", "Ab rukna mat—run!"),
                "misdirection": ("Mujhe laga idhar gaya!", "Wrong side—udhar dekho!", "Theek hai, route change. Chalte raho!"),
                "reaction": ("Bas thoda sa reh gaya tha!", "Haan, bas jeet hi missing thi.", "Talking kam, ek try aur!"),
                "punchline": ("Itna chase kiya aur advantage abhi bhi uske paas!", "Poore area ko free comedy mil gayi.", "Ruko—ab woh kya kar raha hai!"),
                "callback": ("Itni running ke baad ending aisi?", "Joke humse tez bhaag raha tha.", "Theek hai, ye story koi nahi bhulega."),
            },
            "magahi": {
                "setup": ("अरे चलऽ! गड़बड़ अभी शुरूए भेल हई!", "बात बाद में, पहिले ओकरा पीछे चलऽ!", "हम जा रहल हई—नजर मत हटइहऽ!"),
                "escalation": ("ऊ फेर आगे निकल गेल!", "तू दोसरा ओर से घेरऽ, हम पीछे जाइत हई!", "अब रुकऽ मत—दौड़ऽ!"),
                "misdirection": ("हमरा लगल इधरे गेल!", "गलत ओर—उधर देखऽ!", "ठीक हई, रास्ता बदलऽ, चलते रहऽ!"),
                "reaction": ("बस जरा सा बाकी रहल!", "हाँ, जीत छोड़ के सब मिल गेल.", "बात कम, एक बेर आउर!"),
                "punchline": ("एतना दौड़लूँ, फेरो चाल ओकरे चल रहल हई!", "पूरा टोला के मुफ्त में तमाशा मिल गेल.", "रुकऽ—अब ई का कर रहल हई!"),
                "callback": ("एतना दौड़ के बाद अंत अइसन?", "लगऽ हई मजाक हमनी से तेज भाग रहल हल.", "ठीक हई, ई किस्सा केहू ना भूलतई."),
            },
            "bhojpuri": {
                "setup": ("अरे चलऽ! गड़बड़ अबहीं शुरू भइल बा!", "बात बाद में, पहिले ओकरा पीछे चलऽ!", "हम जात बानी—नजर मत हटइहऽ!"),
                "escalation": ("ऊ फेर आगे निकल गइल!", "तू दूसरा ओर से घेरऽ, हम पीछे जात बानी!", "अब रुकऽ मत—दौड़ऽ!"),
                "misdirection": ("हमरा लागल इधरे गइल!", "गलत ओर—उधर देखऽ!", "ठीक बा, रास्ता बदलऽ, चलते रहऽ!"),
                "reaction": ("बस थोड़ा सा बाकी रहल!", "हाँ, जीत छोड़ के सब मिल गइल.", "बात कम, एक बेर अउर!"),
                "punchline": ("एतना दौड़नी, फेरो चाल ओकरे चलत बा!", "पूरा मोहल्ला के मुफ्त तमाशा मिल गइल.", "रुकऽ—अब ई का करत बा!"),
                "callback": ("एतना दौड़ के बाद अंत अइसन?", "लागता मजाक हमनी से तेज भागत रहे.", "ठीक बा, ई कहानी केहू ना भूली."),
            },
        }
        neutral_packs = {
            "english": ("Something changed—look closely.", "Let's deal with what is actually happening here.", "Good. One clear move at a time."),
            "hindi": ("कुछ बदल गया है—ध्यान से देखो.", "जो सच में हो रहा है, उसी पर काम करते हैं.", "ठीक है, एक साफ कदम लेते हैं."),
            "hinglish": ("Kuch change hua hai—dhyan se dekho.", "Jo actually ho raha hai, usi ko handle karte hain.", "Theek hai, ek clear move lete hain."),
            "magahi": ("कुछ बदल गेल हई—ध्यान से देखऽ.", "जे सच में हो रहल हई, ओकरे संभालऽ.", "ठीक हई, एक साफ चाल चलऽ."),
            "bhojpuri": ("कुछ बदल गइल बा—ध्यान से देखऽ.", "जवन सच में होत बा, ओकरे संभालऽ.", "ठीक बा, एगो साफ चाल चलीं."),
        }
        lang = language_code if language_code in action_packs else "english"
        if not action_story:
            return neutral_packs.get(lang, neutral_packs["english"])
        pack = action_packs[lang]
        return pack.get(beat, pack["escalation"])

    @staticmethod
    def _universal_premise_directions(
        *,
        premise_lock: dict[str, object],
        count: int,
    ) -> list[tuple[str, str]]:
        goal = str(premise_lock.get("goal", "the requested premise"))
        world = str(premise_lock.get("capability_world", "requested world"))
        actions = ", ".join(str(x) for x in premise_lock.get("topic_actions", [])) or "requested action"
        props = ", ".join(str(x) for x in premise_lock.get("topic_props", [])) or "important object"

        if bool(premise_lock.get("action_story", False)):
            action_base = [
                (
                    f"Start with a visible physical trigger from the exact premise: {goal}.",
                    "Open on motion/object interaction; no static exposition two-shot.",
                ),
                (
                    f"Escalate the active objective using {actions}; actors move through the current environment.",
                    "Keep pursuit/motion readable in a wide or tracking shot.",
                ),
                (
                    f"Carry the same object(s) {props} and objective into the next beat/location.",
                    "Preserve object ownership and spatial continuity while the action continues.",
                ),
                (
                    "Introduce a new obstacle, wrong turn, or search beat that changes blocking and screen direction.",
                    "Fresh movement pattern; do not stop for a face-to-face conversation.",
                ),
                (
                    "Resume the main action with a stronger visual attempt and reaction from supporting characters.",
                    "Use group movement/reaction and a different framing emphasis.",
                ),
                (
                    "Finish with the topic's own visual payoff/callback, keeping the important object visible.",
                    "Decisive visual joke or reveal; no unrelated moral/career/family detour.",
                ),
            ]
            if count <= len(action_base):
                return action_base[:count]
            extras_needed = count - len(action_base)
            extras = [
                (
                    "Add another action obstacle in the current or next explicit location.",
                    "Change path, blocking, prop use, or screen direction; never replay the same two-shot.",
                )
                for _ in range(extras_needed)
            ]
            return action_base[:4] + extras + action_base[4:]

        base = [
            (
                f"Visual hook: immediately show the exact user premise in {world}: {goal}. "
                f"Put the named role, place and object on screen early.",
                "Visible hook; never substitute family/career content.",
            ),
            (
                f"Clarify the immediate objective while keeping action(s) {actions} and object(s) {props} relevant.",
                "Introduce one world-appropriate obstacle.",
            ),
            (
                "The protagonist makes the first active physical attempt using the same premise and object.",
                "Advance with action, not explanation.",
            ),
            (
                "Complicate the attempt with a fresh setting-appropriate obstacle or misunderstanding.",
                "Escalate visually without changing profession/place/object.",
            ),
            (
                "Deliver the main payoff or reveal caused by the earlier action and object.",
                "Strongest story-specific visual/comedic payoff.",
            ),
            (
                "Close with a short callback to the opening action/object and a decisive final visual beat.",
                "No unrelated moral, career or family detour.",
            ),
        ]
        if count <= 6:
            return base[:count]
        extras_needed = count - 6
        extras_base = [
            (
                "Try a second physical tactic while preserving the same protagonist, world and object.",
                "New tactic; no repeated dialogue.",
            ),
            (
                "Add a location-appropriate interruption that forces adaptation of the original plan.",
                "Fresh obstacle with visible consequence.",
            ),
            (
                "Let another relevant role briefly help or hinder the same objective.",
                "Role-specific interaction, not generic family pressure.",
            ),
        ]
        extras = [extras_base[i % len(extras_base)] for i in range(extras_needed)]
        return base[:4] + extras + base[4:]


    @staticmethod
    def _v1710_is_ai_home_assistant_topic(topic: str) -> bool:
        normalized = unicodedata.normalize("NFKC", str(topic or "").casefold())
        has_ai = bool(re.search(r"(?:\bai\b|असिस्टेंट|assistant)", normalized))
        has_home = any(token in normalized for token in ("घर", "home", "house"))
        has_task = any(token in normalized for token in ("काम", "सफाई", "clean", "housework", "घर का काम"))
        return has_ai and has_home and has_task

    @classmethod
    def _v1710_ai_home_directions(cls, *, count: int) -> list[tuple[str, str]]:
        base = [
            (
                "Babuji asks the phone AI assistant for help with one simple household task. The AI gives a clear short instruction; Babuji immediately interprets one word too literally or incorrectly and starts the first visible mistake.",
                "State the AI instruction and Babuji's wrong interpretation clearly. The family reacts to the AI; nobody impersonates the AI. End on a small laugh beat.",
            ),
            (
                "The AI gives a second, different living-room instruction about clearing, arranging, or cleaning a specific object. Babuji confidently applies it to the wrong thing and creates a new physical problem.",
                "Use a fresh object/action, not the previous scene's prop or wording. Show consequence before explanation.",
            ),
            (
                "In the courtyard, the AI gives a new household/outdoor instruction. Babuji over-literalizes or mishears it and performs the wrong physical action, making the mess visibly worse.",
                "Keep AI -> misunderstanding -> action -> consequence explicit. Do not drift into an unrelated subplot.",
            ),
            (
                "The AI tries to correct the courtyard mistake with a clarification. Babuji misunderstands the correction as a different task and doubles down while Guddu/Bittu/Mai react.",
                "Fresh reversal; no repeated setup sentence. Make the correction itself trigger the next joke.",
            ),
            (
                "In the kitchen, the AI gives one practical instruction involving a kitchen object or ingredient. Babuji applies it to the wrong household item or takes the wording literally, causing the episode's strongest visible payoff.",
                "Strongest distinct gag. 5-7 reciprocal turns; no lecture and no recycling earlier props unless needed for a callback.",
            ),
            (
                "The AI gives a final corrective or 'undo' instruction. Babuji misunderstands it one last time, but Mai/Guddu/Bittu lands a short callback to the first mistake and ends the scene decisively.",
                "Callback to scene 1 with new meaning; do not repeat the opening dialogue verbatim. End on a short punchline, not a summary.",
            ),
        ]
        if count <= len(base):
            return base[:count]
        extras = [
            (
                "The AI gives another distinct household instruction in the current location; Babuji converts it into a new physical misunderstanding.",
                "New object, new action and visible consequence; do not recycle the previous joke mechanism.",
            )
            for _ in range(count - len(base))
        ]
        return base[:4] + extras + base[4:]

    @classmethod
    def _premise_scene_directions(
        cls,
        *,
        premise_lock: dict[str, object],
        count: int,
    ) -> list[tuple[str, str]]:
        route_directions = premise_lock.get("scene_directions", [])
        if isinstance(route_directions, list) and len(route_directions) >= count:
            return [(str(route_directions[i][0]), str(route_directions[i][1])) for i in range(count)]

        key = str(premise_lock.get("key", ""))
        goal_text = str(premise_lock.get("goal", ""))
        premise_text = str(premise_lock.get("premise", ""))
        if cls._v1710_is_ai_home_assistant_topic(f"{goal_text} {premise_text}"):
            return cls._v1710_ai_home_directions(count=count)
        if key.startswith("route_"):
            return cls._universal_premise_directions(
                premise_lock=premise_lock,
                count=count,
            )
        if key != "game_designer" or count < 9:
            return cls._progression_directions(count)

        goal = str(premise_lock.get("goal", "game designer"))
        safe_path = str(premise_lock.get("safe_path", "a secure conventional job"))
        project = str(premise_lock.get("project", "a small proof-of-work project"))
        comparison = str(premise_lock.get("comparison", "the family's usual comparison"))

        base = [
            (
                f"Guddu reveals one locked goal: {goal}. He explains that he wants "
                f"to create games, not merely play them.",
                "Establish the specific career once; no alternative profession.",
            ),
            (
                f"Mai challenges the plan with the family's preference for "
                f"{safe_path}.",
                "Conflict is income/stability, not a repeat of scene 1.",
            ),
            (
                f"Bittu suggests proving the choice by showing {project}.",
                "Set up a concrete demo and one joke about it failing.",
            ),
            (
                f"Family pressure escalates around predictable income and the "
                f"comparison with {comparison}.",
                "Use salary/security/comparison; do not invent children or energy.",
            ),
            (
                f"Guddu actively demonstrates {project} to prove he has real skill.",
                "Show the project itself; do not replace it with an unrelated gadget.",
            ),
            (
                "The game demo freezes or crashes at the worst possible moment.",
                "Backfire must come directly from the same project.",
            ),
            (
                "The family reacts: the demo failed, but they finally notice the "
                "real work and effort behind it.",
                "Reaction should acknowledge effort, not start a new future/child topic.",
            ),
            (
                f"Main twist: {comparison} now asks Guddu for game/UI advice, "
                "reversing the family's favorite comparison.",
                "Land the strongest comparison reversal.",
            ),
            (
                "Callback: the family gives Guddu six months to prove consistent "
                "work; Bittu jokes about choosing a new career every Friday.",
                "Close with a clear chance + sweets/first-earning callback.",
            ),
        ]

        if count == 9:
            return base

        # Keep final 3 payoff beats at the end for longer episodes.
        extra_needed = count - 9
        extras = [
            (
                "Add a new obstacle inside the SAME game-design plan.",
                "No new profession, product category, or family relationship.",
            )
            for _ in range(extra_needed)
        ]

        return base[:6] + extras + base[6:]

    @staticmethod
    def _topic_named_protagonist(
        topic: str,
    ) -> str | None:
        value = unicodedata.normalize("NFKC", topic.casefold())
        alias_map: dict[str, tuple[str, ...]] = {
            "babuji": ("बाबूजी", "बाबू जी", "पिताजी", "babuji", "papaji", "father", "dad"),
            "mai": ("माई", "माँ", "मां", "मम्मी", "mai", "mummy", "mother", "mom"),
            "guddu": ("गुड्डू", "guddu"),
            "bittu": ("बिट्टू", "bittu"),
            "dadaji": ("दादाजी", "दादा जी", "dadaji", "grandpa"),
            "teacher": ("टीचर", "शिक्षक", "teacher", "masterji"),
            "doctor": ("डॉक्टर", "doctor"),
        }
        hits: list[tuple[int, str]] = []
        for character_id, aliases in alias_map.items():
            positions = [value.find(alias.casefold()) for alias in aliases]
            positions = [pos for pos in positions if pos >= 0]
            if positions:
                hits.append((min(positions), character_id))
        if not hits:
            return None
        hits.sort(key=lambda item: item[0])
        return hits[0][1]

    @staticmethod
    def _topic_anchor_tokens(
        topic: str,
    ) -> list[str]:
        """Extract high-signal premise words for dialogue-only continuity QA."""
        normalized = unicodedata.normalize("NFKC", topic.casefold())
        raw = re.findall(
            r"[a-z][a-z0-9_+-]*|[\u0900-\u097f]+",
            normalized,
            flags=re.IGNORECASE,
        )
        stop = {
            "और", "या", "के", "की", "का", "को", "से", "में", "पर", "है", "हैं", "था", "थी",
            "पहली", "बार", "लेकिन", "हर", "बात", "पूरा", "पूरे", "करते", "करता", "करती",
            "करने", "करवाने", "कोशिश", "देते", "देता", "देती", "एक", "फिर", "जब", "तक",
            "main", "mein", "hai", "hain", "aur", "ya", "ka", "ki", "ke", "ko", "se",
            "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with",
            "tries", "try", "trying", "first", "time", "but", "every", "whole",
            "guddu", "bittu", "babuji", "mai", "dadaji", "teacher", "doctor",
            "गुड्डू", "बिट्टू", "बाबूजी", "माई", "दादाजी", "टीचर", "डॉक्टर",
        }
        anchors: list[str] = []
        for token in raw:
            token = token.strip("._-").casefold()
            if not token or token in stop:
                continue
            if token != "ai" and len(token) < 3:
                continue
            if token not in anchors:
                anchors.append(token)
        return anchors[:8]

    @classmethod
    def _v178_semantic_issues(
        cls,
        *,
        batch: CartoonSceneBatch,
        language: CartoonLanguagePack,
        topic: str,
    ) -> list[str]:
        issues: list[str] = []
        anchors = cls._topic_anchor_tokens(topic)
        protagonist = cls._topic_named_protagonist(topic)

        for scene in batch.scenes:
            dialogue_text = " ".join(
                line.text for line in scene.dialogue if line.text.strip()
            )
            normalized = unicodedata.normalize("NFKC", dialogue_text.casefold())

            if anchors and not any(anchor in normalized for anchor in anchors):
                issues.append(
                    f"scene {scene.id} misses premise dialogue anchor; "
                    f"expected one of {anchors[:5]}"
                )

            if protagonist and protagonist not in {
                str(line.character_id) for line in scene.dialogue
            }:
                issues.append(
                    f"scene {scene.id} omits topic-named protagonist {protagonist}"
                )

            if language.code == "hindi":
                dev = len(re.findall(r"[\u0900-\u097f]", dialogue_text))
                latin = len(re.findall(r"[A-Za-z]", dialogue_text))
                if latin >= 30 and dev < max(12, int(latin * 0.45)):
                    issues.append(
                        f"scene {scene.id} Hindi dialogue is mostly Romanized instead of natural Devanagari"
                    )

            token_lines: list[list[str]] = []
            for line in scene.dialogue:
                tokens = re.findall(
                    r"[A-Za-z\u0900-\u097f]+",
                    unicodedata.normalize("NFKC", line.text.casefold()),
                )
                token_lines.append([token for token in tokens if len(token) >= 3])

            phrase_line_counts: dict[str, set[int]] = {}
            for line_index, tokens in enumerate(token_lines):
                for n in (2, 3):
                    for start in range(max(0, len(tokens) - n + 1)):
                        phrase = " ".join(tokens[start:start+n])
                        if len(phrase) < 8:
                            continue
                        phrase_line_counts.setdefault(phrase, set()).add(line_index)
            repeated = [
                phrase for phrase, line_ids in phrase_line_counts.items()
                if len(line_ids) >= 3
            ]
            if repeated:
                issues.append(
                    f"scene {scene.id} has repeated phrase loop: {repeated[0]!r}"
                )

        return cls._dedupe(issues)

    @classmethod
    def _v1710_ai_home_issues(
        cls,
        *,
        batch: CartoonSceneBatch,
        topic: str,
    ) -> list[str]:
        if not cls._v1710_is_ai_home_assistant_topic(topic):
            return []
        issues: list[str] = []
        ai_tokens = ("ai", "असिस्टेंट", "assistant", "फोन", "निर्देश", "आवाज़")
        for scene in batch.scenes:
            text = unicodedata.normalize(
                "NFKC",
                " ".join(line.text for line in scene.dialogue).casefold(),
            )
            if not any(token in text for token in ai_tokens):
                issues.append(
                    f"scene {scene.id} loses AI-assistant instruction source"
                )
            babuji_turns = sum(1 for line in scene.dialogue if str(line.character_id) == "babuji")
            if babuji_turns < 2:
                issues.append(
                    f"scene {scene.id} gives Babuji too little agency for the AI-home premise"
                )
        return cls._dedupe(issues)

    @classmethod
    def v178_plan_weak_reasons(
        cls,
        *,
        plan: CartoonEpisodePlan,
        language: CartoonLanguagePack,
    ) -> dict[int, list[str]]:
        """Return V17.9 scene-level public-quality reasons for a Hindi plan."""
        weak_reasons: dict[int, list[str]] = {}
        for scene in plan.scenes:
            scene_id = int(scene.id)
            if len(scene.dialogue) < 5:
                weak_reasons.setdefault(scene_id, []).append(
                    f"turns={len(scene.dialogue)}<5"
                )
            words = dialogue_word_count([scene])
            if words < 45:
                weak_reasons.setdefault(scene_id, []).append(
                    f"words={words}<45"
                )
            semantic = cls._v178_semantic_issues(
                batch=CartoonSceneBatch(scenes=[scene]),
                language=language,
                topic=plan.topic,
            )
            if semantic:
                weak_reasons.setdefault(scene_id, []).extend(semantic[:3])
            ai_home = cls._v1710_ai_home_issues(
                batch=CartoonSceneBatch(scenes=[scene]),
                topic=plan.topic,
            )
            if ai_home:
                weak_reasons.setdefault(scene_id, []).extend(ai_home[:2])

        seen_lines: dict[str, int] = {}
        for scene in plan.scenes:
            for line in scene.dialogue:
                key = cls._dialogue_key(line.text)
                if not key:
                    continue
                prior_scene = seen_lines.get(key)
                if prior_scene is not None and prior_scene != int(scene.id):
                    weak_reasons.setdefault(int(scene.id), []).append(
                        "cross-scene repeated dialogue"
                    )
                    weak_reasons.setdefault(prior_scene, []).append(
                        "cross-scene repeated dialogue"
                    )
                else:
                    seen_lines[key] = int(scene.id)

        return {
            scene_id: cls._dedupe(reasons)
            for scene_id, reasons in weak_reasons.items()
        }

    @classmethod
    def _premise_continuity_issues(
        cls,
        *,
        batch: CartoonSceneBatch,
        language: CartoonLanguagePack,
        topic: str,
    ) -> list[str]:
        premise_lock = cls._resolve_story_premise(
            topic=topic,
            language_code=language.code,
        )

        if premise_lock.get("key") != "game_designer":
            return []

        issues: list[str] = []

        anchor_sets = {
            "hindi": {
                1: ("गेम", "डिजाइन"),
                2: ("कमाई", "स्थिर", "सुरक्षित", "छह महीने"),
                3: ("डेमो", "गेम", "मोबाइल"),
                4: ("कमाई", "सैलरी", "शर्मा", "तुलना"),
                5: ("गेम", "डेमो", "मोबाइल", "प्रोजेक्ट"),
                6: ("डेमो", "अटक", "क्रैश", "बग"),
                7: ("काम", "मेहनत", "डेमो", "बनाया"),
                8: ("शर्मा", "तुलना", "इंजीनियर", "सलाह", "UI"),
                9: ("छह महीने", "महीने", "मौका", "कमाई", "मिठाई"),
            },
            "english": {
                1: ("game", "design"),
                2: ("income", "stability", "secure", "six-month"),
                3: ("demo", "game", "mobile"),
                4: ("income", "salary", "sharma", "comparison"),
                5: ("game", "demo", "mobile", "project"),
                6: ("demo", "freeze", "crash", "bug"),
                7: ("work", "effort", "demo", "built"),
                8: ("sharma", "comparison", "engineer", "advice", "ui"),
                9: ("six months", "chance", "earning", "sweets"),
            },
            "hinglish": {
                1: ("game", "design"),
                2: ("income", "stability", "secure", "six"),
                3: ("demo", "game", "mobile"),
                4: ("income", "salary", "sharma", "comparison"),
                5: ("game", "demo", "mobile", "project"),
                6: ("demo", "hang", "crash", "bug"),
                7: ("work", "effort", "demo", "build"),
                8: ("sharma", "comparison", "engineer", "advice", "ui"),
                9: ("six months", "career", "earning", "mithai"),
            },
        }

        anchors = anchor_sets.get(language.code)

        if anchors is None:
            return issues

        off_premise = {
            "hindi": (
                "बिजली",
                "बैटरी",
                "अपने बच्चे का भविष्य",
                "तुम्हारे बच्चे के भविष्य",
                "मेरा बच्चा",
            ),
            "english": (
                "electricity",
                "battery",
                "your child's future",
                "my child",
            ),
            "hinglish": (
                "electricity",
                "battery",
                "bacche ka future",
                "mera baccha",
            ),
        }.get(language.code, ())

        for scene in batch.scenes:
            text = " ".join(
                [scene.setup]
                + [
                    line.text
                    for line in scene.dialogue
                ]
            ).casefold()

            required = anchors.get(scene.id, ())

            if required and not any(
                token.casefold() in text
                for token in required
            ):
                issues.append(
                    f"scene {scene.id} misses premise anchor for locked "
                    f"game-design progression"
                )

            drift_hits = [
                token
                for token in off_premise
                if token.casefold() in text
            ]

            if drift_hits:
                issues.append(
                    f"scene {scene.id} has off-premise drift: "
                    + ", ".join(drift_hits[:3])
                )

        return issues

    @staticmethod
    def _fallback_dialogue(
        *,
        language_code: str,
        beat: str,
    ) -> tuple[str, str, str]:
        packs = {
            "english": {
                "setup": (
                    "I want to choose work that actually fits what I can do.",
                    "A choice is fine, but show us the plan behind it.",
                    "Fair. This time I will show the work, not just the idea.",
                ),
                "escalation": (
                    "Everyone keeps asking for the safest option.",
                    "Dreams are fine, but responsibility and income matter too.",
                    "Then judge my plan and effort, not only the job title.",
                ),
                "misdirection": (
                    "One good demo and everyone will finally agree.",
                    "If this family agrees that quickly, something is suspicious.",
                    "Fine, first I will make the demo survive the discussion.",
                ),
                "reaction": (
                    "That went in exactly the opposite direction.",
                    "That is why I said we should watch the whole thing first.",
                    "Laugh now; I still have one better move left.",
                ),
                "punchline": (
                    "The person you compare me with is now asking about my work.",
                    "So the comparison finally came back to bite us?",
                    "For once, the work is answering before the neighbors do.",
                ),
                "callback": (
                    "Give me a few months and judge me by consistent work.",
                    "Deal, but do not choose a brand-new career every Friday.",
                    "Deal—and the first earning pays for the sweets.",
                ),
            },
            "hindi": {
                "setup": (
                    "मैं वही रास्ता चुनना चाहता हूँ जिसमें सच में अच्छा काम कर सकूँ।",
                    "रास्ता चुनो, लेकिन उसके पीछे की योजना भी दिखाओ।",
                    "ठीक है, इस बार सिर्फ बोलूँगा नहीं—काम दिखाऊँगा।",
                ),
                "escalation": (
                    "सबको बस सबसे सुरक्षित नौकरी ही क्यों दिखती है?",
                    "सपने के साथ जिम्मेदारी और कमाई भी जुड़ी होती है।",
                    "तो मेरी मेहनत और योजना दोनों देखकर फैसला कीजिए।",
                ),
                "misdirection": (
                    "एक अच्छा डेमो दिखा दूँ तो शायद सब मान जाएँगे।",
                    "हमारा परिवार इतनी जल्दी मान गया तो मज़ाक किस बात का रहेगा?",
                    "ठीक है, पहले डेमो बचा लूँ, फिर बहस जीतूँगा।",
                ),
                "reaction": (
                    "अरे, यह तो पूरा उल्टा पड़ गया।",
                    "इसीलिए कहा था पहले पूरा देखकर बोलना।",
                    "हँस लीजिए, अगला कदम इससे बेहतर होगा।",
                ),
                "punchline": (
                    "जिससे मेरी तुलना करते थे, वही अब मेरे काम के बारे में पूछ रहा है।",
                    "तो तुलना पहली बार हमारे ही खिलाफ पड़ गई?",
                    "आज पड़ोसी नहीं, मेरा काम जवाब दे रहा है।",
                ),
                "callback": (
                    "कुछ महीने लगातार मेहनत करके दिखाऊँगा।",
                    "ठीक है, बस हर शुक्रवार नया करियर मत चुन लेना।",
                    "डील—और पहली कमाई की मिठाई मेरी तरफ से।",
                ),
            },
            "hinglish": {
                "setup": (
                    "Main wahi career try karna chahta hoon jisme main genuinely achha hoon.",
                    "Career choose karo, but proper plan bhi dikhna chahiye.",
                    "Done, iss baar sirf idea nahi—actual kaam dikhaunga.",
                ),
                "escalation": (
                    "Sabko safest job hi kyun chahiye?",
                    "Dream ke saath bills aur responsibility bhi aati hai.",
                    "Toh title nahi, meri planning aur effort judge karo.",
                ),
                "misdirection": (
                    "Ek solid demo dikha diya toh sab maan jayenge.",
                    "Family itni jaldi maan gayi toh comedy khatam ho jayegi.",
                    "Theek hai, pehle demo bachata hoon, phir argument.",
                ),
                "reaction": (
                    "Yeh toh expected se bilkul ulta ho gaya.",
                    "Isliye bola tha pehle poora dekh lo.",
                    "Has lo, mere paas abhi ek better move hai.",
                ),
                "punchline": (
                    "Jis bande se meri comparison hoti thi, wahi mera kaam pooch raha hai.",
                    "Matlab comparison pehli baar reverse ho gayi?",
                    "Aaj neighbours se pehle mera kaam answer de raha hai.",
                ),
                "callback": (
                    "Kuch months consistently kaam karke dikhaunga.",
                    "Deal, bas har Friday naya career mat choose karna.",
                    "Deal—and first earning ki mithai meri taraf se.",
                ),
            },
            "magahi": {
                "setup": (
                    "हम ओही काम चुने चाहऽ हई जेकरा में सच में बढ़िया कर सकी।",
                    "काम चुनऽ, बाकिर ओकर पूरा योजना भी देखावऽ।",
                    "ठीक हई, एह बेर खाली बात ना—काम देखाइब।",
                ),
                "escalation": (
                    "सबके बस सुरक्षित नौकरीए काहे दिखऽ हई?",
                    "सपना के साथ जिम्मेदारी अउ कमाईओ रहऽ हई।",
                    "तऽ हमर मेहनत अउ योजना देख के फैसला करीं।",
                ),
                "misdirection": (
                    "एक बढ़िया डेमो देखाइ देब तऽ सभे मान जइतो।",
                    "हमर घर एतना जल्दी मान गेल तऽ मजाक कहाँ बचतई?",
                    "पहिले डेमो बचा लेई, फेर बहस जीतब।",
                ),
                "reaction": (
                    "अरे, ई तऽ पूरा उल्टा पड़ गेल।",
                    "एही से कहलिअइ कि पहिले पूरा देखऽ।",
                    "हँस लऽ, अगिला चाल अभी बाकी हई।",
                ),
                "punchline": (
                    "जेकरा से हमर तुलना होवऽ हई, ओही अब हमर काम पूछऽ हई।",
                    "तऽ तुलना पहिला बेर अपने पर भारी पड़ गेल?",
                    "आज पड़ोसी ना, हमर काम जवाब दे रहल हई।",
                ),
                "callback": (
                    "कुछ महीना लगातार मेहनत करके देखाइब।",
                    "ठीक हई, बस हर हफ्ता नया करियर मत चुनिहऽ।",
                    "डील—पहिला कमाई के मिठाई हमर तरफ से।",
                ),
            },
            "bhojpuri": {
                "setup": (
                    "हम ओही काम चुने के चाहत बानी जवन हम सच में बढ़िया कर सकीं।",
                    "काम चुनऽ, बाकिर ओकर साफ योजना भी देखावऽ।",
                    "ठीक बा, एह बेर खाली बात ना—काम देखाइब।",
                ),
                "escalation": (
                    "सबके बस सबसे सुरक्षित नौकरीए काहे चाहीं?",
                    "सपना के साथ जिम्मेदारी आ कमाई भी होला।",
                    "त योजना आ मेहनत दुनो देख के फैसला करीं।",
                ),
                "misdirection": (
                    "एक बढ़िया डेमो देखाइ दीं त सभे मान जाई।",
                    "हमार परिवार एतना जल्दी मान गइल त मजाक कहाँ रही?",
                    "पहिले डेमो बचा लीं, फेर बहस जीतब।",
                ),
                "reaction": (
                    "अरे, ई त पूरा उल्टा पड़ गइल।",
                    "एही से कहल रहीं कि पहिले पूरा देख लऽ।",
                    "हँस लऽ, अगिला चाल अभी बाकी बा।",
                ),
                "punchline": (
                    "जेकरा से हमार तुलना होत रहे, उहे अब हमार काम पूछत बा।",
                    "मतलब तुलना पहिला बेर हमरे पक्ष में आ गइल?",
                    "आज पड़ोसी ना, हमार काम जवाब देत बा।",
                ),
                "callback": (
                    "कुछ महीना लगातार मेहनत करके देखाइब।",
                    "ठीक बा, बस हर हफ्ता नया करियर मत चुनिहऽ।",
                    "डील—पहिला कमाई के मिठाई हमार तरफ से।",
                ),
            },
        }

        language_pack = packs.get(
            language_code,
            packs["english"],
        )

        return language_pack.get(
            beat,
            language_pack["escalation"],
        )

    @staticmethod
    def _bounded_scene_text(
        value: object,
        *,
        max_chars: int,
        fallback: str,
    ) -> str:
        """Keep planner-generated Pydantic text fields inside their schema limits.

        Topic text is user-controlled and can be long in any language.  Scene
        directions also add routing/staging context, so concatenating both without
        a boundary can exceed CartoonSceneBrief limits before either the normal
        planner or deterministic recovery path gets a chance to run.
        """
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text:
            text = fallback.strip() or "Scene beat."
        if len(text) <= max_chars:
            return text

        # Prefer a natural break near the end, but never exceed the schema cap.
        room = max(1, max_chars - 1)
        candidate = text[:room].rstrip()
        floor = int(room * 0.72)
        breaks = [
            candidate.rfind(mark)
            for mark in (". " , "! ", "? ", "। ", "; ", ", ")
        ]
        natural = max(breaks)
        if natural >= floor:
            candidate = candidate[: natural + 1].rstrip()
        candidate = candidate.rstrip(" ,;:-—")
        if not candidate:
            candidate = text[:room].rstrip()
        return candidate + "…"

    @classmethod
    def _build_scene_briefs(
        cls,
        *,
        topic: str,
        cast_ids: list[str],
        scene_target: int,
        premise_lock: dict[str, object] | None = None,
    ) -> list[CartoonSceneBrief]:
        premise_lock = premise_lock or {}
        forced_locations = premise_lock.get("forced_location_arc", [])
        route_locations = premise_lock.get("locations", [])

        if isinstance(forced_locations, list) and forced_locations:
            locations = cls._forced_location_arc(
                candidates=[str(x) for x in forced_locations if str(x).strip()],
                count=scene_target,
            )
        elif isinstance(route_locations, list) and route_locations:
            route_locations = [str(item) for item in route_locations if str(item).strip()]
            # Curated packs that provide one location per scene keep their exact
            # authored progression. Generic routes use a coherent location arc.
            curated = bool(premise_lock.get("scene_directions"))
            if curated and len(route_locations) >= scene_target:
                locations = route_locations[:scene_target]
            else:
                locations = cls._coherent_location_arc(
                    candidates=route_locations,
                    count=scene_target,
                )
        else:
            locations = cls._location_sequence(topic=topic, count=scene_target)

        if not locations:
            locations = ["courtyard"] * scene_target

        beats = cls._beat_sequence(scene_target)
        directions = cls._premise_scene_directions(
            premise_lock=premise_lock,
            count=scene_target,
        )
        speaker_pairs = cls._speaker_sequence(
            topic=topic,
            cast_ids=cast_ids,
            count=scene_target,
        )

        action_story = bool(premise_lock.get("action_story", False))
        action_sequence = cls._action_scene_sequence(
            premise_lock=premise_lock,
            count=scene_target,
        )
        topic_props = [str(x) for x in premise_lock.get("topic_props", [])][:6]

        result: list[CartoonSceneBrief] = []

        for index in range(scene_target):
            scene_id = index + 1
            beat = beats[index]
            summary, goal = directions[index]
            first, second = speaker_pairs[index]

            location = locations[index]
            previous_location = locations[index - 1] if index > 0 else None
            if previous_location is None:
                setting_direction = (
                    f"Open clearly in {location}; establish the environment through "
                    "visible action before settling into dialogue."
                )
            elif location != previous_location:
                setting_direction = (
                    f"Move the story from {previous_location} to {location}. Make the "
                    "transition motivated and visually obvious before dialogue."
                )
            else:
                setting_direction = (
                    f"Remain in {location}, but change staging, actor positions, prop "
                    "use, or the area/framing emphasis so this beat does not visually "
                    "repeat the previous one."
                )

            visual_action = action_sequence[index] if action_sequence else "auto"
            camera_hint, camera_action_hint, blocking_mode = cls._scene_direction_metadata(
                visual_action=visual_action,
                beat=beat,
                action_story=action_story,
            )
            scene_props = list(topic_props)
            if action_story and visual_action in {"chase", "run"} and "motion_lines" not in scene_props:
                scene_props.append("motion_lines")
            scene_props = scene_props[:6]

            result.append(
                CartoonSceneBrief(
                    id=scene_id,
                    location_id=location,
                    beat=beat,
                    summary=cls._bounded_scene_text(
                        (
                            f"{summary} Setting direction: {setting_direction} "
                            f"Topic: {topic.strip()}"
                        ),
                        max_chars=500,
                        fallback=str(summary),
                    ),
                    speakers=[first, second],
                    comedy_goal=cls._bounded_scene_text(
                        goal,
                        max_chars=300,
                        fallback="Advance the scene with a clear visual/comedic beat.",
                    ),
                    visual_action=visual_action,
                    camera_hint=camera_hint,
                    camera_action_hint=camera_action_hint,
                    blocking_mode=blocking_mode,
                    props=scene_props,
                    force_background_change=(
                        previous_location is not None and location != previous_location
                    ),
                )
            )

        return result

    @staticmethod
    def _forced_location_arc(*, candidates: list[str], count: int) -> list[str]:
        """Preserve every explicitly named place in narrative order.

        Unlike the generic three-world coherence limiter, this path is used only
        when the user directly names multiple places. No explicit place is
        silently discarded.
        """
        unique: list[str] = []
        for item in candidates:
            value = str(item).strip()
            if value and value not in unique:
                unique.append(value)
        if not unique:
            return []
        if count <= len(unique):
            if count == 1:
                return [unique[0]]
            # Evenly sample while retaining first/last when the user names more
            # places than the requested scene count.
            idxs = [round(i * (len(unique) - 1) / (count - 1)) for i in range(count)]
            return [unique[i] for i in idxs]

        base, extra = divmod(count, len(unique))
        result: list[str] = []
        for index, location in enumerate(unique):
            block = base + (1 if index < extra else 0)
            result.extend([location] * block)
        return result[:count]

    @staticmethod
    def _action_scene_sequence(
        *,
        premise_lock: dict[str, object],
        count: int,
    ) -> list[str]:
        if not bool(premise_lock.get("action_story", False)):
            return ["auto"] * count

        primary = str(premise_lock.get("primary_action", "chase") or "chase")
        opening = str(premise_lock.get("opening_action", primary) or primary)
        ending = str(premise_lock.get("ending_action", "reaction") or "reaction")
        if count <= 1:
            return [opening]

        result: list[str] = []
        for index in range(count):
            if index == 0:
                action = opening
            elif index == count - 1:
                action = ending
            elif primary == "chase":
                # Keep pursuit dominant, but add a search/obstacle beat around
                # two-thirds so it feels like a story instead of a loop.
                position = index / max(1, count - 1)
                action = "search" if 0.55 <= position < 0.72 else "chase"
            elif primary in {"run", "walk"}:
                action = primary
            else:
                action = primary
            result.append(action)
        return result

    @staticmethod
    def _scene_direction_metadata(
        *,
        visual_action: str,
        beat: str,
        action_story: bool,
    ) -> tuple[str, str, str]:
        if action_story:
            if visual_action == "chase":
                return "wide", "tracking_pan", "moving_chase"
            if visual_action in {"run", "walk", "enter", "exit"}:
                return "wide", "tracking_pan", "moving_group"
            if visual_action == "search":
                return "wide", "explore_pan", "moving_group"
            if visual_action in {"grab", "give", "carry"}:
                return "medium", "quick_push_in", "action_exchange"
            if visual_action in {"use_device", "open", "eat", "point"}:
                return "close_up", "prop_focus_push", "prop_focus"
            if visual_action in {"reaction", "reveal"}:
                return "reaction_close_up", "reaction_punch_in", "reaction"
            return "wide", "small_pan", "moving_group"

        if beat in {"reaction", "punchline", "callback"}:
            return "reaction_close_up", "reaction_punch_in", "reaction"
        return "medium_two_shot", "static", "dialogue"

    @staticmethod
    def _coherent_location_arc(
        *,
        candidates: list[str],
        count: int,
    ) -> list[str]:
        """Create contiguous location blocks rather than scene-by-scene cycling.

        The algorithm is intentionally semantic-agnostic: it accepts whatever
        locations the capability/router layer produced for the current topic.
        """
        unique: list[str] = []
        for item in candidates:
            value = str(item).strip()
            if value and value not in unique:
                unique.append(value)

        if not unique:
            return []
        if len(unique) == 1:
            return [unique[0]] * count

        # Reference-style episodes establish a place, play several beats, then
        # move.  Keep changes coherent, but allow a fourth authored/router world
        # when the episode has enough scenes; this avoids the one-room feel
        # without random per-line background swapping.
        max_worlds = 4 if count >= 6 else 3
        unique = unique[:max_worlds]
        base, extra = divmod(count, len(unique))
        result: list[str] = []
        for index, location in enumerate(unique):
            block = base + (1 if index < extra else 0)
            result.extend([location] * block)
        return result[:count]

    @staticmethod
    def _progression_directions(
        count: int,
    ) -> list[tuple[str, str]]:
        base = [
            (
                "Hook: reveal the protagonist's SPECIFIC personal choice or goal "
                "and why it matters to them.",
                "Create curiosity; do not use a generic profession unless the "
                "topic itself names it.",
            ),
            (
                "Introduce the first opposing expectation from family or society.",
                "Make the conflict concrete and different from scene 1.",
            ),
            (
                "Let a friend/ally suggest a funny but plausible way to prove the "
                "protagonist's choice is valid.",
                "Set up a new plan rather than repeating the original claim.",
            ),
            (
                "Escalate pressure with comparison, status, money, safety, or "
                "social reputation.",
                "Give the opposing character a distinct argument.",
            ),
            (
                "The protagonist actively tries to demonstrate the value of their "
                "choice.",
                "Show action and consequence, not another declaration.",
            ),
            (
                "The demonstration backfires or is misunderstood.",
                "Create a fresh visual/comedic reversal.",
            ),
            (
                "Pause for a strong family/friend reaction to the backfire.",
                "Use facial reaction, silence, and one sharp line.",
            ),
            (
                "Deliver the main twist/punchline: reveal an ironic contradiction "
                "in what the adults/friends were demanding.",
                "Strongest joke; no repeated wording.",
            ),
            (
                "Callback to the opening choice with a short final reversal.",
                "End decisively on a visual/verbal punchline, not explanation.",
            ),
        ]

        if count <= len(base):
            return base[:count]

        # For longer requested episodes, insert extra escalation/action beats
        # before the final three payoff beats.
        extra_needed = count - len(base)
        extras = [
            (
                "Add a new obstacle that changes the situation.",
                "Escalate with new information, not repeated dialogue.",
            ),
            (
                "Let another character propose a competing solution.",
                "Create disagreement between supporting characters.",
            ),
            (
                "Show the protagonist attempting the competing solution.",
                "Use a new action/location and a visual joke.",
            ),
        ]

        middle = [
            extras[i % len(extras)]
            for i in range(extra_needed)
        ]

        return base[:6] + middle + base[6:]

    @staticmethod
    def _beat_sequence(
        count: int,
    ) -> list[str]:
        if count <= 6:
            return [
                "setup",
                "escalation",
                "misdirection",
                "reaction",
                "punchline",
                "callback",
            ][:count]

        result = []

        for index in range(count):
            position = index / max(1, count - 1)

            if index == 0:
                beat = "setup"
            elif index == count - 1:
                beat = "callback"
            elif position < 0.22:
                beat = "setup"
            elif position < 0.52:
                beat = "escalation"
            elif position < 0.66:
                beat = "misdirection"
            elif position < 0.79:
                beat = "reaction"
            else:
                beat = "punchline"

            result.append(beat)

        return result

    @staticmethod
    def _speaker_sequence(
        *,
        topic: str,
        cast_ids: list[str],
        count: int,
    ) -> list[tuple[str, str]]:
        """Keep the explicitly named topic character as the story lead.

        V17.7 always defaulted Guddu to lead when he was present. That broke
        prompts such as "Babuji tries an AI assistant" because Babuji could
        disappear from setup/escalation even though he was the premise owner.
        """
        value = unicodedata.normalize("NFKC", topic.casefold())

        alias_map: dict[str, tuple[str, ...]] = {
            "babuji": (
                "बाबूजी", "बाबू जी", "पिताजी", "पिता",
                "babuji", "father", "dad", "papa", "papaji",
            ),
            "mai": (
                "माई", "माँ", "मां", "मम्मी",
                "mai", "mother", "mom", "mummy",
            ),
            "guddu": ("गुड्डू", "guddu"),
            "bittu": ("बिट्टू", "bittu"),
            "dadaji": ("दादाजी", "दादा जी", "dadaji", "grandpa"),
            "teacher": ("टीचर", "शिक्षक", "teacher", "masterji"),
            "doctor": ("डॉक्टर", "doctor"),
            "guest_child": ("बच्चा", "मेहमान बच्चा", "guest child"),
        }

        mentions: list[tuple[int, str]] = []
        for character_id in cast_ids:
            aliases = alias_map.get(character_id, (character_id,))
            best: int | None = None
            for alias in aliases:
                pos = value.find(unicodedata.normalize("NFKC", alias.casefold()))
                if pos >= 0 and (best is None or pos < best):
                    best = pos
            if best is not None:
                mentions.append((best, character_id))

        if mentions:
            mentions.sort(key=lambda item: item[0])
            lead = mentions[0][1]
        else:
            lead = "guddu" if "guddu" in cast_ids else cast_ids[0]

        preferred = [item for item in cast_ids if item != lead]
        if not preferred:
            preferred = [lead]

        pairs: list[tuple[str, str]] = []
        for index in range(count):
            other = preferred[index % len(preferred)]
            if other == lead and len(cast_ids) > 1:
                other = next(item for item in cast_ids if item != lead)
            pairs.append((lead, other))

        return pairs

    @staticmethod
    def _location_sequence(
        *,
        topic: str,
        count: int,
    ) -> list[str]:
        # Fallback only. Normal V11+ planning receives capability-derived
        # locations from resolve_story_profile(). Keep this path generic too.
        profile = resolve_story_profile(
            topic=topic,
            language_code="english",
        )
        candidates = [str(x) for x in profile.get("locations", [])]
        available = set(background_ids())
        candidates = [item for item in candidates if item in available]
        if not candidates:
            candidates = [item for item in background_ids()][:3]
        return CartoonStoryPlanner._coherent_location_arc(
            candidates=candidates,
            count=count,
        )


    @classmethod
    def _v18_spine_prompt(
        cls,
        *,
        topic: str,
        language: CartoonLanguagePack,
        briefs: list[CartoonSceneBrief],
    ) -> str:
        scene_rows = [
            {
                "location": b.location_id,
                "beat": b.beat,
                "speakers": list(b.speakers),
                "summary": b.summary[:220],
                "goal": b.comedy_goal[:180],
            }
            for b in briefs
        ]
        ai_home = cls._v1710_is_ai_home_assistant_topic(topic)
        special = (
            "This is an AI-home-assistant misunderstanding story. For EVERY beat, trigger must explicitly be a short phone/AI instruction. "
            "Babuji's misunderstanding must be different in every beat, use a different household object/action where practical, and cause a visible consequence. "
            "The AI is only the instruction source; family members must not become the AI."
            if ai_home
            else
            "Keep every beat inside the exact topic/premise. Each beat must use a distinct concrete trigger/mistake/consequence rather than paraphrasing the previous beat."
        )
        return f"""
V18 EPISODE SPINE. Return JSON only, no dialogue.
TOPIC: {topic}
LANGUAGE: {language.display_name}
SCENE BRIEFS: {json.dumps(scene_rows, ensure_ascii=False)}

Return exactly {len(briefs)} ordered beats:
{{"beats":[{{"trigger":"...","misunderstanding":"...","consequence":"...","button":"..."}}]}}

RULES:
- One beat per supplied scene, in the same order. Caller owns scene IDs.
- Make a causal comedy arc: each consequence becomes the starting situation for the next beat.
- Every beat must materially change the visible situation.
- Use concrete objects/actions from the topic/world; avoid abstract filler.
- Do not repeat the same object, wording, mistake mechanism or punchline in adjacent beats.
- Final beat must callback to an earlier object/action with a new meaning and end decisively.
- No dialogue, camera, emotion, pose, SFX or production metadata.
- {special}
"""

    async def _v18_build_episode_spine(
        self,
        *,
        topic: str,
        language: CartoonLanguagePack,
        briefs: list[CartoonSceneBrief],
        llm_fast_ready: bool,
    ) -> list[dict[str, str]]:
        """Build one compact causal plan before any scene dialogue is generated.

        This replaces the old generate->repair-each-scene pattern. A failed spine
        call is non-fatal: deterministic scene briefs remain the fallback.
        """
        if not llm_fast_ready:
            return []
        prompt = self._v18_spine_prompt(topic=topic, language=language, briefs=briefs)
        try:
            spine = await self._llm.generate_fast_structured(
                prompt=prompt,
                response_model=_V18EpisodeSpine,
                system_prompt=(
                    f"Design a concise original {language.display_name} comedy episode arc. "
                    "Return valid compact JSON only; do not write dialogue."
                ),
                rescue=False,
            )
        except Exception as exc:
            print(
                "[CARTOON STORY SPINE V18] "
                f"status=FALLBACK_TO_BRIEFS; error={type(exc).__name__}; "
                f"reason={str(exc)[:180]!r}"
            )
            return []

        rows: list[dict[str, str]] = []
        for beat in spine.beats[:len(briefs)]:
            rows.append({
                "trigger": beat.trigger.strip(),
                "misunderstanding": beat.misunderstanding.strip(),
                "consequence": beat.consequence.strip(),
                "button": beat.button.strip(),
            })
        if len(rows) < len(briefs):
            print(
                "[CARTOON STORY SPINE V18] "
                f"status=PARTIAL; beats={len(rows)}/{len(briefs)}; missing_beats=USE_BRIEFS"
            )
        else:
            print(
                "[CARTOON STORY SPINE V18] "
                f"status=PASS; beats={len(rows)}; causal_arc=ON; per_batch_repairs=OFF"
            )
        return rows

    @staticmethod
    def _v18_core_semantic_reasons(reasons: list[str]) -> list[str]:
        """Reasons that must be fully removed before a rewrite can be accepted."""
        core_tokens = (
            "premise dialogue anchor",
            "off-premise drift",
            "topic-named protagonist",
            "AI-assistant instruction source",
            "Babuji too little agency",
            "omits topic-named protagonist",
            "mostly Romanized",
        )
        return [
            reason for reason in reasons
            if any(token in reason for token in core_tokens)
        ]

    @staticmethod
    def _v173_creative_prompt(
        *, topic: str, language: CartoonLanguagePack, compact_cast: list[dict[str, object]],
        briefs: list[CartoonSceneBrief], continuity: str, recent_lines: list[str],
        target_scene_seconds: float, is_final: bool,
        spine_beat: dict[str, str] | None = None,
        episode_spine: list[dict[str, str]] | None = None,
    ) -> str:
        # V17.6 assigns a different joke engine to successive scenes. The LLM
        # still owns the actual joke, but this prevents every batch from using
        # the same misunderstanding/reaction template.
        joke_cycle = (
            "confidently-wrong assumption",
            "literal interpretation with social reversal",
            "prop/object gag with consequence",
            "status flip: the confident person becomes the confused one",
            "interruption or reveal that changes the plan",
            "callback to an earlier action/object with a new meaning",
        )
        compact_briefs = [
            {
                "id": b.id,
                "location": b.location_id,
                "beat": b.beat,
                "speakers": list(b.speakers),
                "summary": b.summary[:220],
                "comedy_goal": b.comedy_goal[:180],
                "joke_mechanism": joke_cycle[(int(b.id) - 1) % len(joke_cycle)],
            }
            for b in briefs
        ]
        cast = [{"id": c.get("id"), "name": c.get("display_name"), "traits": c.get("traits", [])} for c in compact_cast]
        final = "The final scene must land a strong callback/payoff." if is_final else "Do not finish the whole story yet."
        protagonist = CartoonStoryPlanner._topic_named_protagonist(topic) or (
            briefs[0].speakers[0] if briefs and briefs[0].speakers else ""
        )
        beat_contract = json.dumps(spine_beat or {}, ensure_ascii=False)
        arc_contract = json.dumps(
            [
                {
                    "trigger": item.get("trigger", "")[:90],
                    "consequence": item.get("consequence", "")[:90],
                }
                for item in (episode_spine or [])
            ],
            ensure_ascii=False,
        )
        return f"""
Write ONLY the spoken creative core for an original Indian comedy cartoon.
TOPIC: {topic}
LANGUAGE: {language.display_name}
PROTAGONIST: {protagonist}
CAST: {json.dumps(cast, ensure_ascii=False)}
SCENE: {json.dumps({k: v for k, v in compact_briefs[0].items() if k != "id"}, ensure_ascii=False)}
V18 BEAT CONTRACT: {beat_contract}
V18 EPISODE ARC (trigger/consequence only): {arc_contract}
PREVIOUS: {(continuity or 'Opening: establish the conflict immediately.')[-380:]}
AVOID REUSING: {json.dumps(recent_lines[-3:], ensure_ascii=False)}

Return ONE scene JSON exactly like:
{{"dialogue":[{{"character_id":"babuji","text":"...","emotion":"smirk"}}],"reaction_character_id":"guddu","reaction_expression":"shocked"}}

RULES:
- Do NOT output a scene id and do NOT wrap the answer in a scenes array. The caller owns the scene number.
- Write only the one supplied scene and only listed speaker IDs.
- Each scene: 6-8 reciprocal dialogue turns, about 50-65 spoken words for ~{target_scene_seconds:.0f}s.
- For Hindi output, write primarily in natural Devanagari Hindi. Keep only common tech/product words such as AI, assistant, phone or app in Latin script when useful. Do not write whole Hindi sentences in Roman letters.
- Mostly 5-14 word actable lines, not speeches.
- PROTAGONIST must drive the exact TOPIC action in every scene. Do not silently transfer the premise to Guddu or another supporting character.
- Character voices: Babuji literal old-school authority; Guddu sharp but respectful; Bittu confidently wrong; Mai dry practical.
- Use the supplied scene's assigned joke_mechanism and make it concrete.
- If V18 BEAT CONTRACT is non-empty, follow its trigger -> misunderstanding -> consequence -> button exactly enough that another scene cannot substitute for this one.
- Respect the full V18 EPISODE ARC: do not reuse an earlier beat's object/action as the main new gag unless the final scene is intentionally calling it back.
- Each scene needs a concrete trigger/object/goal, a mid-scene comic reversal, and a short ending button.
- Mention at least one concrete noun/phrase from TOPIC inside the spoken dialogue (for example AI assistant, phone, goat, bag, mela); never replace the premise with vague filler like "something changed".
- For an AI-home-assistant premise, at least one line must explicitly establish what the AI/phone said (for example `AI ने कहा...`), then Babuji must visibly misunderstand that instruction. Supporting family characters may react or correct him but must not invent the instruction source.
- Do not invent an unrelated subplot (books, school, career, shopping, etc.) unless TOPIC itself establishes it.
- Cause-and-effect only: a line should respond to the previous action/claim instead of restarting the topic.
- Two-person scenes must alternate naturally; never let one character lecture for 3+ turns in a row.
- Every scene changes the situation. Do not explain the joke, add a moral, or summarize the lesson after the punchline.
- Avoid generic filler such as repeated greetings, repeated 'arey yaar', or characters simply saying they are confused.
- Original jokes only; no copied memes, films, creators or famous punchlines.
- No camera, pose, SFX, location prose or production metadata in the output.
- {final}
"""

    @staticmethod
    def _v173_creative_rescue_prompt(
        *, topic: str, language: CartoonLanguagePack, compact_cast: list[dict[str, object]],
        briefs: list[CartoonSceneBrief], continuity: str, is_final: bool,
        spine_beat: dict[str, str] | None = None,
    ) -> str:
        scene_lines = []
        for b in briefs:
            scene_lines.append(
                f"speakers={','.join(b.speakers)}; beat={b.beat}; goal={b.comedy_goal[:110]}"
            )
        protagonist = CartoonStoryPlanner._topic_named_protagonist(topic) or (
            briefs[0].speakers[0] if briefs and briefs[0].speakers else ""
        )
        beat_contract = json.dumps(spine_beat or {}, ensure_ascii=False)
        return (
            f"Return JSON only. Topic: {topic}. Language: {language.display_name}. Protagonist: {protagonist}. V18 beat={beat_contract}. "
            + " | ".join(scene_lines)
            + ". Write 6-8 short reciprocal natural dialogue turns for this ONE supplied scene using only its speakers. "
              "Use at least one concrete noun/phrase from the topic in the spoken lines. Follow the V18 beat when present. The protagonist must drive the topic action; do not switch to an unrelated subplot. If this is an AI-home premise, explicitly say what AI/phone instructed before Babuji misunderstands it. "
              "For Hindi, write primarily in Devanagari Hindi, allowing only common tech words in Latin script. "
              "Start from a concrete action/problem, create one wrong assumption, reverse it mid-scene, and end on a short punch. "
              "No lecture, moral, summary, repeated filler, or three consecutive turns by one speaker. Original family-safe comedy. "
              "Shape: {\"dialogue\":[{\"character_id\":\"babuji\",\"text\":\"...\",\"emotion\":\"smirk\"}],"
              "\"reaction_character_id\":\"babuji\",\"reaction_expression\":\"shocked\"}. "
              "Do not output id, scene, or scenes wrapper."
        )

    @staticmethod
    def _v176_fast_repair_prompt(
        *, topic: str, language: CartoonLanguagePack, briefs: list[CartoonSceneBrief],
        current_batch: CartoonSceneBatch, issues: list[str], continuity: str, is_final: bool,
    ) -> str:
        brief_rows = [
            {
                "speakers": list(b.speakers),
                "beat": b.beat,
                "goal": b.comedy_goal[:150],
                "summary": b.summary[:180],
            }
            for b in briefs
        ]
        current = [
            {
                "dialogue": [
                    {"character_id": line.character_id, "text": line.text, "emotion": line.emotion}
                    for line in scene.dialogue
                ],
            }
            for scene in current_batch.scenes
        ]
        final = "Final scene: pay off an earlier action/object with a fresh callback." if is_final else "Do not resolve the whole episode yet."
        return f"""
V17.10 FAST COMEDY REPAIR. Return one-scene JSON only; no scene id and no scenes wrapper.
TOPIC: {topic}
LANGUAGE: {language.display_name}
BRIEFS: {json.dumps(brief_rows, ensure_ascii=False)}
CONTINUITY: {(continuity or 'opening conflict')[-320:]}
CURRENT: {json.dumps(current, ensure_ascii=False)}
PROBLEMS: {json.dumps(issues[:8], ensure_ascii=False)}
RULES:
- Caller owns the scene ID. Do not output an id. Use only allowed speakers.
- 6-8 reciprocal turns and ~50-65 spoken words per scene.
- Replace flat/filler lines instead of merely adding more words.
- Fix every semantic/premise problem listed in PROBLEMS; do not preserve unrelated subplots.
- For Hindi, use primarily natural Devanagari Hindi; only common tech/product words may stay in Latin script.
- Keep the topic-named protagonist responsible for the premise action.
- Concrete trigger -> wrong assumption/attempt -> reaction -> escalation -> reversal -> punch.
- At least one mid-scene laugh beat and one short ending button.
- No three consecutive turns by one speaker, no lecture, moral, summary, or joke explanation.
- Preserve topic, object/goal, relationships and scene brief.
- {final}
"""

    @classmethod
    def _v1710_targeted_repair_prompt(
        cls,
        *,
        topic: str,
        language: CartoonLanguagePack,
        brief: CartoonSceneBrief,
        current_scene: CartoonScene,
        reasons: list[str],
        previous_scene: CartoonScene | None,
        next_scene: CartoonScene | None,
        spine_beat: dict[str, str] | None = None,
    ) -> str:
        current = [
            {"speaker": line.character_id, "text": line.text}
            for line in current_scene.dialogue
        ]
        prev_lines = [line.text for line in (previous_scene.dialogue[-2:] if previous_scene else [])]
        next_lines = [line.text for line in (next_scene.dialogue[:2] if next_scene else [])]
        ai_home = cls._v1710_is_ai_home_assistant_topic(topic)
        special = (
            "This is an AI-home-assistant misunderstanding story. The AI is an off-screen phone/device instruction source; family characters never impersonate it. "
            "Make this scene contain one clear AI instruction, Babuji's specific wrong interpretation, a visible household action/consequence, and a family reaction. Use a new object/action unless this is the final callback."
            if ai_home else
            "Keep the exact premise and make the scene causally advance the same story."
        )
        return f"""
V17.10 TARGETED WEAK-SCENE REWRITE. Return one-scene JSON only: {{"dialogue":[...],"reaction_character_id":"...","reaction_expression":"..."}}. Never output scene id or scenes wrapper.
TOPIC: {topic}
LANGUAGE: {language.display_name}
SCENE: id={brief.id}; beat={brief.beat}; location={brief.location_id}; speakers={brief.speakers}
SCENE GOAL: {brief.comedy_goal}
CURRENT DIALOGUE: {json.dumps(current, ensure_ascii=False)}
QUALITY FAILURES: {json.dumps(reasons, ensure_ascii=False)}
PREVIOUS END: {json.dumps(prev_lines, ensure_ascii=False)}
NEXT START: {json.dumps(next_lines, ensure_ascii=False)}
V18 BEAT CONTRACT: {json.dumps(spine_beat or {}, ensure_ascii=False)}
RULES:
- Rewrite the whole scene; do not patch individual lines.
- If V18 BEAT CONTRACT is non-empty, preserve its exact trigger -> misunderstanding -> consequence -> button; do not invent a replacement subplot.
- 5-7 reciprocal turns, roughly 45-65 spoken words.
- Use only allowed speakers. Babuji must actively cause or react to the premise when he is an allowed speaker.
- Fix every listed failure. Do not repeat the phrase named in a repeated-phrase failure.
- Do not copy wording from PREVIOUS END or NEXT START.
- Natural Devanagari Hindi for Hindi; common tech term AI may stay Latin.
- Concrete instruction/action -> wrong interpretation -> visible consequence -> reaction -> reversal/button.
- No lecture, summary, moral, generic filler, or repeated sentence skeleton.
- {special}
"""

    @classmethod
    def _v1711_compact_targeted_rescue_prompt(
        cls,
        *,
        topic: str,
        language: CartoonLanguagePack,
        brief: CartoonSceneBrief,
        current_scene: CartoonScene,
        reasons: list[str],
    ) -> str:
        current = [
            {"speaker": line.character_id, "text": line.text}
            for line in current_scene.dialogue
        ]
        ai_rule = (
            "Include one explicit AI/assistant instruction source and Babuji's wrong literal action."
            if cls._v1710_is_ai_home_assistant_topic(topic) else
            "Keep the exact topic action and causal continuity."
        )
        return f"""
Return JSON only: {{"dialogue":[{{"character_id":"{brief.speakers[0]}","text":"...","emotion":"smirk"}}]}}
Rewrite scene {brief.id}. Language={language.display_name}. Allowed speakers={list(brief.speakers)}.
Topic={topic}
Problems={json.dumps(reasons[:4], ensure_ascii=False)}
Current={json.dumps(current, ensure_ascii=False)}
Write exactly 5 short reciprocal turns, about 45-55 spoken words total. Fix the listed problems, avoid the repeated phrase, use natural Devanagari Hindi, and end on a comic button. {ai_rule}
No id, no scene/scenes wrapper, no reaction fields, no prose outside JSON.
"""

    @classmethod
    def _v1711_compact_repair_rescue_prompt(
        cls,
        *,
        topic: str,
        language: CartoonLanguagePack,
        brief: CartoonSceneBrief,
        reasons: list[str],
    ) -> str:
        ai_rule = (
            "AI is an off-screen instruction source; Babuji misunderstands it and causes a visible household consequence."
            if cls._v1710_is_ai_home_assistant_topic(topic) else
            "Keep the exact premise and advance it causally."
        )
        return f"""
Return JSON only: {{"dialogue":[{{"character_id":"{brief.speakers[0]}","text":"...","emotion":"smirk"}}]}}
One scene only. Language={language.display_name}. Speakers={list(brief.speakers)}. Topic={topic}
Problems={json.dumps(reasons[:4], ensure_ascii=False)}
Write exactly 5 short reciprocal turns, 45-55 words, natural Hindi, one setup, one wrong assumption, one visible consequence, one reversal, one punchline. {ai_rule}
No id/wrapper/reaction/prose.
"""

    @classmethod
    def _v179_expand_single_creative(
        cls, *, creative: _V179SingleCreative, brief: CartoonSceneBrief,
        language: CartoonLanguagePack, topic: str, target_scene_seconds: float,
    ) -> CartoonSceneBatch:
        """Expand one ID-less creative payload into the caller-owned brief."""
        allowed_emotions = {
            "neutral", "happy", "smirk", "angry", "shocked", "confused", "embarrassed",
            "laughing", "serious", "suspicious", "proud", "sad", "excited",
        }
        dialogue: list[CartoonDialogueLine] = []
        # Cap at 8 performance turns even though the parser accepts up to 10 so
        # a slightly overlong valid JSON response is recoverable rather than lost.
        for index, line in enumerate(creative.dialogue[:8]):
            speaker = (
                line.character_id
                if line.character_id in brief.speakers
                else brief.speakers[index % len(brief.speakers)]
            )
            emotion = line.emotion if line.emotion in allowed_emotions else ("smirk" if index % 3 == 0 else "neutral")
            pose = "pointing" if index in {1, 4} else ("thinking" if emotion in {"confused", "suspicious"} else "idle")
            dialogue.append(CartoonDialogueLine(
                character_id=speaker,
                text=line.text.strip(),
                emotion=emotion,
                pose=pose,
                pause_after_seconds=(0.34 if index == min(len(creative.dialogue), 8) - 1 else 0.18),
            ))

        reaction = None
        if brief.beat in {"reaction", "punchline", "callback"}:
            rc = (
                creative.reaction_character_id
                if creative.reaction_character_id in brief.speakers
                else brief.speakers[-1]
            )
            rexp = creative.reaction_expression if creative.reaction_expression in allowed_emotions else "shocked"
            reaction = CartoonReaction(
                character_id=rc, expression=rexp, duration_seconds=0.7,
                camera="reaction_close_up", sfx="comic_sting",
            )

        return CartoonSceneBatch(scenes=[CartoonScene(
            id=brief.id,
            location_id=brief.location_id,
            beat=brief.beat,
            camera=brief.camera_hint,
            shot_duration_seconds=target_scene_seconds,
            setup=brief.summary,
            dialogue=dialogue,
            reaction=reaction,
            sfx_cues=(["comic_sting"] if brief.beat in {"punchline", "callback"} else []),
            camera_action=brief.camera_action_hint,
            transition="hard_cut",
            visual_action=brief.visual_action,
            props=list(brief.props),
            blocking_mode=brief.blocking_mode,
        )])

    @classmethod
    def _v173_expand_creative_batch(
        cls, *, creative: _V173CreativeBatch, briefs: list[CartoonSceneBrief],
        language: CartoonLanguagePack, topic: str, target_scene_seconds: float,
    ) -> CartoonSceneBatch:
        allowed_emotions = {
            "neutral", "happy", "smirk", "angry", "shocked", "confused", "embarrassed",
            "laughing", "serious", "suspicious", "proud", "sad", "excited",
        }
        by_id = {scene.id: scene for scene in creative.scenes}
        scenes: list[CartoonScene] = []
        for brief in briefs:
            item = by_id.get(brief.id)
            if item is None:
                scenes.append(cls._fallback_scene_from_brief(
                    brief=brief, language=language, topic=topic,
                    target_scene_seconds=target_scene_seconds, variant=brief.id,
                ))
                continue
            dialogue: list[CartoonDialogueLine] = []
            for index, line in enumerate(item.dialogue):
                speaker = line.character_id if line.character_id in brief.speakers else brief.speakers[index % len(brief.speakers)]
                emotion = line.emotion if line.emotion in allowed_emotions else ("smirk" if index % 3 == 0 else "neutral")
                pose = "pointing" if index in {1, 4} else ("thinking" if emotion in {"confused", "suspicious"} else "idle")
                dialogue.append(CartoonDialogueLine(
                    character_id=speaker, text=line.text.strip(), emotion=emotion, pose=pose,
                    pause_after_seconds=(0.34 if index == len(item.dialogue) - 1 else 0.18),
                ))
            reaction = None
            if brief.beat in {"reaction", "punchline", "callback"}:
                rc = item.reaction_character_id if item.reaction_character_id in brief.speakers else brief.speakers[-1]
                rexp = item.reaction_expression if item.reaction_expression in allowed_emotions else "shocked"
                reaction = CartoonReaction(
                    character_id=rc, expression=rexp, duration_seconds=0.7,
                    camera="reaction_close_up", sfx="comic_sting",
                )
            scenes.append(CartoonScene(
                id=brief.id, location_id=brief.location_id, beat=brief.beat,
                camera=brief.camera_hint, shot_duration_seconds=target_scene_seconds,
                setup=brief.summary, dialogue=dialogue, reaction=reaction,
                sfx_cues=(["comic_sting"] if brief.beat in {"punchline", "callback"} else []),
                camera_action=brief.camera_action_hint, transition="hard_cut",
                visual_action=brief.visual_action, props=list(brief.props),
                blocking_mode=brief.blocking_mode,
            ))
        return CartoonSceneBatch(scenes=scenes)

    @staticmethod
    def _batch_prompt(
        *,
        topic: str,
        language: CartoonLanguagePack,
        compact_cast: list[dict[str, object]],
        briefs: list[CartoonSceneBrief],
        continuity: str,
        recent_lines: list[str],
        target_scene_seconds: float,
        is_final: bool,
    ) -> str:
        forbidden = recent_lines[-5:]

        final_rule = (
            "The final scene must land a callback and finish on a short "
            "visual/verbal punchline."
            if is_final
            else "Do not resolve the full story in this batch."
        )

        premise_lock = CartoonStoryPlanner._resolve_story_premise(
            topic=topic,
            language_code=language.code,
        )

        return f"""
TOPIC: {topic}
LANGUAGE: {language.display_name}
NATIVE WRITING RULE: {language.native_writing_rule}
CHANNEL CREATIVE DIRECTION: {CartoonStoryPlanner._compact_channel_direction(language.code)}

STORY PREMISE LOCK - DO NOT CHANGE:
{json.dumps(CartoonStoryPlanner._compact_premise_lock_for_prompt(premise_lock), ensure_ascii=False)}

UNIVERSAL ROUTE:
- primary={premise_lock.get("route", "general_comedy")}
- audience={premise_lock.get("audience", "all")}
- tags={premise_lock.get("tags", [])}
- pacing={premise_lock.get("pacing", "balanced")}
- Do not force family/career grammar onto school, animal, magic, adventure, mystery or kids topics.

CONTINUITY CONTRACT:
- Preserve the same core premise, objective, conflict, relationships, important
  objects and consequences across scenes.
- Never force career/family/school grammar unless it is actually present in the
  topic/premise. This contract must work for ANY topic or capability world.
- Treat a location change in the scene briefs as a real story transition: show
  arrival/movement/context before dialogue.
- When two briefs use the same location, do NOT replay the same blocking. Change
  staging, actor positions, prop interaction or camera emphasis while preserving
  object/character continuity.
- Do not introduce unrelated subplots merely to create visual variety.

CAST:
{json.dumps(compact_cast, ensure_ascii=False)}

SCENE BRIEFS:
{json.dumps(
    [brief.model_dump() for brief in briefs],
    ensure_ascii=False,
)}

PREVIOUS CONTINUITY:
{(continuity or "Opening batch. Establish the specific conflict immediately.")[-700:]}

DO NOT REUSE THESE EARLIER LINES OR CLOSE PARAPHRASES:
{json.dumps(forbidden, ensure_ascii=False)}

QUALITY RULES:
- Return exactly {len(briefs)} scenes with the exact scene IDs.
- Follow EACH scene brief's unique summary/comedy_goal; every scene must
  materially advance the story.
- Use only the character IDs and location IDs shown in each brief.
# V17 legacy target was 45-60 SPOKEN words; V17.1 raises the floor for real TTS runtime.
- For hindi_mass, write 6-8 natural dialogue turns per scene; aim for 50-65 SPOKEN words per ~20s scene.
- In hindi_mass, most spoken lines should be about 8-16 words: short enough to act, long enough to sound like real conversation.
- Build jokes from setup -> misunderstanding -> reaction -> escalation -> callback/payoff; do not write generic filler or moral-summary lines.
- Keep each line playable; use reactions/interruptions, but do not collapse the requested runtime.
- Target about {target_scene_seconds:.0f}s of story performance per scene.
- Do NOT repeat the protagonist's career/choice declaration scene after scene.
- Do NOT reuse the same reply, joke template, or sentence structure.
- Give different characters different viewpoints and vocabulary.
- Dialogue must sound naturally SPOKEN in {language.display_name}, not like a
  literal translation.
- Use emotion and pose changes. Avoid making every line "neutral"/"idle".
- Reaction/punchline/callback scenes must include a visible reaction.
- Use camera movement/SFX sparingly for jokes, not every line.
- No narrator-heavy exposition, PPT, title cards, documentary grammar.
- Original dialogue and story construction only.
- {final_rule}
"""

    @staticmethod
    def _repair_prompt(
        *,
        topic: str,
        language: CartoonLanguagePack,
        compact_cast: list[dict[str, object]],
        briefs: list[CartoonSceneBrief],
        continuity: str,
        recent_lines: list[str],
        current_batch: CartoonSceneBatch,
        issues: list[str],
        target_scene_seconds: float,
        is_final: bool,
    ) -> str:
        return f"""
Rewrite ONLY this weak batch.

TOPIC: {topic}
LANGUAGE: {language.display_name}
NATIVE WRITING RULE: {language.native_writing_rule}
CHANNEL CREATIVE DIRECTION: {CartoonStoryPlanner._compact_channel_direction(language.code)}

CAST:
{json.dumps(compact_cast, ensure_ascii=False)}

MANDATORY SCENE BRIEFS:
{json.dumps(
    [brief.model_dump() for brief in briefs],
    ensure_ascii=False,
)}

PREVIOUS CONTINUITY:
{continuity}

RECENT LINES THAT MUST NOT BE REUSED:
{json.dumps(recent_lines[-10:], ensure_ascii=False)}

CURRENT WEAK BATCH:
{current_batch.model_dump_json(indent=2)}

DETECTED QUALITY PROBLEMS:
{json.dumps(issues, ensure_ascii=False)}

REPAIR RULES:
- Return the same exact scene IDs.
- For hindi_mass: 6-8 natural dialogue turns and 50-65 spoken words per scene; otherwise 3-5 turns.
- Each scene must advance its unique brief.
- No repeated career declaration or repeated reply template.
- Different characters must sound different.
- Use expressive emotion/pose values.
- Target about {target_scene_seconds:.0f}s performance per scene.
- Reaction/punchline/callback scenes need a reaction.
- {'Land the final callback strongly.' if is_final else 'Do not resolve the full story yet.'}
"""

    @classmethod
    def _v176_hindi_comedy_issues(
        cls,
        *,
        batch: CartoonSceneBatch,
    ) -> list[str]:
        issues: list[str] = []
        for scene in batch.scenes:
            turns = len(scene.dialogue)
            words = dialogue_word_count([scene])
            if turns < 5:
                issues.append(
                    f"scene {scene.id} has fewer than 5 Hindi comedy turns: {turns}"
                )
            if words < 45:
                issues.append(
                    f"scene {scene.id} underfilled Hindi comedy dialogue: turns={turns}, words={words}"
                )
            if words > 92:
                issues.append(
                    f"scene {scene.id} is over-written Hindi comedy dialogue: words={words}"
                )

            speaker_ids = [str(line.character_id) for line in scene.dialogue]
            if turns >= 4 and len(set(speaker_ids)) <= 1:
                issues.append(f"scene {scene.id} is single-speaker instead of reciprocal comedy")
            longest_run = 0
            run = 0
            previous = None
            for speaker in speaker_ids:
                if speaker == previous:
                    run += 1
                else:
                    run = 1
                    previous = speaker
                longest_run = max(longest_run, run)
            if longest_run >= 3:
                issues.append(
                    f"scene {scene.id} has a speaker run of {longest_run}; dialogue feels like a lecture"
                )

            long_lines = 0
            for line in scene.dialogue:
                wc = len(re.findall(r"[\w\u0900-\u097f]+", line.text, flags=re.UNICODE))
                if wc > 20:
                    long_lines += 1
            if long_lines >= 2:
                issues.append(
                    f"scene {scene.id} has {long_lines} expositional long lines instead of short comic turns"
                )
        return cls._dedupe(issues)

    @classmethod
    def _quality_issues(
        cls,
        *,
        batch: CartoonSceneBatch,
        recent_lines: list[str],
        language: CartoonLanguagePack,
        topic: str | None = None,
    ) -> list[str]:
        issues: list[str] = []
        history = [
            cls._dialogue_key(value)
            for value in recent_lines
            if value.strip()
        ]
        current_keys: list[str] = []

        neutral_lines = 0
        total_lines = 0

        for scene in batch.scenes:
            if len(scene.dialogue) < 2:
                issues.append(
                    f"scene {scene.id} has fewer than 2 dialogue turns"
                )

            if (
                scene.beat in {
                    "reaction",
                    "punchline",
                    "callback",
                }
                and scene.reaction is None
            ):
                issues.append(
                    f"scene {scene.id} lacks required reaction"
                )

            for line in scene.dialogue:
                total_lines += 1

                if line.emotion == "neutral":
                    neutral_lines += 1

                key = cls._dialogue_key(line.text)

                if not key:
                    continue

                for previous in history + current_keys:
                    if cls._too_similar(key, previous):
                        issues.append(
                            f"repeated/near-duplicate dialogue in scene "
                            f"{scene.id}: {line.text[:70]!r}"
                        )
                        break

                current_keys.append(key)

        if total_lines >= 4 and neutral_lines / total_lines >= 0.80:
            issues.append(
                "at least 80% of dialogue emotions are neutral"
            )

        if os.getenv("CONTENT_FACTORY_CARTOON_CHANNEL", "auto").strip().lower() == "hindi_mass":
            issues.extend(cls._v176_hindi_comedy_issues(batch=batch))

        if topic:
            issues.extend(
                cls._premise_continuity_issues(
                    batch=batch,
                    language=language,
                    topic=topic,
                )
            )
            issues.extend(
                cls._v178_semantic_issues(
                    batch=batch,
                    language=language,
                    topic=topic,
                )
            )
            issues.extend(
                cls._v1710_ai_home_issues(
                    batch=batch,
                    topic=topic,
                )
            )

        return cls._dedupe(issues)

    @staticmethod
    def _dialogue_key(
        value: str,
    ) -> str:
        normalized = unicodedata.normalize(
            "NFKC",
            value.casefold(),
        )
        return "".join(
            ch
            for ch in normalized
            if (
                unicodedata.category(ch)[0] in {"L", "N"}
                or ch.isspace()
            )
        ).strip()

    @staticmethod
    def _too_similar(
        left: str,
        right: str,
    ) -> bool:
        if not left or not right:
            return False

        if left == right:
            return True

        # Avoid over-triggering on very short normal phrases.
        if min(len(left), len(right)) < 18:
            return False

        return (
            SequenceMatcher(
                None,
                left,
                right,
            ).ratio()
            >= 0.78
        )

    @staticmethod
    def _dedupe(
        values: list[str],
    ) -> list[str]:
        result = []
        seen = set()

        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)

        return result

    @classmethod
    def _apply_performance_direction(
        cls,
        *,
        batch: CartoonSceneBatch,
        briefs: list[CartoonSceneBrief],
        target_scene_seconds: float,
    ) -> None:
        brief_by_id = {
            brief.id: brief
            for brief in briefs
        }

        for scene in batch.scenes:
            brief = brief_by_id[scene.id]

            scene.shot_duration_seconds = target_scene_seconds

            # Deterministic direction prevents flat neutral/static output
            # without another LLM call.
            if scene.beat == "setup":
                camera = "medium_two_shot"
                camera_action = "static"
                default_emotions = (
                    "happy",
                    "confused",
                )
            elif scene.beat == "escalation":
                camera = "medium"
                camera_action = "small_pan"
                default_emotions = (
                    "confused",
                    "angry",
                )
            elif scene.beat == "misdirection":
                camera = "close_up"
                camera_action = "quick_push_in"
                default_emotions = (
                    "smirk",
                    "confused",
                )
            elif scene.beat == "reaction":
                camera = "reaction_close_up"
                camera_action = "reaction_punch_in"
                default_emotions = (
                    "shocked",
                    "confused",
                )
            elif scene.beat == "punchline":
                camera = "close_up"
                camera_action = "quick_push_in"
                default_emotions = (
                    "smirk",
                    "shocked",
                )
            else:
                camera = "medium_two_shot"
                camera_action = "slight_pull_back"
                default_emotions = (
                    "laughing",
                    "shocked",
                )

            scene.camera = camera
            scene.camera_action = camera_action

            for index, line in enumerate(scene.dialogue):
                if line.emotion == "neutral":
                    line.emotion = default_emotions[
                        index % len(default_emotions)
                    ]

                # V11.5: do not leave an entire spoken scene on idle/thinking.
                # Use the existing pose vocabulary to create visible gesture
                # contrast between successive lines without inventing assets.
                if line.pose in {"idle", "thinking", "pointing"}:
                    emotion = str(line.emotion).casefold()
                    if emotion in {"shocked", "surprised"}:
                        line.pose = "shocked"
                    elif emotion in {"confused", "suspicious"}:
                        line.pose = "thinking"
                    elif emotion in {"angry", "serious"}:
                        line.pose = "pointing"
                    elif emotion in {"happy", "laughing"}:
                        line.pose = "shocked" if index % 3 == 2 else "pointing"
                    else:
                        pose_cycle = ("thinking", "pointing", "shocked")
                        line.pose = pose_cycle[(scene.id + index) % len(pose_cycle)]

                if scene.beat in {"reaction", "punchline", "callback"} and index == len(scene.dialogue) - 1:
                    # The renderer clamps audio pauses to its natural range, but
                    # keeping a stronger authored tail makes punchline intent
                    # survive saved plans and future timing policies.
                    line.pause_after_seconds = max(float(line.pause_after_seconds), 0.40)

            if (
                scene.beat in {
                    "reaction",
                    "punchline",
                    "callback",
                }
                and scene.reaction is None
            ):
                reacting_character = (
                    scene.dialogue[-1].character_id
                    if scene.dialogue
                    else brief.speakers[-1]
                )

                expression = (
                    "shocked"
                    if scene.beat != "callback"
                    else "laughing"
                )

                scene.reaction = CartoonReaction(
                    character_id=reacting_character,
                    expression=expression,
                    duration_seconds=0.7,
                    camera="reaction_close_up",
                    sfx=(
                        "pop"
                        if scene.beat == "reaction"
                        else "comic_sting"
                    ),
                )

            clean_sfx = [
                cue
                for cue in scene.sfx_cues
                if cue in cls._ALLOWED_SFX
            ]

            if (
                scene.beat in {
                    "punchline",
                    "callback",
                }
                and not clean_sfx
            ):
                clean_sfx = ["comic_sting"]

            scene.sfx_cues = clean_sfx[:2]

    @staticmethod
    def _continuity_tail(
        batch: CartoonSceneBatch,
    ) -> str:
        if not batch.scenes:
            return ""

        scene = batch.scenes[-1]

        lines = [
            line.text.strip()
            for line in scene.dialogue[-3:]
            if line.text.strip()
        ]

        return (
            f"Previous scene {scene.id} at {scene.location_id}; "
            f"beat={scene.beat}; dialogue="
            + " / ".join(lines)
        )[:650]

    @staticmethod
    def _identifier_key(
        value: str,
    ) -> str:
        normalized = unicodedata.normalize(
            "NFKC",
            str(value or ""),
        ).casefold()

        return "".join(
            character
            for character in normalized
            if (
                unicodedata.category(character)[0] in {"L", "N"}
                or unicodedata.category(character) == "Mn"
            )
        )

    @classmethod
    def _character_aliases(
        cls,
        cast_ids: list[str],
    ) -> dict[str, str]:
        registry = character_registry()
        aliases: dict[str, str] = {}

        for character_id in cast_ids:
            character = registry[character_id]

            for value in (
                character.id,
                character.display_name,
                character.role,
            ):
                aliases[
                    cls._identifier_key(value)
                ] = character_id

        common = {
            "guddu": (
                "गुड्डू",
                "son",
                "beta",
                "बेटा",
                "young lead",
            ),
            "bittu": (
                "बिट्टू",
                "friend",
                "dost",
                "दोस्त",
                "comic friend",
            ),
            "chacha": (
                "चाचा",
                "चचा",
                "uncle",
                "comic elder",
            ),
            "mai": (
                "माई",
                "माँ",
                "मां",
                "mother",
                "mom",
                "mummy",
                "मम्मी",
            ),
            "babuji": (
                "बाबूजी",
                "पिताजी",
                "पिता",
                "father",
                "dad",
                "papa",
                "पापा",
            ),
        }

        allowed = set(cast_ids)

        for canonical_id, values in common.items():
            if canonical_id not in allowed:
                continue

            for value in (
                canonical_id,
                *values,
            ):
                aliases[
                    cls._identifier_key(value)
                ] = canonical_id

        return aliases

    @classmethod
    def _canonical_character_id(
        cls,
        value: str,
        *,
        cast_ids: list[str],
    ) -> str | None:
        return cls._character_aliases(
            cast_ids
        ).get(
            cls._identifier_key(value)
        )

    @classmethod
    def _canonical_location_id(
        cls,
        value: str,
    ) -> str | None:
        lookup = {
            cls._identifier_key(location): location
            for location in background_ids()
        }

        return lookup.get(
            cls._identifier_key(value)
        )

    @classmethod
    def _normalize_batch_identifiers(
        cls,
        *,
        batch: CartoonSceneBatch,
        cast_ids: list[str],
    ) -> None:
        for scene in batch.scenes:
            location = cls._canonical_location_id(
                scene.location_id
            )

            if location is not None:
                scene.location_id = location

            used: list[str] = []

            for line in scene.dialogue:
                canonical = cls._canonical_character_id(
                    line.character_id,
                    cast_ids=cast_ids,
                )

                if canonical is None:
                    canonical = next(
                        (
                            candidate
                            for candidate in cast_ids
                            if candidate not in used
                        ),
                        cast_ids[
                            (scene.id - 1) % len(cast_ids)
                        ],
                    )

                    print(
                        "[CARTOON V9] "
                        f"Unknown batch speaker in scene {scene.id}: "
                        f"{line.character_id!r}; using {canonical!r}."
                    )

                line.character_id = canonical

                if canonical not in used:
                    used.append(canonical)

            if scene.reaction is not None:
                canonical = cls._canonical_character_id(
                    scene.reaction.character_id,
                    cast_ids=cast_ids,
                )

                if canonical is None:
                    canonical = (
                        used[0]
                        if used
                        else cast_ids[
                            (scene.id - 1) % len(cast_ids)
                        ]
                    )

                scene.reaction.character_id = canonical

    @classmethod
    def _apply_route_sfx(cls, *, batch: CartoonSceneBatch, premise_lock: dict[str, object]) -> None:
        mapping = premise_lock.get("sfx_by_scene", {})
        if not isinstance(mapping, dict):
            return
        for scene in batch.scenes:
            values = mapping.get(str(scene.id), [])
            if isinstance(values, list):
                scene.sfx_cues = [str(v) for v in values if str(v) in cls._ALLOWED_SFX][:2]

    @staticmethod
    def _enforce_brief_contract(
        *,
        batch: CartoonSceneBatch,
        briefs: list[CartoonSceneBrief],
    ) -> None:
        """
        Make the deterministic scene brief authoritative.

        The LLM may create dialogue, expressions, actions and jokes, but it
        cannot rename structural IDs after generation. This prevents repair
        output such as location_id="home" from breaking a scene planned as
        location_id="living_room".
        """
        brief_by_id = {
            brief.id: brief
            for brief in briefs
        }

        for scene in batch.scenes:
            brief = brief_by_id.get(scene.id)

            if brief is None:
                # _validate_batch owns the precise scene-ID mismatch error.
                continue

            if scene.location_id != brief.location_id:
                print(
                    "[CARTOON CONTRACT] "
                    f"Scene {scene.id} location corrected: "
                    f"{scene.location_id!r} -> {brief.location_id!r}"
                )
                scene.location_id = brief.location_id

            if scene.beat != brief.beat:
                print(
                    "[CARTOON CONTRACT] "
                    f"Scene {scene.id} beat corrected: "
                    f"{scene.beat!r} -> {brief.beat!r}"
                )
                scene.beat = brief.beat

            # V11.4: deterministic action/location contract is authoritative in
            # both LLM and fallback paths. Dialogue may vary, but a chase scene
            # cannot collapse back into a static two-shot.
            if brief.visual_action != "auto":
                scene.visual_action = brief.visual_action
            scene.camera = brief.camera_hint
            scene.camera_action = brief.camera_action_hint
            scene.blocking_mode = brief.blocking_mode
            for prop in brief.props:
                if prop not in scene.props:
                    scene.props.append(prop)
                if len(scene.props) >= 6:
                    break

            expected_speakers = list(brief.speakers)

            if not expected_speakers:
                continue

            used: list[str] = []

            for line_index, line in enumerate(scene.dialogue):
                if line.character_id in expected_speakers:
                    if line.character_id not in used:
                        used.append(line.character_id)
                    continue

                replacement = expected_speakers[
                    line_index % len(expected_speakers)
                ]

                if (
                    replacement in used
                    and len(expected_speakers) > 1
                ):
                    replacement = next(
                        (
                            candidate
                            for candidate in expected_speakers
                            if candidate not in used
                        ),
                        replacement,
                    )

                print(
                    "[CARTOON CONTRACT] "
                    f"Scene {scene.id} speaker corrected: "
                    f"{line.character_id!r} -> {replacement!r}"
                )

                line.character_id = replacement

                if replacement not in used:
                    used.append(replacement)

            if (
                scene.reaction is not None
                and scene.reaction.character_id not in expected_speakers
            ):
                replacement = (
                    scene.dialogue[-1].character_id
                    if scene.dialogue
                    and scene.dialogue[-1].character_id in expected_speakers
                    else expected_speakers[-1]
                )

                print(
                    "[CARTOON CONTRACT] "
                    f"Scene {scene.id} reaction character corrected: "
                    f"{scene.reaction.character_id!r} -> {replacement!r}"
                )

                scene.reaction.character_id = replacement

    @staticmethod
    def _validate_batch(
        *,
        batch: CartoonSceneBatch,
        briefs: list[CartoonSceneBrief],
        allowed_cast: set[str],
    ) -> None:
        expected_ids = [
            item.id
            for item in briefs
        ]
        actual_ids = [
            scene.id
            for scene in batch.scenes
        ]

        if actual_ids != expected_ids:
            raise ValueError(
                "Scene batch IDs do not match skeleton. "
                f"expected={expected_ids}, actual={actual_ids}"
            )

        allowed_locations = set(background_ids())

        for scene in batch.scenes:
            if scene.location_id not in allowed_locations:
                raise ValueError(
                    f"Unknown location in scene {scene.id}: "
                    f"{scene.location_id}"
                )

            for line in scene.dialogue:
                if line.character_id not in allowed_cast:
                    raise ValueError(
                        f"Unknown speaker in scene {scene.id}: "
                        f"{line.character_id}"
                    )

            if (
                scene.reaction is not None
                and scene.reaction.character_id not in allowed_cast
            ):
                raise ValueError(
                    f"Unknown reacting character in scene {scene.id}: "
                    f"{scene.reaction.character_id}"
                )

    @staticmethod
    def _validate_plan(
        *,
        plan: CartoonEpisodePlan,
        allowed_cast: set[str],
    ) -> None:
        if not set(plan.characters).issubset(
            allowed_cast
        ):
            raise ValueError(
                "Final plan returned character(s) outside selected cast."
            )

        speaking = {
            line.character_id
            for scene in plan.scenes
            for line in scene.dialogue
        }

        if len(speaking) < 2:
            raise ValueError(
                "Cartoon episode must contain dialogue from at least "
                "two characters."
            )
