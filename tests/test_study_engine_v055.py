from __future__ import annotations

import math
import wave
from pathlib import Path
from types import SimpleNamespace

from content_factory.agents.study_animation_director import StudyAnimationDirectorAgent
from content_factory.visual.study_storyboard import (
    StudySceneStoryboard,
    StudyVisualBeat,
    StudyVisualObject,
    storyboard_quality_report,
)
from content_factory.voice.local import LocalVoiceProvider


def test_bidirectional_voice_tempo_handles_slow_and_fast_speech() -> None:
    assert LocalVoiceProvider._pace_tempo(112.0, 147) > 1.0
    assert LocalVoiceProvider._pace_tempo(147.0, 147) == 1.0
    assert LocalVoiceProvider._pace_tempo(170.0, 147) < 1.0
    assert 1.0 <= LocalVoiceProvider._pace_tempo(80.0, 147) <= 1.18
    assert 0.86 <= LocalVoiceProvider._pace_tempo(220.0, 147) <= 1.0


def test_audio_activity_stats_detect_long_silence(tmp_path: Path) -> None:
    path = tmp_path / "sample.wav"
    rate = 22050
    samples: list[int] = []
    # 0.5s silence, 1s tone, 1s silence, 1s tone, 0.5s silence
    for seconds, tone in [(0.5, False), (1.0, True), (1.0, False), (1.0, True), (0.5, False)]:
        for i in range(int(rate * seconds)):
            samples.append(int(6000 * math.sin(2 * math.pi * 220 * i / rate)) if tone else 0)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"".join(int(v).to_bytes(2, "little", signed=True) for v in samples))

    stats = LocalVoiceProvider._audio_activity_stats(path)
    assert 3.8 <= stats["total_seconds"] <= 4.2
    assert 1.7 <= stats["active_seconds"] <= 2.6
    assert stats["silence_ratio"] > 0.30


def test_storyboard_quality_tracks_meaningful_state_change() -> None:
    static = StudySceneStoryboard(
        scene_id=1,
        purpose="Define a concept",
        layout="freeform",
        objects=[
            StudyVisualObject(id="a", kind="equation", label="Relationship", slot="left_mid"),
            StudyVisualObject(id="b", kind="graph", label="Graph", slot="center"),
            StudyVisualObject(id="c", kind="quantity", label="Result", slot="right_mid"),
        ],
        beats=[
            StudyVisualBeat(cue="define it", action="reveal", target="a"),
            StudyVisualBeat(cue="show graph", action="reveal", target="b"),
            StudyVisualBeat(cue="show result", action="reveal", target="c"),
            StudyVisualBeat(cue="connect", action="connect", target="b", source="a", destination="b"),
        ],
    )
    report = storyboard_quality_report([static])
    assert report["dynamic_scene_ratio"] == 0.0
    assert any("state-changing" in str(issue) for issue in report["issues"])


def test_math_fallback_uses_math_primitives_not_software_boxes() -> None:
    scene = SimpleNamespace(
        id=1,
        title="Understanding slope",
        description="The slope of a line compares change in y with change in x on a graph.",
        key_elements=["slope", "change in y", "change in x", "graph"],
        visual_type="educational",
    )
    sb = StudyAnimationDirectorAgent._fallback("Algebra: slope for beginners", scene)
    kinds = {obj.kind for obj in sb.objects}
    assert kinds & {"equation", "graph", "quantity", "number_line"}
    assert not ({"client", "server", "packet"} <= kinds)
    assert {beat.action for beat in sb.beats} & {"compare", "select", "transform"}


def test_science_fallback_uses_science_primitives() -> None:
    scene = SimpleNamespace(
        id=2,
        title="Wave frequency",
        description="Frequency tells us how many wave cycles pass a point each second.",
        key_elements=["frequency", "wave", "cycles", "seconds"],
        visual_type="educational",
    )
    sb = StudyAnimationDirectorAgent._fallback("Physics waves", scene)
    kinds = {obj.kind for obj in sb.objects}
    assert "wave" in kinds
    assert kinds & {"graph", "quantity", "vector"}


def test_renderer_source_has_no_persistent_study_mode_banner() -> None:
    source = Path("src/content_factory/visual/study_manim_scene.py").read_text(encoding="utf-8")
    assert 'Text("STUDY MODE"' not in source
    assert "def _context_title" in source
    assert "def _retire_context_title" in source
