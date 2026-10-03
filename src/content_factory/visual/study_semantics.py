from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True)
class StudyScenePlan:
    scene_id: int
    topic: str
    title: str
    archetype: str
    visual_type: str
    labels: list[str]
    beats: list[str]
    reference_role: str = "context"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class StudySemanticPlanner:
    """Pick a scene-specific teaching animation from the actual narration.

    The planner intentionally does not map every technical lesson to one fixed
    flow chart. It routes by topic *and* scene intent, then nudges adjacent
    scenes away from repeating the same archetype when another valid treatment
    exists.
    """

    SUPPORTED_ARCHETYPES = frozenset({
        "many_to_one", "architecture_network", "capability_orbit",
        "message_exchange", "validation_gate", "security_boundary",
        "tradeoff_balance", "retrieval_pipeline", "request_response",
        "browser_action", "browser_test", "query_table", "algorithm_trace",
        "agent_tool_loop", "analogy_transform", "timeline_build",
        "code_execution", "concept_map", "build_challenge", "concept_reveal",
    })

    _STOP = {
        "the", "a", "an", "and", "or", "to", "for", "from", "with", "into",
        "how", "why", "what", "when", "this", "that", "these", "those", "your",
        "our", "their", "its", "is", "are", "was", "were", "be", "being", "been",
        "in", "on", "of", "by", "as", "at", "it", "we", "you", "they", "then",
        "now", "using", "use", "used", "model", "context", "protocol",
    }

    @classmethod
    def plan_all(
        cls,
        *,
        topic: str,
        scenes: Iterable[object],
    ) -> dict[int, StudyScenePlan]:
        plans: dict[int, StudyScenePlan] = {}
        recent: list[str] = []
        for scene in scenes:
            scene_id = int(getattr(scene, "id"))
            plan = cls.plan_scene(
                scene_id=scene_id,
                topic=topic,
                title=str(getattr(scene, "title", "")),
                description=str(getattr(scene, "description", "")),
                key_elements=[str(x) for x in getattr(scene, "key_elements", [])],
                visual_type=str(getattr(scene, "visual_type", "")),
                recent_archetypes=recent[-2:],
            )
            plans[scene_id] = plan
            recent.append(plan.archetype)
        return plans

    @classmethod
    def plan_scene(
        cls,
        *,
        scene_id: int,
        topic: str,
        title: str,
        description: str,
        key_elements: list[str],
        visual_type: str,
        recent_archetypes: list[str] | None = None,
    ) -> StudyScenePlan:
        scene_text = cls._norm(" ".join([title, description, visual_type, *key_elements]))
        text = cls._norm(" ".join([topic, scene_text]))
        title_text = cls._norm(title)
        recent = recent_archetypes or []

        archetype = cls._choose_archetype(
            topic=cls._norm(topic),
            title=title_text,
            text=text,
            scene_text=scene_text,
            visual_type=cls._norm(visual_type),
        )
        archetype = cls._avoid_boring_repeat(archetype, text, recent)

        labels = cls._labels(key_elements, description, title, topic)
        beats = cls._beats(archetype, labels)
        return StudyScenePlan(
            scene_id=scene_id,
            topic=topic,
            title=title,
            archetype=archetype,
            visual_type=visual_type,
            labels=labels,
            beats=beats,
            reference_role="topic_scene_reference",
        )

    @classmethod
    def _choose_archetype(
        cls,
        *,
        topic: str,
        title: str,
        text: str,
        scene_text: str,
        visual_type: str,
    ) -> str:
        """Choose from the current scene first; topic only supplies domain context.

        v0.4.1 let topic-level keywords contaminate every scene. For example an
        AI-agent lesson could route a generic intro to browser_test or an API
        animation merely because those words appeared elsewhere. The current
        scene narration/title is now authoritative.
        """

        # Structural scene intents have highest priority, but use precise
        # phrases so topic titles such as "API Testing" do not become a
        # validation scene by accident.
        if cls._has(title, "what to watch next", "next step", "practice", "challenge"):
            return "build_challenge"
        if cls._has(title, "tradeoff", "production design", "interview takeaway"):
            return "tradeoff_balance"
        if cls._has(title, "verification", "failure case", "edge case", "debugging"):
            if cls._has(scene_text, "security", "permission", "guardrail", "unsafe", "sensitive"):
                return "security_boundary"
            return "validation_gate"
        if cls._has(title, "implement", "code", "coding") or "code" in visual_type:
            return "code_execution"
        if cls._has(scene_text, "security", "permission", "trust boundary", "sensitive", "attack", "guardrail"):
            return "security_boundary"
        if cls._has(title, "recap", "what it means", "summary", "takeaway"):
            return "concept_map"
        if cls._has(title, "mental model", "analogy"):
            if cls._has(topic, "mcp", "model context protocol") and cls._has(scene_text, "adapter", "fragmentation", "many-to-many", "custom connector"):
                return "many_to_one"
            if cls._has(topic, "agent", "agentic") and cls._has(scene_text, "tool", "observe", "loop", "plan"):
                return "agent_tool_loop"
            return "analogy_transform"

        # Algorithm intent must be present in the scene, not merely the topic.
        if cls._has(scene_text, "binary search", "two sum", "pointer", "sorted array", "left index", "right index"):
            return "algorithm_trace"

        # Browser automation only when this scene explicitly talks about a browser.
        browser_scene = cls._has(scene_text, "browser", "playwright", "selenium", "locator", "page object", "click", "fill")
        if browser_scene:
            if cls._has(scene_text, "assert", "verify", "test", "failure", "debug"):
                return "browser_test"
            return "browser_action"

        # Retrieval only when retrieval concepts are actually narrated here.
        if cls._has(scene_text, "retrieval", "vector database", "embedding", "retriever", "chunk", "document store"):
            if cls._has(scene_text, "faithful", "hallucination", "verify", "evaluate"):
                return "validation_gate"
            return "retrieval_pipeline"

        # HTTP/API animation only for explicit request-response mechanics.
        if cls._has(scene_text, "http request", "http response", "endpoint", "rest api", "status code", "request body", "response body"):
            if cls._has(scene_text, "schema", "validation", "error", "failure", "assert"):
                return "validation_gate"
            return "request_response"

        # Agent lessons get agent-specific mechanics only when this scene describes
        # the loop/capabilities. Generic intro and recap scenes stay conceptual.
        if cls._has(topic, "agent", "agentic"):
            if cls._has(scene_text, "security", "permission", "guardrail", "unsafe", "sensitive"):
                return "security_boundary"
            if cls._has(scene_text, "tool", "observe", "observation", "plan", "planner", "memory", "action", "loop", "reason"):
                return "agent_tool_loop"
            if cls._has(scene_text, "architecture", "component", "orchestrator", "service"):
                return "architecture_network"

        # MCP-specific scene treatments.
        if cls._has(topic, "mcp", "model context protocol"):
            if cls._has(scene_text, "adapter", "fragmentation", "many-to-many", "custom connector"):
                return "many_to_one"
            if cls._has(scene_text, "tools", "resources", "prompts", "capabilities"):
                return "capability_orbit"
            if cls._has(scene_text, "host", "client", "server", "architecture", "component"):
                return "architecture_network"
            if cls._has(scene_text, "json-rpc", "request", "response", "message"):
                return "message_exchange"

        if cls._has(scene_text, "database", "sql", "query", "table", "row", "record"):
            return "query_table"

        # Topic-independent scene semantics.
        if cls._has(scene_text, "security", "permission", "trust boundary", "sensitive", "attack"):
            return "security_boundary"
        if cls._has(scene_text, "test", "verify", "validation", "failure", "error", "debug"):
            return "validation_gate"
        if cls._has(scene_text, "compare", "versus", "tradeoff", "pros", "cons", "before", "after"):
            return "tradeoff_balance"
        if cls._has(scene_text, "architecture", "client", "server", "service", "component", "node"):
            return "architecture_network"
        if cls._has(scene_text, "request", "response", "message", "event", "packet"):
            return "message_exchange"
        if cls._has(scene_text, "timeline", "first", "next", "finally", "stages", "step-by-step"):
            return "timeline_build"
        if cls._has(scene_text, "implement", "function", "method", "code"):
            return "code_execution"
        if cls._has(scene_text, "build", "try", "practice", "challenge"):
            return "build_challenge"
        return "concept_reveal"

    @classmethod
    def _avoid_boring_repeat(cls, archetype: str, text: str, recent: list[str]) -> str:
        if len(recent) < 2 or not (recent[-1] == recent[-2] == archetype):
            return archetype
        alternatives = {
            "architecture_network": "message_exchange",
            "message_exchange": "concept_map",
            "concept_reveal": "concept_map",
            "validation_gate": "security_boundary" if "security" in text else "concept_map",
            "code_execution": "build_challenge",
            "tradeoff_balance": "concept_map",
        }
        return alternatives.get(archetype, archetype)

    @classmethod
    def _labels(cls, key_elements: list[str], description: str, title: str, topic: str = "") -> list[str]:
        raw: list[str] = []
        banned_exact = {cls._norm(title), cls._norm(topic)}
        generic = {
            "welcome", "imagine", "instead", "these", "when", "why", "what",
            "building", "understand", "today", "context", "introduction",
        }
        for value in key_elements:
            cleaned = re.sub(r"\s+", " ", value).strip(" .,:;—-_()[]{}")
            if (
                cleaned
                and cls._usable_label(cleaned)
                and cls._norm(cleaned) not in banned_exact
                and cls._norm(cleaned) not in generic
            ):
                raw.append(cleaned)

        # Extract short noun-like phrases from the narration if production key
        # elements are too generic. This is deliberately deterministic.
        phrases = re.findall(
            r"\b(?:[A-Z][A-Za-z0-9+.#-]*|[a-z][a-z0-9+.#-]{2,})"
            r"(?:\s+(?:[A-Z][A-Za-z0-9+.#-]*|[a-z][a-z0-9+.#-]{2,})){0,2}\b",
            description,
        )
        for phrase in phrases:
            cleaned = re.sub(r"\s+", " ", phrase).strip()
            if (
                cls._usable_label(cleaned)
                and cls._norm(cleaned) not in banned_exact
                and cls._norm(cleaned) not in generic
            ):
                raw.append(cleaned)

        if not raw and cls._usable_label(title):
            raw.append(title)

        unique: list[str] = []
        seen: set[str] = set()
        for item in raw:
            item = cls._short_label(item)
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
            if len(unique) >= 6:
                break
        return unique or ["Core idea", "Mechanism", "Verification"]

    @classmethod
    def _usable_label(cls, text: str) -> bool:
        value = cls._norm(text)
        if not value or len(value) < 3 or len(value) > 64:
            return False
        words = value.split()
        if len(words) == 1 and words[0] in cls._STOP:
            return False
        if all(word in cls._STOP for word in words):
            return False
        return True

    @staticmethod
    def _short_label(text: str) -> str:
        value = re.sub(r"\s+", " ", text).strip()
        if len(value) <= 34:
            return value
        words = value.split()
        compact: list[str] = []
        for word in words:
            candidate = " ".join([*compact, word])
            if compact and len(candidate) > 34:
                break
            compact.append(word)
        return " ".join(compact) or value[:34].rstrip()

    @staticmethod
    def _beats(archetype: str, labels: list[str]) -> list[str]:
        templates = {
            "many_to_one": ["show_fragmentation", "merge_connectors", "introduce_standard", "show_reuse"],
            "architecture_network": ["place_nodes", "connect_edges", "move_message", "highlight_responsibility"],
            "capability_orbit": ["show_center", "orbit_capabilities", "select_capability", "return_context"],
            "message_exchange": ["show_peers", "send_request", "execute_action", "return_response"],
            "validation_gate": ["show_input", "check_schema", "reject_invalid", "pass_valid"],
            "security_boundary": ["show_boundary", "attempt_access", "check_permission", "allow_or_block"],
            "tradeoff_balance": ["show_benefit", "show_cost", "compare_weight", "show_takeaway"],
            "retrieval_pipeline": ["show_documents", "retrieve_matches", "compose_context", "ground_answer"],
            "request_response": ["create_request", "travel_to_service", "process", "return_response"],
            "browser_action": ["show_browser", "locate_target", "perform_action", "show_state_change"],
            "browser_test": ["show_browser", "perform_action", "assert_state", "pass_or_fail"],
            "query_table": ["show_table", "send_query", "highlight_rows", "return_result"],
            "algorithm_trace": ["show_data", "move_pointer", "eliminate_or_update", "show_result"],
            "agent_tool_loop": ["show_agent", "choose_tool", "execute_tool", "observe_and_continue"],
            "analogy_transform": ["show_real_world_analogy", "map_parts", "transform_to_technical", "show_equivalence"],
            "timeline_build": ["show_start", "add_stage", "advance_marker", "show_end"],
            "code_execution": ["show_code", "highlight_line", "show_state_change", "show_output"],
            "concept_map": ["show_core", "add_concepts", "connect_relationships", "highlight_takeaway"],
            "build_challenge": ["show_goal", "assemble_parts", "verify_build", "show_next_step"],
            "concept_reveal": ["show_question", "reveal_concepts", "connect_meaning", "show_takeaway"],
        }
        beats = list(templates.get(archetype, templates["concept_reveal"]))
        # Labels are not embedded into beat names because the renderer receives
        # them separately; keeping the beat vocabulary finite makes plans safe.
        return beats[: max(3, min(5, len(labels) + 1))]

    @staticmethod
    def _has(text: str, *needles: str) -> bool:
        return any(needle in text for needle in needles)

    @staticmethod
    def _norm(value: str) -> str:
        return re.sub(r"\s+", " ", value.lower()).strip()
