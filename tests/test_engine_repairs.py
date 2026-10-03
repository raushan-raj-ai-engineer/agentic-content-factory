import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from content_factory.local_video.media import mux, concat_media, duration_seconds
from content_factory.local_video.backends.voice_piper import PiperVoiceBackend
from content_factory.local_video.config import EngineConfig
from content_factory.agents.fact_checker import FactCheckerAgent
from content_factory.models.content import FactCheckResult, YouTubeScript
from content_factory.orchestration.state import WorkflowState


def ff(*args):
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y',*map(str,args)],check=True)


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg required')
def test_mux_preserves_long_audio_and_concat_handles_quoted_path(tmp_path):
    folder=tmp_path/"creator's demo";folder.mkdir()
    motion=folder/'motion.mp4';voice=folder/'voice.wav';out=folder/'output.mp4'
    ff('-f','lavfi','-i','color=c=blue:s=320x180:r=24','-t','0.5','-c:v','libx264',motion)
    ff('-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','2.5','-ac','2',voice)
    mux(motion,voice,out)
    assert abs(duration_seconds(out)-2.5)<0.15
    joined=folder/'joined.mp4'
    concat_media([out,out],joined)
    assert abs(duration_seconds(joined)-5.0)<0.2
    # Decode the complete output, not just its container header.
    ff('-xerror','-i',joined,'-f','null','-')


def test_empty_concat_rejected(tmp_path):
    with pytest.raises(ValueError,match='No clips'):
        concat_media([],tmp_path/'bad.mp4')


def test_voice_name_rejects_traversal(tmp_path):
    backend=PiperVoiceBackend(EngineConfig.from_project(tmp_path))
    with pytest.raises(ValueError):backend.ensure_voice('../voice')


@pytest.mark.asyncio
async def test_rejected_empty_fact_result_is_not_upgraded():
    state=WorkflowState(run_id='test')
    state.script=YouTubeScript(title='Test',hook='Hook',introduction='Intro',sections=[{'title':'One','content':'Content'}],conclusion='End',call_to_action='Try it',estimated_duration_minutes=1)
    agent=FactCheckerAgent(AsyncMock())
    agent._check=AsyncMock(return_value=FactCheckResult(approved=False,score=30,issues=[]))
    agent._repair_script=AsyncMock()
    result=await agent.execute(state)
    assert result.stop_requested and not result.fact_check.approved
    assert result.fact_check.score==30
    agent._repair_script.assert_not_called()
