import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from content_factory.agents.visual_generator import VisualGenerationAgent
from content_factory.video.local import LocalVideoAssembler
from content_factory.visual.study_semantics import StudySemanticPlanner
from content_factory.visual.technical import TechnicalVisualRenderer


def test_mcp_scenes_are_semantically_routed_not_one_flow_template() -> None:
    scenes = [
        SimpleNamespace(
            id=1,
            title="The Universal Adapter Mental Model",
            description="Think of MCP as a universal adapter that removes many custom connectors.",
            key_elements=["custom connectors", "MCP", "universal adapter"],
            visual_type="technical_workflow",
        ),
        SimpleNamespace(
            id=2,
            title="Hosts Clients and Servers in Action",
            description="The host contains a client that communicates with MCP servers.",
            key_elements=["Host", "Client", "Server"],
            visual_type="technical_diagram",
        ),
        SimpleNamespace(
            id=3,
            title="Tools Resources and Prompts",
            description="Servers expose tools, resources, and prompts as distinct capabilities.",
            key_elements=["Tools", "Resources", "Prompts"],
            visual_type="technical_diagram",
        ),
        SimpleNamespace(
            id=4,
            title="Verification Testing and Common Failure Cases",
            description="Validate input schemas and reject invalid tool arguments before execution.",
            key_elements=["Schema", "Invalid arguments", "Validation"],
            visual_type="technical_workflow",
        ),
        SimpleNamespace(
            id=5,
            title="Production Security and Trust Boundaries",
            description="Protect sensitive resources with permission checks and explicit trust boundaries.",
            key_elements=["Permission", "Trust boundary", "Sensitive data"],
            visual_type="technical_diagram",
        ),
    ]
    plans = StudySemanticPlanner.plan_all(topic="Model Context Protocol MCP", scenes=scenes)
    assert [plans[i].archetype for i in range(1, 6)] == [
        "many_to_one",
        "architecture_network",
        "capability_orbit",
        "validation_gate",
        "security_boundary",
    ]
    assert len({plan.archetype for plan in plans.values()}) == 5


def test_different_topics_route_to_topic_specific_archetypes() -> None:
    examples = [
        ("RAG for Beginners", "Retrieve chunks from a vector database and ground the answer.", "retrieval_pipeline"),
        ("Playwright Locators", "Find the browser element with a locator and click it.", "browser_action"),
        ("API Testing", "Send an HTTP request to an endpoint and inspect the response.", "request_response"),
        ("Binary Search", "Use a sorted array and move the pointer by index.", "algorithm_trace"),
    ]
    actual = []
    for index, (topic, description, expected) in enumerate(examples, start=1):
        plan = StudySemanticPlanner.plan_scene(
            scene_id=index,
            topic=topic,
            title=topic,
            description=description,
            key_elements=[],
            visual_type="technical_diagram",
        )
        actual.append(plan.archetype)
        assert plan.archetype == expected
    assert len(set(actual)) == len(actual)


def test_study_motion_sidecar_requires_semantic_manim_manifest(tmp_path: Path) -> None:
    image = tmp_path / "scene_1.png"
    Image.new("RGB", (1920, 1080), (8, 17, 31)).save(image)
    manifest = image.with_suffix(".png.study.json")
    manifest.write_text(
        json.dumps(
            {
                "scene_id": 1,
                "topic": "MCP",
                "title": "Hosts Clients and Servers",
                "archetype": "architecture_network",
                "visual_type": "technical_diagram",
                "labels": ["Host", "Client", "Server"],
                "beats": ["place_nodes", "connect_edges", "move_message"],
            }
        ),
        encoding="utf-8",
    )
    VisualGenerationAgent._write_study_motion_policy(
        output_path=image,
        visual_type="technical_diagram",
        study_manifest=manifest,
    )
    sidecar = image.with_suffix(".png.motion.json")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["mode"] == "study_semantic_manim"
    assert payload["policy"] == "study-animation-v3-semantic-manim"
    assert payload["renderer"] == "manim"
    assert payload["whole_frame_zoom"] is False
    assert payload["static_png_primary"] is False
    assert LocalVideoAssembler._study_animation_required([str(image)]) is True
    loaded = LocalVideoAssembler._study_semantic_manifest(str(image))
    assert loaded is not None
    assert loaded[1]["archetype"] == "architecture_network"


def test_technical_reference_png_changes_with_scene_intent(tmp_path: Path) -> None:
    architecture = tmp_path / "architecture.png"
    validation = tmp_path / "validation.png"
    renderer = TechnicalVisualRenderer()
    renderer.render(
        title="Hosts Clients and Servers",
        description="A host contains a client that connects to one or more MCP servers.",
        visual_type="technical_diagram",
        output_path=str(architecture),
    )
    renderer.render(
        title="Verification and Failure Cases",
        description="Validate input schemas and reject invalid arguments before execution.",
        visual_type="technical_workflow",
        output_path=str(validation),
    )
    assert architecture.is_file() and validation.is_file()
    assert architecture.read_bytes() != validation.read_bytes()
    assert not architecture.with_suffix(".png.layers.json").exists()
    assert not validation.with_suffix(".png.layers.json").exists()


def test_ai_agent_lesson_routes_scene_intent_not_topic_noise() -> None:
    examples = [
        ("Context", "Learn what an AI agent is and why it matters.", "concept_reveal"),
        ("Mental Model of an Agent", "An agent plans, chooses a tool, observes the result, and loops.", "agent_tool_loop"),
        ("Implementing the Agent Loop in Code", "Implement the loop in code with a function and tool call.", "code_execution"),
        ("Verification and Common Edge Cases", "Verify outputs, reject invalid tool arguments, and handle failures.", "validation_gate"),
        ("Architectural Tradeoffs and Interview Takeaways", "Compare flexibility versus control and discuss tradeoffs.", "tradeoff_balance"),
        ("What to Watch Next", "Try building a small agent as a practice challenge.", "build_challenge"),
    ]
    for index, (title, description, expected) in enumerate(examples, start=1):
        plan = StudySemanticPlanner.plan_scene(
            scene_id=index,
            topic="AI Agents for Beginners",
            title=title,
            description=description,
            key_elements=[],
            visual_type="technical_diagram",
        )
        assert plan.archetype == expected
        assert plan.archetype in StudySemanticPlanner.SUPPORTED_ARCHETYPES
