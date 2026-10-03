import json
import wave
from types import SimpleNamespace

import pytest

from content_factory.video.lesson import write_lesson
from content_factory.voice import timing


def audio(tmp_path, seconds=2.37):
    path = tmp_path / "segment.wav"
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, 1000, 0, "NONE", "not compressed"))
        out.writeframes(b"\0\0" * round(seconds * 1000))
    return path


def test_exact_duration_and_explicit_estimate(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDY_WORD_TIMING", "off")
    p = audio(tmp_path)
    result = timing.create_timing(p, "hello learner")
    assert result["duration_seconds"] == 2.37
    assert result["source"] == "text_estimate"
    assert p.with_suffix(".timing.json").exists()


def test_measured_cues_use_spoken_time_and_repeated_words():
    words = [
        {"word": w, "start": t, "end": t + 0.1}
        for w, t in [("send", 0.3), ("request", 0.5), ("send", 2), ("reply", 2.4)]
    ]
    result = timing.schedule_beats(
        [{"cue": "send request"}, {"cue": "send reply"}],
        "",
        {"source": "asr_word_timestamps", "words": words},
        3,
    )
    assert [b["start"] for b in result["beats"]] == [0.3, 2]
    assert result["measured_ratio"] == 1


def test_unmatched_cues_are_marked_and_bounded():
    result = timing.schedule_beats(
        [{"cue": "missing"}, {"cue": "hello"}], "hello world", {}, 1
    )
    assert all(b["source"] == "text_estimate" for b in result["beats"])
    starts = [b["start"] for b in result["beats"]]
    assert starts == sorted(starts)
    assert max(starts) <= 1


def test_required_timing_does_not_silently_downgrade(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDY_WORD_TIMING", "required")

    def unavailable(_):
        raise ImportError("not installed")

    monkeypatch.setattr(timing, "_model", unavailable)
    with pytest.raises(RuntimeError, match="Required word timing"):
        timing.create_timing(audio(tmp_path), "hello")
    monkeypatch.setenv("STUDY_WORD_TIMING", "auto")
    assert "warning" in timing.create_timing(audio(tmp_path), "hello")


def test_asr_low_coverage_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDY_WORD_TIMING", "auto")
    word = SimpleNamespace(word="unrelated", start=0, end=0.5)
    model = SimpleNamespace(
        transcribe=lambda *a, **k: ([SimpleNamespace(words=[word])], None)
    )
    monkeypatch.setattr(timing, "_model", lambda _: model)
    assert (
        timing.create_timing(audio(tmp_path), "send request now")["source"]
        == "text_estimate"
    )


def test_companion_exact_chapters_and_script_escaping(tmp_path):
    p = audio(tmp_path)
    output = tmp_path / "lesson.html"
    scenes = [SimpleNamespace(id=1, title="A"), SimpleNamespace(id=2, title="B")]
    write_lesson(
        output,
        [str(p), str(p)],
        scenes,
        [{"scene_id": 1, "interaction_prompt": "</script><script>alert(1)</script>"}],
        "<unsafe>",
    )
    assert json.loads(output.with_suffix(".json").read_text())[1]["start"] == 2.37
    assert "</script><script>alert" not in output.read_text()
    assert "&lt;unsafe&gt;" in output.read_text()
