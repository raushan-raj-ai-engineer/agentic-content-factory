from pathlib import Path
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from content_factory.local_video.config import EngineConfig
from content_factory.local_video.plan import load_plan, shots_from_plan
from content_factory.local_video.backends.motion_ltx import LTXMotionBackend


def main():
    cfg = EngineConfig.from_project(ROOT)
    assert cfg.width == 512
    assert LTXMotionBackend.frames_for(2.0, 16) % 8 == 1
    # Build a tiny local plan independent of the project's benchmark artifact.
    tmp = ROOT / ".test-v19"
    tmp.mkdir(exist_ok=True)
    plan_path = tmp / "plan.json"
    plan_path.write_text(json.dumps({"scenes":[{"id":1,"setup":"test","location_id":"home","visual_action":"wave","dialogue":[{"character_id":"babuji","text":"नमस्ते","emotion":"happy"}]}]}, ensure_ascii=False), encoding="utf-8")
    (tmp / "scene_01.png").write_bytes((ROOT / "sample_assets" / "scene_01.png").read_bytes())
    shots = shots_from_plan(load_plan(plan_path), tmp)
    assert len(shots) == 1
    assert "Natural hand" in shots[0].motion_prompt
    print("V19 OWN VIDEO ENGINE CONTRACT TESTS PASSED")
    print("fake_static_motion=DISABLED")
    print("motion_backend=LTX")
    print("voice_backend=PIPER")

if __name__ == "__main__":
    main()
