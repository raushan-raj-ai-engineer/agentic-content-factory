import sys
import types
import wave
from dataclasses import replace
from unittest.mock import AsyncMock
import pytest
from content_factory.agents.content_producer import ContentProductionAgent
from content_factory.models.content import YouTubeScript, TrendCandidate
from content_factory.orchestration.state import WorkflowState
from content_factory.local_video.backends.voice_piper import PiperVoiceBackend
from content_factory.local_video.config import EngineConfig


@pytest.mark.asyncio
async def test_approved_script_produces_paired_plan():
    state=WorkflowState(run_id='production-smoke',topic='Python lists',script_approved=True)
    state.script=YouTubeScript(title='Python lists',hook='Lists preserve order.', introduction='A list stores a sequence of values.',sections=[{'title':'Indexing','content':'Python list indexing starts at zero. Access the first value with index zero.'}],conclusion='Try a small list.',call_to_action='Test it yourself.',estimated_duration_minutes=1)
    result=await ContentProductionAgent().execute(state)
    assert result.production_plan.voice_segments
    assert [v.id for v in result.production_plan.voice_segments] == [s.voice_segment_id for s in result.production_plan.visual_scenes]


def test_trend_accepts_numeric_competition():
    candidate=TrendCandidate(topic='Python',trend_score=70,audience_fit=80,competition=35,opportunity_score=65)
    assert candidate.competition==35


def test_voice_cache_reuses_model_and_regenerates_corrupt_wav(tmp_path,monkeypatch):
    class Voice:
        loads=0
        calls=0
        @classmethod
        def load(cls,*a,**kw):cls.loads+=1;return cls()
        def synthesize_wav(self,text,wav):
            type(self).calls+=1
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(22050)
            wav.writeframes(b'\x01\x00'*2205)
    monkeypatch.setitem(sys.modules,'piper',types.SimpleNamespace(PiperVoice=Voice))
    cfg=EngineConfig.from_project(tmp_path)
    cfg=replace(cfg,piper_voice_map={'default':'test'})
    cfg.piper_voice_dir.mkdir(parents=True)
    (cfg.piper_voice_dir/'test.onnx').write_bytes(b'0'*2048)
    (cfg.piper_voice_dir/'test.onnx.json').write_text('{}')
    backend=PiperVoiceBackend(cfg)
    backend.synthesize('Hello','default',tmp_path/'a.wav')
    backend.synthesize('Hello','default',tmp_path/'b.wav')
    assert Voice.loads==1 and Voice.calls==1
    next((cfg.cache_root/'voice').glob('*.wav')).write_bytes(b'bad')
    backend.synthesize('Hello','default',tmp_path/'c.wav')
    assert Voice.loads==1 and Voice.calls==2

@pytest.mark.asyncio
async def test_study_mode_forces_technical_visual_domain():
    state=WorkflowState(run_id='study-domain',topic='AI Agents for Beginners',script_approved=True)
    state.metadata['content_mode']='study'
    state.metadata['requested_category']='technical'
    state.script=YouTubeScript(
        title='AI Agents for Beginners',
        hook='Agents can choose tools.',
        introduction='Learn the agent loop from first principles.',
        sections=[{'title':'Agent Loop','content':'An agent plans, selects a tool, executes the action, observes the result, and continues.'}],
        conclusion='Verify every tool action.',
        call_to_action='Build a small agent.',
        estimated_duration_minutes=2,
    )
    result=await ContentProductionAgent().execute(state)
    assert result.metadata['production_domain']=='technical'
    assert result.metadata['domain_classification']['domain']=='technical'


def test_mcp_identity_is_technical_even_when_full_script_uses_restaurant_analogy():
    from content_factory.agents.content_producer import ContentProductionAgent

    classification = ContentProductionAgent._resolve_domain_classification(
        identity_context="Model Context Protocol MCP Beginner Guide software developers",
        full_context=(
            "Model Context Protocol MCP server client JSON-RPC. "
            "Imagine a restaurant kitchen with a chef, waiter, ingredients, and pantry."
        ),
        has_factual_evidence=True,
    )
    assert classification.domain == "technical"
    assert classification.family == "technical"
