from types import SimpleNamespace

import pytest

from content_factory.agents import script_writer_chunked as swc


class FakeLLM:
    def __init__(self) -> None:
        self.switched = 0

    async def switch_to_alternate_model(self, reason: str) -> bool:
        self.switched += 1
        return True


class FakeAgent:
    def __init__(self) -> None:
        self._llm = FakeLLM()

    def _target_language_name(self, state) -> str:
        return "English (United States)"


@pytest.fixture
def study_state():
    return SimpleNamespace(
        topic="RAG explained for beginners",
        strategy=SimpleNamespace(
            topic="RAG explained for beginners",
            audience="Beginners",
            angle="Build the mental model and then implement it.",
            estimated_duration_minutes=12,
            hook="RAG gives a model relevant evidence before it answers.",
        ),
        metadata={"topic_grounding": {"target_duration_minutes": 12}},
    )


@pytest.mark.asyncio
async def test_study_mode_uses_six_smaller_chunks(monkeypatch, study_state) -> None:
    monkeypatch.setattr(swc, "is_study_mode", lambda state: True)
    calls = []

    async def fake_generate(agent, *, prompt, system_prompt, timeout):
        calls.append(prompt)
        idx = len(calls)
        return swc._ScriptChunk(
            title=study_state.strategy.topic if idx == 1 else "",
            hook=study_state.strategy.hook if idx == 1 else "",
            sections=[swc._ChunkSection(title=f"Section {idx}", content="Useful narration " * 30)],
            conclusion="Recap" if idx == 6 else "",
            call_to_action="Practice" if idx == 6 else "",
        )

    async def no_expand(agent, state, **kwargs):
        return kwargs["chunk"]

    monkeypatch.setattr(swc, "_generate_one", fake_generate)
    monkeypatch.setattr(swc, "_expand_study_chunk_if_short", no_expand)

    script = await swc.generate_chunked_script(
        FakeAgent(), study_state, min_words=1500, max_words=1900, target_minutes=12
    )

    assert len(calls) == 6
    assert len(script.sections) == 6
    assert "CHUNK 6 OF 6" in calls[-1]


@pytest.mark.asyncio
async def test_timeout_switches_local_model_then_micro_rescues(monkeypatch, study_state) -> None:
    monkeypatch.setattr(swc, "is_study_mode", lambda state: True)
    agent = FakeAgent()
    attempts = 0

    async def always_timeout(agent_arg, *, prompt, system_prompt, timeout):
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise TimeoutError()
        return swc._ScriptChunk(
            sections=[swc._ChunkSection(title=f"S{attempts}", content="Narration " * 40)]
        )

    async def micro(agent_arg, state, **kwargs):
        return swc._ScriptChunk(
            title=state.strategy.topic if kwargs["index"] == 1 else "",
            hook=state.strategy.hook if kwargs["index"] == 1 else "",
            sections=[swc._ChunkSection(title="Recovered", content="Recovered narration " * 30)],
        )

    async def no_expand(agent_arg, state, **kwargs):
        return kwargs["chunk"]

    monkeypatch.setattr(swc, "_generate_one", always_timeout)
    monkeypatch.setattr(swc, "_micro_rescue_chunk", micro)
    monkeypatch.setattr(swc, "_expand_study_chunk_if_short", no_expand)

    script = await swc.generate_chunked_script(
        agent, study_state, min_words=1200, max_words=1800, target_minutes=10
    )

    assert agent._llm.switched == 1
    assert any(section.title == "Recovered" for section in script.sections)
    assert len(script.sections) >= 5
