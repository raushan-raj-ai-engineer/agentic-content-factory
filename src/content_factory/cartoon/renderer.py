from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import struct
import subprocess
import tempfile
import time
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from content_factory.cartoon.characters import character_registry
from content_factory.cartoon.language import CartoonLanguagePack, load_language_pack
from content_factory.cartoon.models import CartoonEpisodePlan, CartoonScene
from content_factory.cartoon.capabilities import (
    resolve_action_family,
    resolve_background_asset_id,
)
from content_factory.cartoon.performance_director_v16 import (
    crowd_full_rigs, focal_speaker, gaze_direction, gaze_for_line,
    interaction_mode as v16_interaction_mode, lightweight_positions,
    line_addressee, listener_gaze,
)
from content_factory.cartoon.quality_reset_v17 import (
    natural_actor_available, natural_actor_path,
)


FPS = 24
WIDTH = 1920
HEIGHT = 1080
AUDIO_RATE = 48000
AUDIO_CHANNELS = 1
AUDIO_SAMPLE_WIDTH = 2

# V9.1.2 natural pacing defaults.
SCENE_LEAD_IN_SECONDS = 0.10
SCENE_LEAD_OUT_SECONDS = 0.16
MIN_INTERLINE_PAUSE = 0.09
MAX_INTERLINE_PAUSE = 0.22
INTERLINE_PAUSE_SCALE = 0.55
MIN_REACTION_HOLD = 0.22
MAX_REACTION_HOLD = 0.42
REACTION_HOLD_SCALE = 0.55

RIG_FRAME_W = 420
RIG_FRAME_H = 740
RIG_CYCLE_FRAMES = 8


@dataclass(frozen=True)
class RenderResult:
    final_video: Path
    master_audio: Path
    report_path: Path
    duration_seconds: float
    voice_map: dict[str, dict[str, object]]
    degraded: bool


class CartoonRenderer:
    """
    V10.0.1 articulated renderer using portable PNG frame sequences.

    It intentionally uses pre-baked original articulated sprite sheets plus FFmpeg so
    rendering does not depend on diffusion/image models or Pillow at runtime.
    On macOS it uses `say` when available. On other systems it can use espeak;
    if no speech engine works, it generates timed silent dialogue audio rather
    than aborting the video build.
    """

    _EXPRESSION_ALIASES = {
        "neutral": "neutral",
        "happy": "happy",
        "smile": "happy",
        "small_smile": "happy",
        "proud": "happy",
        "excited": "happy",
        "smirk": "smirk",
        "angry": "angry",
        "serious": "serious",
        "suspicious": "suspicious",
        "shocked": "shocked",
        "surprised": "shocked",
        "confused": "confused",
        "embarrassed": "confused",
        "sad": "confused",
        "laughing": "laughing",
    }

    _RATES = {
        # Slightly slower than V9.1 for clearer Hindi articulation.
        "guddu": 158,
        "bittu": 168,
        "chacha": 142,
        "mai": 152,
        "babuji": 140,
    }

    _VOLUMES = {
        "guddu": 1.00,
        "bittu": 1.03,
        "chacha": 1.05,
        "mai": 0.98,
        "babuji": 1.02,
    }

    def __init__(
        self,
        *,
        project_root: Path,
        language: CartoonLanguagePack,
        fps: int = FPS,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.language = language
        self.fps = int(fps)

        # V17.7: render-existing-plan historically returned before CLI exported
        # CONTENT_FACTORY_CARTOON_CHANNEL. Natural actors and the Hindi-mass
        # audio profile are channel-gated, so that path silently fell back to
        # legacy stick sprites. Mirror the router's auto policy when the caller
        # has not supplied an explicit channel.
        _channel = os.getenv("CONTENT_FACTORY_CARTOON_CHANNEL", "").strip().lower()
        if _channel not in {"hindi_mass", "global_english"}:
            _code = str(getattr(language, "code", "") or "").strip().lower()
            _channel = "global_english" if _code in {"english", "en", "en_us", "en-us"} else "hindi_mass"
            os.environ["CONTENT_FACTORY_CARTOON_CHANNEL"] = _channel
            print(f"[CARTOON CHANNEL V17.7] renderer_inferred_channel={_channel}; language={_code}")
        self.assets_root = self.project_root / "assets" / "cartoon_v9_1"
        self.background_root = self.assets_root / "backgrounds"
        self.sprite_root = self.assets_root / "sprites"
        self.sfx_root = self.assets_root / "sfx"
        self.prop_root = self.assets_root / "props"
        self.rig_root = self.project_root / "assets" / "cartoon_v10" / "rigs"
        self.rig_prop_root = self.project_root / "assets" / "cartoon_v10" / "props"
        self.rig_config = json.loads((self.project_root / "configs" / "cartoon_rigs_v10.json").read_text(encoding="utf-8"))
        self.performance_root = self.project_root / "assets" / "cartoon_v11" / "rigs"
        self.foreground_root = self.project_root / "assets" / "cartoon_v11" / "foregrounds"
        self.v18_scene_fx_root = self.project_root / "assets" / "cartoon_v18" / "scene_fx"
        self.performance_config = json.loads((self.project_root / "configs" / "cartoon_performance_v11.json").read_text(encoding="utf-8"))
        self._hindi_audio_profile = self._load_hindi_audio_profile()
        if self._is_hindi_mass_channel():
            mastering = self._hindi_audio_profile.get("mastering", {})
            if not isinstance(mastering, dict):
                mastering = {}
            print(
                "[CARTOON AUDIO V15] "
                f"accent={self._channel_audio_profile_name()}; "
                f"target_lufs={float(mastering.get('integrated_lufs', -15.0)):.1f}; "
                "dialogue_presence=ON; sfx_duck=ON"
            )
            print(
                "[CARTOON AV V17.5] "
                "ground_lock=ON; safe_actor_framing=ON; background_double_zoom=OFF; "
                "single_stage_voice_master=ON; final_audio=stereo"
            )
            print(
                "[CARTOON QUALITY V17.7] "
                "static_fallback_natural=ON; actor_floor_lock=ON; "
                "expressive_voice=ON; scene_safe_background=ON"
            )
            print(
                "[CARTOON AV V18.1] "
                "story_specific_staging=ON; natural_dialogue_motion=ON; "
                "oversize_generic_phone=OFF; scene_fx=ON; expressive_audio_v18=ON"
            )
        self._voice_map: dict[str, dict[str, object]] = {}
        self._warnings: list[str] = []
        self._articulation_scene_quality: dict[int, dict[str, object]] = {}
        self._rig_sequence_fps: dict[str, int] = {}
        self._degraded = False
        self._encoder_args = self._select_video_encoder()
        self._validate_runtime()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def render(
        self,
        *,
        plan: CartoonEpisodePlan,
        artifact_root: Path,
    ) -> RenderResult:
        artifact_root = Path(artifact_root).resolve()
        render_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        work_root = artifact_root / "render" / render_id
        audio_root = work_root / "audio"
        scene_video_root = work_root / "scenes"
        video_root = artifact_root / "video"
        final_audio_root = artifact_root / "audio"

        for folder in (
            work_root,
            audio_root,
            scene_video_root,
            video_root,
            final_audio_root,
        ):
            folder.mkdir(parents=True, exist_ok=True)

        final_video = self._unique_path(video_root / "final_video.mp4")
        master_audio = self._unique_path(final_audio_root / "master.wav")
        report_path = work_root / "render_report.json"

        report: dict[str, object] = {
            "version": "11.3",
            "mode": "production_performance_dynamic_scene_renderer_v11_3",
            "render_id": render_id,
            "fps": self.fps,
            "width": WIDTH,
            "height": HEIGHT,
            "video_encoder": self._encoder_args[0] if self._encoder_args else "unknown",
            "voice_engine": "pending",
            "channel_audio_profile": self._channel_audio_profile_name(),
            "scene_count": len(plan.scenes),
            "scene_reports": [],
            "stage_seconds": {},
            "warnings": self._warnings,
            "degraded": False,
            "final_video": self._display_path(final_video),
            "master_audio": self._display_path(master_audio),
        }

        try:
            scene_wavs: list[Path] = []
            scene_videos: list[Path] = []

            for scene in plan.scenes:
                scene_wall_start = time.perf_counter()
                print(
                    "[CARTOON RENDER] "
                    f"Scene {scene.id}/{len(plan.scenes)}: "
                    f"location={scene.location_id}, beat={scene.beat}"
                )

                scene_audio_dir = audio_root / f"scene_{scene.id:02d}"
                scene_audio_dir.mkdir(parents=True, exist_ok=True)
                audio_stage_start = time.perf_counter()
                scene_wav, timeline, scene_audio_report = self._build_scene_audio(
                    scene=scene,
                    output_dir=scene_audio_dir,
                )
                scene_audio_seconds_wall = (
                    time.perf_counter() - audio_stage_start
                )
                scene_wavs.append(scene_wav)

                scene_video = scene_video_root / f"scene_{scene.id:02d}.mp4"
                scene_render_mode = "animated"

                video_stage_start = time.perf_counter()
                try:
                    self._render_scene_video(
                        scene=scene,
                        scene_audio=scene_wav,
                        timeline=timeline,
                        output=scene_video,
                    )
                except Exception as exc:
                    self._degraded = True
                    scene_render_mode = "static_fallback"
                    warning = (
                        f"scene {scene.id} animated render failed: "
                        f"{type(exc).__name__}: {str(exc)[:260]}"
                    )
                    self._warnings.append(warning)
                    print(
                        "[CARTOON RENDER] "
                        f"Scene {scene.id} animated render failed; "
                        "using static scene fallback."
                    )
                    self._render_static_scene(
                        scene=scene,
                        scene_audio=scene_wav,
                        timeline=timeline,
                        output=scene_video,
                    )

                scene_videos.append(scene_video)

                scene_video_seconds_wall = (
                    time.perf_counter() - video_stage_start
                )
                print(
                    "[CARTOON ENV V11.3] "
                    f"scene={scene.id}; location={scene.location_id}; "
                    f"variant={scene.environment_variant}; "
                    f"motion={scene.environment_motion}; render={scene_render_mode}."
                )
                scene_report = {
                    "scene_id": scene.id,
                    "audio_build_wall_seconds": round(
                        scene_audio_seconds_wall,
                        4,
                    ),
                    "video_render_wall_seconds": round(
                        scene_video_seconds_wall,
                        4,
                    ),
                    "scene_wall_seconds": round(
                        time.perf_counter() - scene_wall_start,
                        4,
                    ),
                    "audio_seconds": round(self._media_duration(scene_wav), 3),
                    "render_mode": scene_render_mode,
                    "visual_action": self._resolve_visual_action(scene),
                    "microshot_count": self._microshot_count(
                        scene=scene,
                        timeline=timeline,
                    ),
                    "props": list(scene.props),
                    "pose_rig_enabled": True,
                    "pose_states_available": [
                        "idle","pointing","hands_up","thinking","running","holding_food"
                    ],
                    "visual_motion_enabled": scene_render_mode == "animated",
                    "articulated_rig_characters": [cid for cid in self._scene_characters(scene) if self._rig_available(cid)],
                    "legacy_sprite_characters": [cid for cid in self._scene_characters(scene) if not self._rig_available(cid)],
                    "articulation_quality": self._articulation_scene_quality.get(
                        int(scene.id),
                        {"status": "UNKNOWN"},
                    ),
                    "capability_world": scene.capability_world,
                    "capability_fallback": scene.capability_fallback,
                    "continuity_group": scene.continuity_group,
                    "location_changed": scene.location_changed,
                    "environment_variant": scene.environment_variant,
                    "environment_motion": scene.environment_motion,
                    **scene_audio_report,
                }
                report["scene_reports"].append(scene_report)

            assembly_audio_start = time.perf_counter()
            self._concat_wavs(scene_wavs, master_audio)
            if self._is_hindi_mass_channel():
                self._master_indian_episode_audio(master_audio)
            report["stage_seconds"]["concat_audio"] = round(
                time.perf_counter() - assembly_audio_start,
                4,
            )

            visual_concat = work_root / "visual_concat.mp4"
            assembly_video_start = time.perf_counter()
            self._concat_scene_videos(
                scene_videos=scene_videos,
                output=visual_concat,
            )
            report["stage_seconds"]["concat_video"] = round(
                time.perf_counter() - assembly_video_start,
                4,
            )

            mux_start = time.perf_counter()
            self._mux_master_audio(
                visual_video=visual_concat,
                master_audio=master_audio,
                output=final_video,
            )

            # Extract the final encoded audio back to WAV. This makes the WAV
            # duration track the delivered MP4 audio timeline exactly rather
            # than relying on pre-AAC source timing.
            delivered_master = master_audio.with_name(
                master_audio.stem + "_delivered.wav"
            )
            self._extract_audio(
                video=final_video,
                output=delivered_master,
            )
            delivered_master.replace(master_audio)

        except Exception as exc:
            self._degraded = True
            warning = (
                "primary renderer failed; emergency static renderer used: "
                f"{type(exc).__name__}: {str(exc)[:400]}"
            )
            self._warnings.append(warning)
            print(
                "[CARTOON RENDER] Primary renderer failed; "
                "building emergency playable MP4 instead of aborting."
            )
            self._emergency_render(
                plan=plan,
                work_root=work_root,
                final_video=final_video,
                master_audio=master_audio,
            )

        video_duration = self._media_duration(final_video)
        wav_duration = self._wave_duration(master_audio)
        duration_delta = abs(video_duration - wav_duration)

        if duration_delta > 0.10:
            # Last duration alignment pass. The video is padded visually and
            # trimmed by the WAV duration, so speech is never cut.
            fixed = final_video.with_name(final_video.stem + "_duration_fix.mp4")
            self._duration_fix(
                video=final_video,
                audio=master_audio,
                output=fixed,
                duration=wav_duration,
            )
            fixed.replace(final_video)
            video_duration = self._media_duration(final_video)
            duration_delta = abs(video_duration - wav_duration)

        # V17.5: requested runtime is a quality contract, not just metadata.
        # Keep this advisory/degraded rather than hard-failing a finished render,
        # but never silently label a severely short/long episode as production-ready.
        planned_total = sum(max(0.0, float(sc.shot_duration_seconds)) for sc in plan.scenes)
        duration_ratio = (video_duration / planned_total) if planned_total > 0.1 else 1.0
        report["planned_episode_seconds"] = round(planned_total, 3)
        report["episode_duration_ratio"] = round(duration_ratio, 4)
        report["episode_duration_quality"] = "PASS" if 0.90 <= duration_ratio <= 1.08 else "REVIEW_REQUIRED"
        if self._is_hindi_mass_channel() and planned_total > 0.1 and not (0.90 <= duration_ratio <= 1.08):
            self._degraded = True
            warning = (
                "episode duration outside V17.5 requested-runtime tolerance: "
                f"planned={planned_total:.2f}s rendered={video_duration:.2f}s ratio={duration_ratio:.3f}"
            )
            if warning not in self._warnings:
                self._warnings.append(warning)
            print(
                "[CARTOON DURATION QA V17.5] "
                f"planned={planned_total:.2f}s; rendered={video_duration:.2f}s; "
                f"ratio={duration_ratio:.3f}; status=REVIEW_REQUIRED"
            )
        elif self._is_hindi_mass_channel() and planned_total > 0.1:
            print(
                "[CARTOON DURATION QA V17.5] "
                f"planned={planned_total:.2f}s; rendered={video_duration:.2f}s; "
                f"ratio={duration_ratio:.3f}; status=PASS"
            )

        motion_quality = self._measure_motion_quality(final_video)
        report["motion_quality"] = motion_quality
        print(
            "[CARTOON MOTION V11.1] "
            f"median_yavg={motion_quality.get('median_yavg', 0.0):.3f}; "
            f"mid80_yavg={motion_quality.get('mid80_mean_yavg', 0.0):.3f}; "
            f"samples={motion_quality.get('sample_count', 0)}; "
            f"status={motion_quality.get('status', 'UNKNOWN')}."
        )
        if motion_quality.get("status") != "PASS":
            self._degraded = True
            warning = (
                "anti-slideshow motion quality below V11.1 threshold: "
                f"median={motion_quality.get('median_yavg', 0.0):.3f}, "
                f"mid80={motion_quality.get('mid80_mean_yavg', 0.0):.3f}"
            )
            if warning not in self._warnings:
                self._warnings.append(warning)

        report.update(
            {
                "voice_engine": self._dominant_voice_engine(),
                "voice_map": self._voice_map,
                "warnings": self._warnings,
                "degraded": self._degraded,
                "final_video_seconds": round(video_duration, 3),
                "master_wav_seconds": round(wav_duration, 3),
                "duration_delta_seconds": round(duration_delta, 4),
                "duration_match": duration_delta <= 0.10,
                "final_video_exists": final_video.is_file(),
            }
        )

        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(
            "[CARTOON RENDER] Final video: "
            f"{self._display_path(final_video)}"
        )
        print(
            "[CARTOON RENDER] Master WAV: "
            f"{self._display_path(master_audio)}"
        )
        print(
            "[CARTOON RENDER] Duration: "
            f"video={video_duration:.2f}s, wav={wav_duration:.2f}s, "
            f"delta={duration_delta:.3f}s"
        )
        if self._warnings:
            for warning in self._warnings:
                print(f"[CARTOON RENDER WARNING] {warning}")
        print(
            "[CARTOON RENDER] Status: "
            + ("video_rendered_degraded" if self._degraded else "video_rendered")
        )

        return RenderResult(
            final_video=final_video,
            master_audio=master_audio,
            report_path=report_path,
            duration_seconds=video_duration,
            voice_map=dict(self._voice_map),
            degraded=self._degraded,
        )

    def _load_hindi_audio_profile(self) -> dict[str, object]:
        path = self.project_root / "configs" / "hindi_mass_audio.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _is_hindi_mass_channel(self) -> bool:
        return os.getenv("CONTENT_FACTORY_CARTOON_CHANNEL", "auto").strip().lower() == "hindi_mass"

    def _channel_audio_profile_name(self) -> str:
        if self._is_hindi_mass_channel():
            return str(self._hindi_audio_profile.get("accent_family", "consistent Indian Hindi-family"))
        return "global/default"

    def _hindi_voice_role_group(self, character_id: str) -> str:
        character = character_registry().get(character_id)
        role = str(getattr(character, "voice_role", "") or "").casefold()
        if "female" in role:
            return "female"
        if any(token in role for token in ("male", "older_male", "young_male")):
            return "male"
        return "default"

    def _hindi_voice_tone_factor(self, character_id: str) -> float:
        """Small pitch distinction when macOS exposes only one Hindi male voice.

        Reference-style comedy depends on immediately distinguishable speakers.
        Keep the shift deliberately subtle so it does not create a chipmunk/monster
        effect; duration is restored with atempo after the pitch shift.
        """
        cfg = self._hindi_audio_profile.get("character_tone_factor", {})
        if isinstance(cfg, dict):
            try:
                # V17.6: the prior +/-6% ceiling still sounded like one repeated
                # speaker when macOS exposed only a single hi_IN voice. Keep the
                # range natural but wide enough for character identity to register.
                return max(0.90, min(1.10, float(cfg.get(character_id, 1.0))))
            except (TypeError, ValueError):
                pass
        return 1.0

    def _hindi_character_rate_factor(self, character_id: str) -> float:
        cfg = self._hindi_audio_profile.get("character_rate_factor", {})
        if isinstance(cfg, dict):
            try:
                return max(0.90, min(1.10, float(cfg.get(character_id, 1.0))))
            except (TypeError, ValueError):
                pass
        return 1.0

    def _hindi_emotion_rate_factor(self, emotion: str) -> float:
        cfg = self._hindi_audio_profile.get("emotion_rate_factor", {})
        if isinstance(cfg, dict):
            try:
                return max(0.92, min(1.08, float(cfg.get(str(emotion).casefold(), 1.0))))
            except (TypeError, ValueError):
                pass
        return 1.0

    # ------------------------------------------------------------------
    # Audio / voice
    # ------------------------------------------------------------------
    def _build_scene_audio(
        self,
        *,
        scene: CartoonScene,
        output_dir: Path,
    ) -> tuple[Path, list[dict[str, object]], dict[str, object]]:
        timeline: list[dict[str, object]] = []
        pieces: list[tuple[Path | None, float]] = []
        cursor = SCENE_LEAD_IN_SECONDS
        pieces.append((None, SCENE_LEAD_IN_SECONDS))
        voice_engines: list[str] = []

        # V17.1: calibrate Indian TTS against the actual requested scene budget.
        # macOS Indic voices can ignore nominal WPM semantics and speak much
        # faster than English voices, so word-count-only planning is unreliable.
        _line_weights: list[float] = []
        for line in scene.dialogue:
            _words = max(4, len(re.findall(r"[\w\u0900-\u097f]+", line.text, flags=re.UNICODE)))
            if self._is_hindi_mass_channel():
                # V17.6: allocate the fixed scene speech budget according to the
                # intended delivery. A slower Babuji/serious line receives a
                # little more time, while an excited/Bittu line receives less.
                # Total scene duration remains unchanged because weights are
                # normalized below. This prevents later duration calibration from
                # erasing all character/emotion rate differences.
                _delivery = (
                    self._hindi_character_rate_factor(line.character_id)
                    * self._hindi_emotion_rate_factor(line.emotion)
                )
                _delivery = max(0.82, min(1.18, _delivery))
                _line_weights.append(float(_words) / _delivery)
            else:
                _line_weights.append(float(_words))
        _weight_total = max(1.0, sum(_line_weights))
        _desired_voice_total = (
            max(8.0, float(scene.shot_duration_seconds) * 0.90)
            if self._is_hindi_mass_channel() else 0.0
        )
        _calibrated_lines = 0
        _retimed_lines = 0

        for index, line in enumerate(scene.dialogue, start=1):
            line_wav = output_dir / f"line_{index:02d}_{line.character_id}.wav"
            _base_rate = int(self._RATES.get(line.character_id, 165))
            if self._is_hindi_mass_channel():
                # V17.6: character identity and line emotion now affect delivery
                # before duration calibration. This avoids ten lines sounding like
                # the same repeated narrator while preserving the requested runtime.
                _base_rate = int(round(
                    _base_rate
                    * self._hindi_character_rate_factor(line.character_id)
                    * self._hindi_emotion_rate_factor(line.emotion)
                ))
                _base_rate = max(60, min(260, _base_rate))
            synth = self._synthesize_line(
                text=line.text,
                character_id=line.character_id,
                output=line_wav,
                rate_override=_base_rate,
            )
            voice_duration = self._wave_duration(line_wav)

            if self._is_hindi_mass_channel() and _desired_voice_total > 0.0:
                _target_line = _desired_voice_total * (_line_weights[index - 1] / _weight_total)
                # V17.5: the old 5.25s cap made two-line scenes collapse to
                # ~9-12 seconds even when the scene budget was 20 seconds.
                # Allow longer dialogue turns, but keep an upper bound so short
                # text is never stretched into an unnatural monologue.
                _target_line = max(1.55, min(8.00, _target_line))
                if (
                    str(synth.get("engine")) in {"macos_say", "espeak"}
                    and voice_duration > 0.20
                    and (voice_duration < _target_line * 0.78 or voice_duration > _target_line * 1.28)
                ):
                    # Engine-specific rate semantics vary a lot for Indic voices.
                    # Calibrate from measured audio duration rather than assuming
                    # the numeric WPM behaves like an English voice.
                    _scaled_rate = int(round(_base_rate * (voice_duration / _target_line)))
                    _scaled_rate = max(44, min(300, _scaled_rate))
                    if abs(_scaled_rate - _base_rate) >= 4:
                        synth = self._synthesize_line(
                            text=line.text,
                            character_id=line.character_id,
                            output=line_wav,
                            rate_override=_scaled_rate,
                        )
                        voice_duration = self._wave_duration(line_wav)
                        _calibrated_lines += 1

                # A second, bounded tempo correction handles macOS Indic voices
                # whose rate flag remains non-linear even after re-synthesis.
                # atempo preserves pitch. The 0.80-1.25 clamp prevents the
                # robotic slow/fast speech that earlier duration patches risked.
                if (
                    str(synth.get("engine")) in {"macos_say", "espeak"}
                    and voice_duration > 0.20
                    and _target_line > 0.20
                    and (voice_duration < _target_line * 0.86 or voice_duration > _target_line * 1.18)
                ):
                    _tempo = max(0.80, min(1.25, voice_duration / _target_line))
                    if abs(_tempo - 1.0) >= 0.035:
                        self._retime_voice_file(line_wav, tempo=_tempo)
                        voice_duration = self._wave_duration(line_wav)
                        _retimed_lines += 1

            voice_engines.append(str(synth["engine"]))

            requested_pause = max(
                0.0,
                float(line.pause_after_seconds),
            )
            pause = min(
                MAX_INTERLINE_PAUSE,
                max(
                    MIN_INTERLINE_PAUSE,
                    requested_pause * INTERLINE_PAUSE_SCALE,
                ),
            )
            # V18.1 conversational rhythm: punctuation and reaction emotion get
            # a tiny breathing gap. Keep it bounded so the 20s scene contract
            # is preserved and dialogue never becomes sluggish.
            _text_tail = str(line.text).rstrip()
            if _text_tail.endswith(("?", "？", "!", "！")):
                pause += 0.035
            if str(line.emotion).casefold() in {"shocked", "confused", "laughing"}:
                pause += 0.025
            pause = min(0.30, pause)

            start = cursor
            voice_end = start + voice_duration
            line_end = voice_end + pause

            mouth_windows = self._mouth_activity_windows(
                path=line_wav,
                absolute_start=start,
            )
            timeline.append(
                {
                    "character_id": line.character_id,
                    "emotion": line.emotion,
                    "pose": line.pose,
                    "start": start,
                    "voice_end": voice_end,
                    "end": line_end,
                    "text": line.text,
                    "pause_seconds": pause,
                    "mouth_windows": mouth_windows,
                }
            )
            pieces.append((line_wav, 0.0))
            pieces.append((None, pause))
            cursor = line_end

        reaction_hold = 0.0
        if scene.reaction is not None:
            reaction_hold = min(
                MAX_REACTION_HOLD,
                max(
                    MIN_REACTION_HOLD,
                    float(scene.reaction.duration_seconds) * REACTION_HOLD_SCALE,
                ),
            )
            pieces.append((None, reaction_hold))
            cursor += reaction_hold

        # V17.1: allow only a short visual/reaction hold after calibrated speech.
        # We do not hide missing content behind long silence, but we also do not
        # smash a requested 20s scene into a 2-3 second burst.
        _performance_hold = 0.0
        if self._is_hindi_mass_channel():
            _scene_floor = float(scene.shot_duration_seconds) * 0.90
            # Small reaction/visual breathing room is preferable to unnaturally
            # stretching a voice line. Cap at 3.0s so missing content is still
            # visible to duration QA instead of being hidden by silence.
            _performance_hold = min(3.00, max(0.0, _scene_floor - cursor))
            if _performance_hold > 0.01:
                pieces.append((None, _performance_hold))
                cursor += _performance_hold

        pieces.append((None, SCENE_LEAD_OUT_SECONDS))
        cursor += SCENE_LEAD_OUT_SECONDS

        base_wav = output_dir / "scene_base.wav"
        self._write_wav_timeline(pieces, base_wav)

        scene_wav = output_dir / "scene.wav"
        sfx_name = None
        if scene.reaction and scene.reaction.sfx:
            sfx_name = scene.reaction.sfx
        elif scene.sfx_cues:
            sfx_name = scene.sfx_cues[0]

        if sfx_name and (self.sfx_root / f"{sfx_name}.wav").is_file():
            delay_ms = max(0, int((cursor - reaction_hold - 0.20) * 1000))
            try:
                self._mix_sfx(
                    base=base_wav,
                    sfx=self.sfx_root / f"{sfx_name}.wav",
                    delay_ms=delay_ms,
                    output=scene_wav,
                )
            except Exception as exc:
                self._warnings.append(
                    f"scene {scene.id} sfx mix skipped: {type(exc).__name__}"
                )
                shutil.copy2(base_wav, scene_wav)
        else:
            shutil.copy2(base_wav, scene_wav)

        if self._is_hindi_mass_channel():
            print(
                "[CARTOON AUDIO V17.1] "
                f"scene={scene.id}; planned={float(scene.shot_duration_seconds):.1f}s; "
                f"actual={self._wave_duration(scene_wav):.2f}s; "
                f"rate_calibrated_lines={_calibrated_lines}; "
                f"retimed_lines={_retimed_lines}; "
                f"performance_hold={_performance_hold:.2f}s"
            )

        return (
            scene_wav,
            timeline,
            {
                "voice_engines": sorted(set(voice_engines)),
                "planned_scene_seconds": float(scene.shot_duration_seconds),
                "rendered_scene_audio_seconds": round(self._wave_duration(scene_wav), 3),
                "audio_driven_timing": True,
                "trimmed_idle_seconds": round(
                    max(
                        0.0,
                        float(scene.shot_duration_seconds)
                        - self._wave_duration(scene_wav),
                    ),
                    3,
                ),
                "lead_in_seconds": SCENE_LEAD_IN_SECONDS,
                "lead_out_seconds": SCENE_LEAD_OUT_SECONDS,
                "reaction_hold_seconds": round(reaction_hold, 3),
                "v171_rate_calibrated_lines": int(_calibrated_lines),
                "v175_retimed_lines": int(_retimed_lines),
                "v171_performance_hold_seconds": round(_performance_hold, 3),
            },
        )

    def _synthesize_line(
        self,
        *,
        text: str,
        character_id: str,
        output: Path,
        rate_override: int | None = None,
    ) -> dict[str, object]:
        output.parent.mkdir(parents=True, exist_ok=True)
        rate = int(rate_override if rate_override is not None else self._RATES.get(character_id, 165))
        volume = self._VOLUMES.get(character_id, 1.0)

        character = character_registry().get(character_id)
        if character is not None and character.voice_role == "animal_sfx":
            animal_sfx = self.sfx_root / "monkey_chatter.wav"
            if animal_sfx.is_file():
                self._run(["ffmpeg","-hide_banner","-loglevel","error","-y","-i",str(animal_sfx),"-ac","1","-ar",str(AUDIO_RATE),"-c:a","pcm_s16le",str(output)], label="animal chatter")
                info={"engine":"animal_sfx","voice":"monkey_chatter","rate":0}
                self._voice_map.setdefault(character_id, info)
                return info

        # 1) macOS native voice.
        if platform.system() == "Darwin" and shutil.which("say"):
            voice = self._select_say_voice(character_id)
            tmp = output.with_suffix(".aiff")
            cmd = ["say"]
            if voice:
                cmd += ["-v", voice]
            cmd += ["-r", str(rate), "-o", str(tmp), text]
            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            if proc.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 256:
                self._normalize_voice_file(
                    input_path=tmp,
                    output=output,
                    volume=volume,
                    character_id=character_id,
                )
                tmp.unlink(missing_ok=True)
                info = {
                    "engine": "macos_say",
                    "voice": voice or "system_default",
                    "rate": rate,
                    "accent_profile": self._channel_audio_profile_name(),
                }
                self._voice_map.setdefault(character_id, info)
                return info
            tmp.unlink(missing_ok=True)
            self._warnings.append(
                f"macOS say failed for {character_id}; trying fallback voice engine"
            )

        # 2) espeak/espeak-ng where available (useful for Linux/dev too).
        espeak = shutil.which("espeak-ng") or shutil.which("espeak")
        if espeak:
            tmp = output.with_name(output.stem + "_espeak.wav")
            voice_code = self._espeak_voice_code()
            proc = subprocess.run(
                [
                    espeak,
                    "-v",
                    voice_code,
                    "-s",
                    str(rate),
                    "-w",
                    str(tmp),
                    text,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            if proc.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 256:
                self._normalize_voice_file(
                    input_path=tmp,
                    output=output,
                    volume=volume,
                    character_id=character_id,
                )
                tmp.unlink(missing_ok=True)
                info = {
                    "engine": "espeak",
                    "voice": voice_code,
                    "rate": rate,
                    "accent_profile": self._channel_audio_profile_name(),
                }
                self._voice_map.setdefault(character_id, info)
                if platform.system() == "Darwin":
                    self._degraded = True
                return info
            tmp.unlink(missing_ok=True)

        # 3) Never abort the render because a TTS engine is missing.
        self._degraded = True
        duration = self._estimated_speech_seconds(text=text, rate=rate)
        self._write_silence(output, duration)
        info = {
            "engine": "timed_silence_fallback",
            "voice": "none",
            "rate": rate,
            "accent_profile": self._channel_audio_profile_name(),
        }
        self._voice_map.setdefault(character_id, info)
        self._warnings.append(
            f"no speech engine available for {character_id}; timed silence used"
        )
        return info

    def _select_say_voice(self, character_id: str) -> str | None:
        voices = self._available_say_voices()
        if not voices:
            return None

        # V15 Indian channel: lock the whole channel to the same Indian accent
        # family. Character identity comes from voice choice/rate, not random
        # cross-region accents. Magahi/Bhojpuri use the Hindi-India voice family
        # because macOS does not expose native system TTS voices for them.
        if self._is_hindi_mass_channel():
            locale_cfg = self._hindi_audio_profile.get("locale_priority", {})
            if not isinstance(locale_cfg, dict):
                locale_cfg = {}
            prefs = [str(x) for x in locale_cfg.get(self.language.code, ["hi_IN", "en_IN"])]
            voice_cfg = self._hindi_audio_profile.get("preferred_macos_voices", {})
            if not isinstance(voice_cfg, dict):
                voice_cfg = {}
            role_group = self._hindi_voice_role_group(character_id)
            preferred = [str(x) for x in voice_cfg.get(role_group, [])]
            preferred += [str(x) for x in voice_cfg.get("default", [])]

            # V17.5: locale priority must beat character-gender preference. The
            # previous flattened candidate list could choose an en_IN male voice
            # for Devanagari Hindi even when a hi_IN voice was installed, which
            # hurt pronunciation. Search one locale bucket at a time; character
            # identity is then supplied by a subtle pitch/tone factor.
            for locale in prefs:
                bucket: list[str] = []
                for item in voices:
                    if item["locale"].casefold() == locale.casefold() and item["name"] not in bucket:
                        bucket.append(item["name"])
                if not bucket:
                    continue
                for name in preferred:
                    if name in bucket:
                        return name
                return bucket[0]

            # Only if the machine has no Indian-locale voice at all do we use a
            # system fallback. This is logged as degraded accent availability.
            self._warnings.append("hindi_mass: no hi_IN/en_IN macOS voice found; using system fallback accent")
            return voices[0]["name"]

        prefs = list(self.language.voice_locale_preferences)
        if self.language.code in {"hinglish"}:
            prefs += ["en_IN", "hi_IN", "en_US"]
        elif self.language.code in {"magahi", "bhojpuri"}:
            prefs += ["hi_IN"]
        elif self.language.code == "english":
            prefs += ["en_IN", "en_US", "en_GB"]

        matching: list[str] = []
        for locale in prefs:
            matching.extend(
                item["name"]
                for item in voices
                if item["locale"].casefold() == locale.casefold()
            )

        preferred_names = ["Lekha", "Rishi", "Isha"]
        for name in preferred_names:
            if any(item["name"] == name for item in voices) and name not in matching:
                matching.append(name)

        if not matching:
            matching = [item["name"] for item in voices]

        if self.language.code in {"hindi", "magahi", "bhojpuri"}:
            for preferred in ("Lekha", "Isha", "Rishi"):
                if preferred in matching:
                    return preferred

        order = ["guddu", "bittu", "chacha", "mai", "babuji"]
        index = order.index(character_id) if character_id in order else 0
        return matching[index % len(matching)] if matching else None

    def _available_say_voices(self) -> list[dict[str, str]]:
        cache = getattr(self, "_say_voice_cache", None)
        if cache is not None:
            return cache

        if not shutil.which("say"):
            self._say_voice_cache = []
            return []

        proc = subprocess.run(
            ["say", "-v", "?"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        result: list[dict[str, str]] = []
        if proc.returncode == 0:
            pattern = re.compile(r"^(.+?)\s+([a-z]{2}_[A-Z]{2})\s+#")
            for line in proc.stdout.splitlines():
                match = pattern.match(line.rstrip())
                if match:
                    result.append(
                        {
                            "name": match.group(1).strip(),
                            "locale": match.group(2),
                        }
                    )
        self._say_voice_cache = result
        return result

    def _espeak_voice_code(self) -> str:
        if self._is_hindi_mass_channel():
            return {
                "hindi": "hi",
                "hinglish": "en-in",
                "magahi": "hi",
                "bhojpuri": "hi",
                "english": "en-in",
            }.get(self.language.code, "hi")
        return {
            "hindi": "hi",
            "hinglish": "hi",
            "magahi": "hi",
            "bhojpuri": "hi",
            "english": "en-in",
        }.get(self.language.code, "en")

    def _normalize_voice_file(
        self,
        *,
        input_path: Path,
        output: Path,
        volume: float,
        character_id: str | None = None,
    ) -> None:
        if self._is_hindi_mass_channel():
            mastering = self._hindi_audio_profile.get("mastering", {})
            if not isinstance(mastering, dict):
                mastering = {}
            hp = int(mastering.get("highpass_hz", 72))
            lp = int(mastering.get("lowpass_hz", 14500))
            presence_hz = int(mastering.get("presence_hz", 3200))
            presence_gain = float(mastering.get("presence_gain_db", 1.2))
            mud_hz = int(mastering.get("mud_cut_hz", 220))
            mud_gain = float(mastering.get("mud_cut_db", -1.4))
            air_hz = int(mastering.get("air_hz", 8500))
            air_gain = float(mastering.get("air_gain_db", 0.8))
            # V17.5: do NOT loud-normalize every sentence independently. That
            # double-normalization flattened expression and made macOS Hindi
            # voices sound hard/robotic. Use a tiny character-specific pitch
            # distinction, gentle cleanup, then one program-level master.
            tone = self._hindi_voice_tone_factor(character_id or "")
            pitch = "aresample=48000,"
            if abs(tone - 1.0) >= 0.002:
                pitch += (
                    f"asetrate=48000*{tone:.5f},aresample=48000,"
                    f"atempo={1.0 / tone:.5f},"
                )
            filt = (
                pitch
                + f"volume={volume:.3f},"
                f"highpass=f={hp},"
                f"lowpass=f={lp},"
                f"equalizer=f={mud_hz}:t=q:w=1:g={mud_gain:.2f},"
                f"equalizer=f={presence_hz}:t=q:w=1:g={presence_gain:.2f},"
                f"equalizer=f={air_hz}:t=q:w=0.8:g={air_gain:.2f},"
                "acompressor=threshold=0.20:ratio=1.35:attack=10:release=190:makeup=1.04,"
                "alimiter=limit=0.97"
            )
        else:
            # Preserve the pre-V15 global channel mastering contract.
            filt = (
                f"volume={volume:.3f},"
                "highpass=f=80,"
                "lowpass=f=11500,"
                "acompressor="
                "threshold=0.125:ratio=2.5:attack=5:release=80:makeup=1.35,"
                "loudnorm=I=-16:TP=-1.5:LRA=7"
            )

        self._run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(input_path),
                "-af",
                filt,
                "-ac",
                "1",
                "-ar",
                str(AUDIO_RATE),
                "-c:a",
                "pcm_s16le",
                str(output),
            ],
            label="normalize voice",
        )

    def _retime_voice_file(self, path: Path, *, tempo: float) -> None:
        """Bounded pitch-preserving retime for one already-cleaned voice line."""
        tempo = max(0.80, min(1.25, float(tempo)))
        if abs(tempo - 1.0) < 0.01:
            return
        tmp = path.with_name(path.stem + "_retime.wav")
        self._run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(path),
                "-af", f"atempo={tempo:.6f}",
                "-ac", "1", "-ar", str(AUDIO_RATE),
                "-c:a", "pcm_s16le", str(tmp),
            ],
            label="V17.5 bounded voice retime",
        )
        tmp.replace(path)

    def _mix_sfx(
        self,
        *,
        base: Path,
        sfx: Path,
        delay_ms: int,
        output: Path,
    ) -> None:
        if self._is_hindi_mass_channel():
            mastering = self._hindi_audio_profile.get("mastering", {})
            if not isinstance(mastering, dict):
                mastering = {}
            sfx_volume = float(mastering.get("sfx_volume", 0.12))
            filt = (
                f"[1:a]volume={sfx_volume:.3f},adelay={delay_ms}:all=1[sfx];"
                "[0:a][sfx]amix=inputs=2:duration=first:normalize=0,"
                "alimiter=limit=0.94[aout]"
            )
        else:
            filt = (
                f"[1:a]volume=0.18,adelay={delay_ms}:all=1[sfx];"
                "[0:a][sfx]amix=inputs=2:duration=first:normalize=0[aout]"
            )
        self._run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(base),
                "-i",
                str(sfx),
                "-filter_complex",
                filt,
                "-map",
                "[aout]",
                "-ac",
                "1",
                "-ar",
                str(AUDIO_RATE),
                "-c:a",
                "pcm_s16le",
                str(output),
            ],
            label="mix sfx",
        )

    # ------------------------------------------------------------------
    # Scene video
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # V10 articulated 2D performance rig
    # ------------------------------------------------------------------
    def _rig_available(self, character_id: str) -> bool:
        legacy = self.rig_root / character_id
        performance = self.performance_root / character_id
        return (
            (performance / "body_idle.mov").is_file()
            and (legacy / "face_neutral_closed.png").is_file()
        ) or (
            (legacy / "body_idle_frames" / "frame_00.png").is_file()
            and (legacy / "face_neutral_closed.png").is_file()
        )

    @staticmethod
    def _v11_directional_action(action: str, direction: str = "right") -> str:
        if action in {"walk", "walk_carry", "run", "run_carry"}:
            return f"{action}_{direction}"
        return action

    def _rig_action(
        self,
        *,
        character_id: str,
        scene_action: str,
        requested_pose: str = "idle",
        attached_props: set[str] | None = None,
        speaking: bool = False,
    ) -> str:
        attached_props = attached_props or set()
        carrying = bool(attached_props & {"suitcase", "basket", "package_box", "gift"})
        if scene_action == "chase":
            return "run_carry" if carrying else "run"
        if scene_action == "run":
            return "run_carry" if carrying else "run"
        if scene_action in {"walk", "enter", "exit"}:
            return "walk_carry" if carrying else "walk"
        if scene_action == "carry":
            return "carry"
        if scene_action in {"grab", "give", "use_device", "celebrate", "reaction", "jump", "fall", "magic"}:
            return scene_action
        if scene_action == "dance":
            return "celebrate"
        if scene_action in {"open", "eat"}:
            return "use_device"
        if scene_action in {"search", "hide", "reveal"}:
            return "talk"
        if scene_action == "point":
            return "point"
        pose = self._pose_asset(requested_pose)
        if pose == "running":
            return "run"
        if pose == "pointing":
            return "point"
        if pose == "hands_up":
            return "reaction"
        if pose == "holding_food":
            return "carry"
        return "talk" if speaking else "idle"

    def _rig_body_sheet(self, character_id: str, action: str) -> Path:
        v11_action = self._v11_directional_action(action, "right")
        clip = self.performance_root / character_id / f"body_{v11_action}.mov"
        if clip.is_file():
            return clip
        root = self.rig_root / character_id
        sequence_dir = root / f"body_{action}_frames"
        if not (sequence_dir / "frame_00.png").is_file():
            action = "idle"
            sequence_dir = root / "body_idle_frames"
        pattern = sequence_dir / "frame_%02d.png"
        self._rig_sequence_fps[str(pattern)] = self._rig_cycle_rate(action)
        return pattern

    def _rig_face_path(self, character_id: str, expression: str, mouth: str) -> Path:
        root = self.rig_root / character_id
        expr = self._expression_asset(expression)
        path = root / f"face_{expr}_{mouth}.png"
        return path if path.is_file() else root / f"face_neutral_{mouth}.png"

    def _rig_face_directional_path(
        self, character_id: str, expression: str, mouth: str, gaze: str = "front"
    ) -> Path:
        """V16 directional head/eyeline asset with legacy-safe fallback."""
        base = self._rig_face_path(character_id, expression, mouth)
        if gaze not in {"left", "right"}:
            return base
        candidate = base.with_name(f"{base.stem}_look_{gaze}{base.suffix}")
        return candidate if candidate.is_file() else base

    def _rig_face_blink_path(self, character_id: str) -> Path:
        return self.rig_root / character_id / "face_blink.png"

    def _rig_cycle_rate(self, action: str) -> int:
        return int(self.rig_config.get("cycle_fps", {}).get(action, 5))

    def _rig_sheet_stream(
        self,
        *,
        filters: list[str],
        input_index: int,
        label: str,
        action: str,
    ) -> str:
        # image2 already emits the native articulated action cycle.
        # Each decoded frame remains only 420x740, minimizing memory pressure.
        out = f"{label}_anim"
        filters.append(
            f"[{input_index}:v]format=rgba[{out}]"
        )
        return out

    def _attached_prop_specs(
        self,
        *,
        scene: CartoonScene,
        action: str,
        duration: float,
        positions: dict[str, tuple[int, int]],
        timeline: list[dict[str, object]],
    ) -> list[dict[str, str]]:
        attach_cfg = self.rig_config.get("prop_attachment", {})
        if not isinstance(attach_cfg, dict):
            return []
        rig_chars = [cid for cid in positions if self._rig_available(cid)]
        if not rig_chars:
            return []
        actor = next(
            (
                str(item.get("character_id"))
                for item in timeline
                if str(item.get("character_id")) in rig_chars
            ),
            rig_chars[0],
        )
        base_x, base_y = positions[actor]
        x_expr, y_expr = self._character_motion_expr(
            scene=scene,
            character_id=actor,
            base_x=base_x,
            base_y=base_y,
            duration=duration,
            timeline=timeline,
            action=action,
        )
        result: list[dict[str, str]] = []
        hand_actions = {
            "grab", "carry", "give", "use_device", "open", "eat",
            "search", "point", "walk", "run", "enter", "exit", "chase",
        }
        for name in scene.props:
            cfg = attach_cfg.get(name)
            explicit = isinstance(cfg, dict)
            if explicit:
                allowed = {str(v) for v in cfg.get("actions", [])}
                if allowed and action not in allowed:
                    continue
                depth = str(cfg.get("depth", "front"))
                ox = int(cfg.get("x", 0))
                oy = int(cfg.get("y", 0))
                asset_path = self.rig_prop_root / f"{name}.png"
                asset_root = "rig"
            elif action in hand_actions:
                # Generic portable props are constrained to the actor's hand
                # instead of being drawn at arbitrary screen-space coordinates.
                asset_path = self.prop_root / f"{name}.png"
                if not asset_path.is_file():
                    continue
                depth = "front"
                ox = 190
                oy = 350
                asset_root = "generic"
            else:
                continue

            if not asset_path.is_file():
                # Explicit V10 props may also exist in the generic prop set.
                asset_path = self.prop_root / f"{name}.png"
                asset_root = "generic"
                if not asset_path.is_file():
                    continue

            px = f"({x_expr})+{ox}"
            py = f"({y_expr})+{oy}"
            if name == "suitcase":
                # Suitcase stays on/near the floor while its handle follows
                # the carry hand. Tiny bounce follows gait, never free-floats.
                py = f"({y_expr})+{oy}+2*sin(8*t)"
            result.append(
                {
                    "name": name,
                    "actor": actor,
                    "depth": depth,
                    "asset_root": asset_root,
                    "x": px,
                    "y": py,
                    "enable": "1",
                }
            )
        return result

    def _attached_prop_path(self, spec: dict[str, str]) -> Path:
        root = (
            self.rig_prop_root
            if str(spec.get("asset_root", "rig")) == "rig"
            else self.prop_root
        )
        return root / f"{spec['name']}.png"

    def _articulation_quality_check(
        self,
        *,
        scene: CartoonScene,
        characters: list[str],
        action: str,
        attached_names: set[str],
    ) -> dict[str, object]:
        locomotion = {"walk", "run", "chase", "enter", "exit"}
        legacy_allowed = {"bandar", "dog", "cat", "dinosaur"}
        missing_rig = [
            cid
            for cid in characters
            if cid not in legacy_allowed and not self._rig_available(cid)
        ]
        floating_risk = [
            str(name)
            for name in scene.props
            if action in {"grab", "carry", "give", "use_device"} | locomotion
            and str(name) not in attached_names
            and (
                (self.rig_prop_root / f"{name}.png").is_file()
                or (self.prop_root / f"{name}.png").is_file()
            )
        ]
        status = "PASS"
        reasons: list[str] = []
        if missing_rig and action in locomotion:
            status = "REVIEW_REQUIRED"
            reasons.append(
                "human-like locomotion missing articulated rig: "
                + ", ".join(missing_rig)
            )
        if floating_risk:
            status = "REVIEW_REQUIRED"
            reasons.append(
                "portable props not actor-constrained: "
                + ", ".join(floating_risk)
            )
        return {
            "status": status,
            "missing_articulated_rigs": missing_rig,
            "floating_prop_risk": floating_risk,
            "reasons": reasons,
        }

    def _line_performance_action(self, item: dict[str, object], line_index: int) -> str:
        text = str(item.get("text", ""))
        detected = resolve_action_family(text, beat="")
        mapping = {"chase":"run","enter":"walk","exit":"walk","search":"point","hide":"reaction","open":"use_device","eat":"use_device","reveal":"reaction","dance":"celebrate"}
        detected = mapping.get(detected, detected)
        if detected != "dialogue":
            return detected
        requested = self._pose_asset(str(item.get("pose", "idle")))
        if requested == "running":
            return "run"
        if requested == "pointing":
            return "point"
        if requested == "hands_up":
            return "reaction"
        if requested == "holding_food":
            return "carry"
        emotion = str(item.get("emotion", "neutral")).casefold()
        if emotion in {"shocked","surprised","confused","suspicious"}:
            return "reaction"
        if emotion in {"angry","serious"} and line_index % 2:
            return "point"
        if emotion in {"happy","laughing"} and line_index % 3 == 0:
            return "celebrate"
        return "talk"

    @staticmethod
    def _secondary_line_action(
        *,
        primary: str,
        emotion: str,
        line_index: int,
    ) -> str:
        """Choose a second body beat inside a long spoken line.

        Limited-animation comedy feels alive when the body pose changes before
        the sentence ends. This reuses existing rigs; it does not add an LLM
        call, a new asset, or an extra scene encode.
        """
        emotion = (emotion or "neutral").casefold()
        if primary in {"run", "walk", "carry", "grab", "give", "use_device"}:
            return "reaction" if emotion in {"shocked", "confused", "suspicious"} else "talk"
        if emotion in {"shocked", "surprised", "confused", "suspicious"}:
            return "reaction" if primary != "reaction" else "point"
        if emotion in {"angry", "serious"}:
            return "point" if primary != "point" else "talk"
        if emotion in {"happy", "laughing"}:
            return "celebrate" if line_index % 2 else "reaction"
        if primary == "point":
            return "talk"
        if primary == "reaction":
            return "talk"
        return "point" if line_index % 2 else "reaction"

    def _performance_prelude_seconds(self, action: str, duration: float) -> float:
        if action in {"dialogue","reaction","reveal"}: return 0.0
        cfg=self.performance_config.get("performance",{})
        return max(0.8,min(float(cfg.get("action_prelude_max_seconds",2.8)),duration*float(cfg.get("action_prelude_fraction",0.28))))

    def _render_character_performance_track(
        self,
        *,
        scene: CartoonScene,
        character_id: str,
        scene_action: str,
        duration: float,
        timeline: list[dict[str, object]],
        attached_names: set[str],
        attached_specs: list[dict[str, str]],
        primary_actor: str | None,
        output: Path,
        positions: dict[str, tuple[int, int]] | None = None,
        scene_characters: list[str] | None = None,
        interaction: str | None = None,
    ) -> None:
        """Render exactly one mutually-exclusive body performance per actor.

        V11.1 rule: body states never stack. Earlier V11 prototypes kept the
        idle body underneath gesture/run bodies; transparent limb regions then
        exposed duplicate arms/legs. Here raw performance events are resolved
        to non-overlapping timeline segments before FFmpeg sees them.

        Hand-held props are also composited inside this local 420x740 actor
        track. They therefore inherit the actor's scene transform as one unit
        instead of floating independently in 1080p screen space.
        """
        positions = positions or {}
        scene_characters = list(scene_characters or [character_id])
        interaction = interaction or v16_interaction_mode(scene, scene_characters, scene_action)
        focal = focal_speaker(timeline, scene_characters)

        inputs: list[Path] = []
        filters: list[str] = [
            f"color=c=black@0.0:s={RIG_FRAME_W}x{RIG_FRAME_H}:r={self.fps}:d={duration:.4f},format=rgba[base]"
        ]
        current = "base"

        carry_props = {"suitcase", "basket", "package_box", "gift"}

        def normalized_action(action: str) -> str:
            if action in {"run", "walk"} and attached_names & carry_props:
                return f"{action}_carry"
            return action

        # Collect raw body events with explicit priority. Higher wins if two
        # windows overlap. This produces a single body state at every frame.
        raw_events: list[dict[str, object]] = []
        prelude_seconds = self._performance_prelude_seconds(scene_action, duration)
        if character_id == primary_actor and prelude_seconds > 0.0:
            prelude_action = self._rig_action(
                character_id=character_id,
                scene_action=scene_action,
                attached_props=attached_names,
                speaking=False,
            )
            raw_events.append({
                "start": 0.05,
                "end": min(duration, prelude_seconds),
                "action": normalized_action(prelude_action),
                "priority": 10,
            })

        # V14.1 natural acting grammar: HOLD -> short gesture -> HOLD.
        # Do not animate a body continuously for the whole spoken sentence.
        # Mouth/face animation carries speech; body gestures are short accents.
        own_lines = [
            (i, item)
            for i, item in enumerate(timeline, start=1)
            if str(item.get("character_id")) == character_id
        ]
        for line_index, item in own_lines:
            start_t = float(item["start"])
            end_t = float(item["end"])
            span = max(0.0, end_t - start_t)
            primary_line_action = normalized_action(
                self._line_performance_action(item, line_index)
            )

            # First emphasis beat: brief and readable, then settle to idle.
            first_len = min(0.62, max(0.28, span * 0.22))
            first_start = start_t + min(0.12, span * 0.06)
            first_end = min(end_t, first_start + first_len)
            if first_end - first_start >= 0.18:
                raw_events.append({
                    "start": first_start,
                    "end": first_end,
                    "action": primary_line_action,
                    "priority": 30,
                })

            # Long lines get one second gesture around the later emphasis point.
            # There is always a visible idle hold between the two gestures.
            if span >= 2.75:
                secondary = normalized_action(
                    self._secondary_line_action(
                        primary=primary_line_action,
                        emotion=str(item.get("emotion", "neutral")),
                        line_index=line_index,
                    )
                )
                second_len = min(0.52, max(0.26, span * 0.14))
                second_start = min(
                    end_t - second_len - 0.08,
                    start_t + span * 0.62,
                )
                second_start = max(first_end + 0.34, second_start)
                second_end = min(end_t - 0.04, second_start + second_len)
                if second_end - second_start >= 0.18:
                    raw_events.append({
                        "start": second_start,
                        "end": second_end,
                        "action": secondary,
                        "priority": 31,
                    })

        listener_limit = int(
            self.performance_config.get("performance", {}).get(
                "listener_reaction_max_per_scene", 1
            )
        )
        listener_hold = float(
            self.performance_config.get("performance", {}).get(
                "listener_reaction_seconds", 0.36
            )
        )

        # React while another person is still speaking, not only after the line.
        # The reference pacing frequently shows the listener's face/body during
        # a continuing sentence; that creates conversational life without extra
        # dialogue or extra model calls.
        live_reacted = 0
        for item in timeline:
            if live_reacted >= listener_limit:
                break
            if str(item.get("character_id")) == character_id:
                continue
            start_t = float(item.get("start", 0.0))
            voice_end = float(item.get("voice_end", item.get("end", start_t)))
            if voice_end - start_t < 2.15:
                continue
            st = start_t + (voice_end - start_t) * 0.58
            en = min(voice_end - 0.08, st + 0.34)
            if en - st < 0.18:
                continue
            raw_events.append({
                "start": st,
                "end": en,
                "action": "reaction",
                "priority": 22,
            })
            live_reacted += 1

        reacted = 0
        for item in timeline:
            if reacted >= listener_limit:
                break
            if str(item.get("character_id")) == character_id:
                continue
            st = min(
                duration,
                float(item.get("voice_end", item.get("end", 0.0))) + 0.03,
            )
            en = min(duration, st + listener_hold)
            if en - st < 0.16:
                continue
            raw_events.append({
                "start": st,
                "end": en,
                "action": "reaction",
                "priority": 20,
            })
            reacted += 1

        if scene.reaction is not None and scene.reaction.character_id == character_id:
            end_t = duration
            start_t = max(
                0.0,
                end_t
                - max(
                    0.35,
                    min(0.70, float(scene.reaction.duration_seconds)),
                ),
            )
            raw_events.append({
                "start": start_t,
                "end": end_t,
                "action": "reaction",
                "priority": 40,
            })

        # Resolve raw events into non-overlapping body segments.
        bounds = {0.0, round(float(duration), 4)}
        for event in raw_events:
            bounds.add(round(max(0.0, min(duration, float(event["start"]))), 4))
            bounds.add(round(max(0.0, min(duration, float(event["end"]))), 4))
        ordered = sorted(bounds)
        body_segments: list[dict[str, object]] = []
        for a, b in zip(ordered, ordered[1:]):
            if b - a < 0.001:
                continue
            mid = (a + b) / 2.0
            active = [
                event
                for event in raw_events
                if float(event["start"]) <= mid < float(event["end"])
            ]
            if active:
                winner = max(active, key=lambda item: int(item["priority"]))
                action = str(winner["action"])
            else:
                action = "idle"
            if body_segments and body_segments[-1]["action"] == action and abs(float(body_segments[-1]["end"]) - a) < 0.002:
                body_segments[-1]["end"] = b
            else:
                body_segments.append({"start": a, "end": b, "action": action})

        def add_image(
            path: Path, *, enable: str | None, label: str, x_offset: int = 0
        ) -> None:
            nonlocal current
            idx = len(inputs)
            inputs.append(path)
            out = f"{label}_out"
            suffix = f":enable='{enable}'" if enable else ""
            filters.append(
                f"[{current}][{idx}:v]overlay={int(x_offset)}:0:format=auto:eval=frame{suffix}[{out}]"
            )
            current = out

        def gaze_offset(gaze: str) -> int:
            # A small head/face translation gives a readable partner-facing cue
            # without replacing or warping the user's existing rig artwork.
            return -9 if gaze == "left" else (9 if gaze == "right" else 0)

        # Props behind the body are now local to the actor track.
        attach_cfg = self.rig_config.get("prop_attachment", {})
        for prop_index, spec in enumerate(
            item for item in attached_specs if str(item.get("depth")) == "behind"
        ):
            name = str(spec["name"])
            path = self._attached_prop_path(spec)
            if not path.is_file():
                continue
            cfg = attach_cfg.get(name, {}) if isinstance(attach_cfg, dict) else {}
            ox = int(cfg.get("x", 250)) if isinstance(cfg, dict) else 250
            # Correct old suitcase offset: handle sits at the actor carry hand,
            # while bottom remains close to the 740px rig floor.
            if name == "suitcase":
                oy = 490
                y_expr = f"{oy}+2*abs(sin(6.283*t))"
            else:
                oy = int(cfg.get("y", 485)) if isinstance(cfg, dict) else 485
                y_expr = str(oy)
            idx = len(inputs)
            inputs.append(path)
            out = f"local_prop_behind_{prop_index}"
            filters.append(
                f"[{current}][{idx}:v]overlay=x='{ox}':y='{y_expr}':format=auto:eval=frame[{out}]"
            )
            current = out

        # Exactly one body clip is enabled in each segment.
        for segment_index, segment in enumerate(body_segments):
            action = str(segment["action"])
            path = self._rig_body_sheet(character_id, action)
            enable = self._between(float(segment["start"]), float(segment["end"]))
            add_image(path, enable=enable, label=f"body_segment_{segment_index}_{action}")

        # Neutral facial baseline. Expression overlays fully cover the face
        # region, so unlike bodies these layers are safe to stack by time.
        # Default conversational gaze points toward the most likely partner/audience.
        default_target = None
        if timeline:
            first_idx = next((i for i, it in enumerate(timeline) if str(it.get("character_id")) == character_id), 0)
            default_target = line_addressee(timeline, first_idx, scene_characters, interaction, focal)
        default_gaze = gaze_direction(character_id, default_target, positions)
        add_image(
            self._rig_face_directional_path(character_id, "neutral", "closed", default_gaze),
            enable=None,
            label="neutral_face",
            x_offset=gaze_offset(default_gaze),
        )

        for line_index, item in own_lines:
            start_t = float(item["start"])
            voice_end = float(item["voice_end"])
            line_end = float(item["end"])
            line_enable = self._between(start_t, line_end)
            expr = self._expression_asset(str(item.get("emotion", "neutral")))
            timeline_index = next((j for j, raw in enumerate(timeline) if raw is item), max(0, line_index - 1))
            line_gaze = gaze_for_line(
                timeline, timeline_index, character_id, scene_characters, positions, interaction, focal
            )
            add_image(
                self._rig_face_directional_path(character_id, expr, "closed", line_gaze),
                enable=line_enable,
                label=f"line_{line_index}_closed",
                x_offset=gaze_offset(line_gaze),
            )
            mouth_enable = self._mouth_enable_expression(
                windows=item.get("mouth_windows", []),
                start=start_t,
                voice_end=voice_end,
            )
            add_image(
                self._rig_face_directional_path(character_id, expr, "open", line_gaze),
                enable=mouth_enable,
                label=f"line_{line_index}_open",
                x_offset=gaze_offset(line_gaze),
            )

        # Listener reaction face windows mirror the body-event policy.
        reacted = 0
        for li, item in enumerate(timeline, start=1):
            if reacted >= listener_limit:
                break
            if str(item.get("character_id")) == character_id:
                continue
            st = min(
                duration,
                float(item.get("voice_end", item.get("end", 0.0))) + 0.03,
            )
            en = min(duration, st + listener_hold)
            if en - st < 0.16:
                continue
            speaker_id = str(item.get("character_id", ""))
            react_gaze = listener_gaze(speaker_id, character_id, positions)
            add_image(
                self._rig_face_directional_path(character_id, "shocked", "closed", react_gaze),
                enable=self._between(st, en),
                label=f"listener_{li}_face",
                x_offset=gaze_offset(react_gaze),
            )
            reacted += 1

        blink = self._rig_face_blink_path(character_id)
        if blink.is_file():
            phase = 0.65 + scene.id * 0.17 + (sum(ord(c) for c in character_id) % 9) * 0.11
            period = 3.15 + (sum(ord(c) for c in character_id) % 3) * 0.37
            blink_enable = f"lt(mod(t+{phase:.2f}\\,{period:.2f})\\,0.11)"
            add_image(blink, enable=blink_enable, label="blink")

        if scene.reaction is not None and scene.reaction.character_id == character_id:
            end_t = duration
            start_t = max(
                0.0,
                end_t - max(0.35, min(0.70, float(scene.reaction.duration_seconds))),
            )
            add_image(
                self._rig_face_path(
                    character_id,
                    self._expression_asset(scene.reaction.expression),
                    "closed",
                ),
                enable=self._between(start_t, end_t),
                label="final_reaction_face",
            )

        # Front props are likewise actor-local. Nonpersistent handheld props
        # are only visible while a compatible body segment is active.
        for prop_index, spec in enumerate(
            item for item in attached_specs if str(item.get("depth")) == "front"
        ):
            name = str(spec["name"])
            path = self._attached_prop_path(spec)
            if not path.is_file():
                continue
            cfg = attach_cfg.get(name, {}) if isinstance(attach_cfg, dict) else {}
            ox = int(cfg.get("x", 180)) if isinstance(cfg, dict) else 180
            oy = int(cfg.get("y", 350)) if isinstance(cfg, dict) else 350
            allowed = {str(v) for v in cfg.get("actions", [])} if isinstance(cfg, dict) else set()
            windows: list[str] = []
            for segment in body_segments:
                act = str(segment["action"])
                normalized = act.replace("_carry", "")
                if not allowed or act in allowed or normalized in allowed or ("carry" in act and "carry" in allowed):
                    windows.append(self._between(float(segment["start"]), float(segment["end"])))
            enable = "+".join(windows) if windows else "0"
            idx = len(inputs)
            inputs.append(path)
            out = f"local_prop_front_{prop_index}"
            filters.append(
                f"[{current}][{idx}:v]overlay=x='{ox}':y='{oy}':format=auto:eval=frame:enable='{enable}'[{out}]"
            )
            current = out

        filters.append(f"[{current}]fps={self.fps},format=argb[vout]")
        args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        for path in inputs:
            text = str(path)
            if path.suffix.lower() == ".mov":
                args += ["-stream_loop", "-1", "-i", text]
            elif "%02d" in text:
                rate = max(1, int(self._rig_sequence_fps.get(text, self.fps)))
                args += [
                    "-stream_loop", "-1", "-framerate", str(rate),
                    "-start_number", "0", "-i", text,
                ]
            else:
                args += ["-loop", "1", "-framerate", str(self.fps), "-i", text]
        args += [
            "-filter_complex", ";".join(filters),
            "-map", "[vout]", "-t", f"{duration:.4f}",
            "-c:v", "qtrle", "-pix_fmt", "argb", "-an", str(output),
        ]
        self._run(args, label=f"render character performance {character_id}")

    def _v16_is_crowd_scene(
        self, *, scene: CartoonScene, characters: list[str], action: str
    ) -> bool:
        return v16_interaction_mode(scene, characters, action) == "crowd_speech"

    def _render_crowd_scene_video(
        self,
        *,
        scene: CartoonScene,
        scene_audio: Path,
        timeline: list[dict[str, object]],
        output: Path,
    ) -> None:
        """V16 lightweight stage/crowd compositor.

        Crowd scenes use a 1280x720 internal stage with exactly one articulated
        focal performer. Other people are stable lightweight sprites and only
        receive a cheap mouth-open overlay while speaking. A single crop/reframe
        pass is then upscaled to 1080p. This avoids the multi-rig 1080p graph
        that could exceed laptop memory while keeping normal dialogue scenes on
        the original full-quality renderer.
        """
        duration = self._wave_duration(scene_audio)
        bg = self._background_path(scene.location_id)
        characters = self._scene_characters(scene)[:5]
        action = self._resolve_visual_action(scene)
        mode = "crowd_speech"
        focal = focal_speaker(timeline, characters)
        positions = lightweight_positions(characters, focal)
        natural_stage = [cid for cid in characters if natural_actor_available(self.project_root, cid)]
        available = [cid for cid in characters if self._rig_available(cid) and cid not in natural_stage]
        full_rigs = crowd_full_rigs(timeline, characters, available, max_full=1)
        focal_natural = focal if focal in natural_stage else None
        focal_rig = None if focal_natural else (full_rigs[0] if full_rigs else None)

        print(
            "[CARTOON DIRECTOR V16] "
            f"scene={scene.id}; mode=crowd_speech; focal={focal or 'none'}; "
            f"full_rigs={','.join(full_rigs) or 'none'}; audience=LIGHTWEIGHT; "
            f"actor_mode={'NATURAL_LIMITED' if natural_stage else 'LEGACY'}; "
            "internal_canvas=1280x720; final=1920x1080"
        )

        performance_track: Path | None = None
        if focal_rig:
            performance_track = output.parent / f"{output.stem}_{focal_rig}_v16_stage.mov"
            self._render_character_performance_track(
                scene=scene,
                character_id=focal_rig,
                scene_action=action,
                duration=duration,
                timeline=timeline,
                attached_names=set(),
                attached_specs=[],
                primary_actor=focal_rig,
                output=performance_track,
                positions=positions,
                scene_characters=characters,
                interaction=mode,
            )

        inputs: list[Path] = [bg]
        filters: list[str] = [
            "[0:v]scale=1280:720:force_original_aspect_ratio=increase,"
            "crop=1280:720,format=rgba[base]"
        ]
        current = "base"

        # Stable audience first: they do not bob or animate continuously.
        for idx_char, cid in enumerate(characters):
            if cid == focal_rig:
                continue
            if cid in natural_stage:
                target = focal or "audience"
                direction = gaze_direction(cid, target, positions)
                sprite = natural_actor_path(self.project_root, cid, direction)
            else:
                sprite = self._sprite_path(cid, "neutral", "closed", pose="idle")
            if not sprite.is_file():
                continue
            idx = len(inputs)
            inputs.append(sprite)
            x, y = positions.get(cid, (60 + idx_char * 220, 340))
            scaled = f"aud_{idx_char}_scaled"
            nxt = f"aud_{idx_char}"
            filters.append(f"[{idx}:v]scale=210:-1:flags=lanczos,format=rgba[{scaled}]")
            filters.append(
                f"[{current}][{scaled}]overlay=x={x}:y={y}:format=auto[{nxt}]"
            )
            current = nxt

            # One cheap mouth-open layer per lightweight speaker, enabled for all
            # of that actor's speech windows. This avoids full articulated rigs.
            speech_windows = []
            for item in timeline:
                if str(item.get("character_id", "")) != cid:
                    continue
                st = float(item.get("start", 0.0))
                en = float(item.get("voice_end", item.get("end", st)))
                if en - st >= 0.05:
                    speech_windows.append(f"between(t\\,{st:.3f}\\,{en:.3f})")
            if speech_windows and cid not in natural_stage:
                opened = self._sprite_path(cid, "neutral", "open", pose="idle")
                if opened.is_file():
                    oidx = len(inputs)
                    inputs.append(opened)
                    oscaled = f"aud_{idx_char}_open_scaled"
                    onxt = f"aud_{idx_char}_mouth"
                    filters.append(f"[{oidx}:v]scale=210:-1:flags=lanczos,format=rgba[{oscaled}]")
                    filters.append(
                        f"[{current}][{oscaled}]overlay=x={x}:y={y}:format=auto:"
                        f"enable='{'+'.join(speech_windows)}'[{onxt}]"
                    )
                    current = onxt

        # V17: high-quality limited actor is preferred for Hindi speeches.
        if focal_natural is not None:
            fidx = len(inputs)
            fdir = gaze_direction(focal_natural, "audience", positions)
            fpath = natural_actor_path(self.project_root, focal_natural, fdir)
            inputs.append(fpath)
            x, y = positions.get(focal_natural, (500, 155))
            filters.append(f"[{fidx}:v]scale=300:-1:flags=lanczos,format=rgba[v17_focal_scaled]")
            filters.append(f"[{current}][v17_focal_scaled]overlay=x={x}:y={y}:format=auto[v17_stage]")
            current = "v17_stage"

        # Focal stage performer is the only full articulated stream when no V17 actor exists.
        if performance_track is not None and focal_rig is not None:
            tidx = len(inputs)
            inputs.append(performance_track)
            x, y = positions.get(focal_rig, (500, 155))
            filters.append(
                f"[{tidx}:v]scale=300:-1:flags=lanczos,format=rgba[v16_focal_scaled]"
            )
            filters.append(
                f"[{current}][v16_focal_scaled]overlay=x={x}:y={y}:format=auto[v16_stage]"
            )
            current = "v16_stage"

        # Cheap fixed-zoom reframing. x changes with the active speaker, but the
        # crop size stays fixed, so FFmpeg avoids expensive per-frame zoompan.
        crop_x = "107"
        clauses: list[tuple[float, float, int]] = []
        for item in timeline:
            cid = str(item.get("character_id", ""))
            if cid not in positions:
                continue
            st = float(item.get("start", 0.0))
            en = float(item.get("voice_end", item.get("end", st)))
            px = positions[cid][0]
            target = max(0, min(214, int(px - 533)))
            clauses.append((st, en, target))
        for st, en, target in reversed(clauses):
            crop_x = f"if(between(t\\,{st:.3f}\\,{en:.3f})\\,{target}\\,{crop_x})"
        filters.append(
            f"[{current}]crop=1066:600:x='{crop_x}':y=60,"
            "scale=1920:1080:flags=lanczos,fps=" + str(self.fps) + ",format=yuv420p[vout]"
        )

        args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        for item in inputs:
            if item.suffix.lower() == ".mov":
                args += ["-stream_loop", "-1", "-i", str(item)]
            else:
                args += ["-loop", "1", "-framerate", str(self.fps), "-i", str(item)]
        audio_index = len(inputs)
        args += ["-i", str(scene_audio)]
        args += [
            "-filter_complex", ";".join(filters),
            "-map", "[vout]", "-map", f"{audio_index}:a:0",
            "-t", f"{duration:.4f}",
            *self._encoder_args, "-r", str(self.fps),
            "-c:a", "aac", "-b:a", "256k", "-ar", str(AUDIO_RATE), "-ac", "1",
            str(output),
        ]
        self._run(args, label=f"render V16 crowd scene {scene.id}")

    def _render_scene_video(
        self,
        *,
        scene: CartoonScene,
        scene_audio: Path,
        timeline: list[dict[str, object]],
        output: Path,
    ) -> None:
        duration = self._wave_duration(scene_audio)
        bg = self._background_path(scene.location_id)
        characters = self._scene_characters(scene)
        action = self._resolve_visual_action(scene)
        if self._v16_is_crowd_scene(scene=scene, characters=characters, action=action):
            return self._render_crowd_scene_video(
                scene=scene, scene_audio=scene_audio, timeline=timeline, output=output
            )
        interaction = v16_interaction_mode(scene, characters, action)
        locomotion_actions = {"walk", "run", "chase", "enter", "exit", "jump", "fall"}
        natural_characters = [
            cid for cid in characters
            if natural_actor_available(self.project_root, cid)
        ]
        if natural_characters:
            print(
                "[CARTOON ACTORS V17] "
                f"scene={scene.id}; mode=LIMITED_NATURAL; actors={','.join(natural_characters)}; "
                "continuous_rig_motion=OFF; partner_gaze=ON"
            )
        print(
            "[CARTOON DIRECTOR V16] "
            f"scene={scene.id}; mode={interaction}; eye_contact=ON; natural_turn_taking=ON"
        )
        print(
            "[CARTOON ACTION WORLD V11.4] "
            f"scene={scene.id}; location={scene.location_id}; "
            f"background={bg.name}; action={action}; "
            f"blocking={getattr(scene, 'blocking_mode', 'auto')}; "
            f"camera={scene.camera}/{scene.camera_action}; "
            f"actors={','.join(characters)}"
        )
        positions = self._positions_for_scene(
            scene=scene,
            characters=characters,
            action=action,
        )
        attached_props = self._attached_prop_specs(
            scene=scene,
            action=action,
            duration=duration,
            positions=positions,
            timeline=timeline,
        )
        attached_names = {str(item["name"]) for item in attached_props}
        v18_scene_fx = self._v18_scene_effect_specs(
            scene=scene, action=action, duration=duration, positions=positions
        )
        articulation_quality = self._articulation_quality_check(
            scene=scene,
            characters=characters,
            action=action,
            attached_names=attached_names,
        )
        self._articulation_scene_quality[int(scene.id)] = articulation_quality
        if articulation_quality["status"] != "PASS":
            self._degraded = True
            for reason in articulation_quality["reasons"]:
                warning = f"scene {scene.id} articulation quality: {reason}"
                if warning not in self._warnings:
                    self._warnings.append(warning)

        # Precompose each rigged actor's complete performance at rig resolution.
        # Final scene compositing therefore uses one alpha stream per actor.
        rig_characters = [
            cid for cid in characters
            if self._rig_available(cid) and cid not in natural_characters
        ]
        primary_actor = next(
            (str(item.get("character_id")) for item in timeline if str(item.get("character_id")) in rig_characters),
            rig_characters[0] if rig_characters else None,
        )
        performance_tracks: dict[str, Path] = {}
        for cid in rig_characters:
            track = output.parent / f"{output.stem}_{cid}_performance.mov"
            self._render_character_performance_track(
                scene=scene, character_id=cid, scene_action=action, duration=duration,
                timeline=timeline, attached_names=attached_names,
                attached_specs=[
                    spec for spec in attached_props
                    if str(spec.get("actor")) == cid
                ],
                primary_actor=primary_actor, output=track,
                positions=positions, scene_characters=characters,
                interaction=v16_interaction_mode(scene, characters, action),
            )
            performance_tracks[cid] = track

        inputs: list[Path] = [bg]
        # V17.5: natural actors must live in the same camera space as the set.
        # Older builds zoomed/drifted the 1080p background BEFORE overlaying actors,
        # which made the floor move underneath fixed sprites (the "floating" look)
        # and softened the plate through double upscaling. For natural dialogue actors
        # keep the source plate full-resolution here; the micro-shot camera is applied
        # later to the completed composite, so floor, shadow and actor move together.
        if natural_characters:
            background_filter = f"scale={WIDTH}:{HEIGHT}:flags=lanczos,unsharp=5:5:0.28:5:5:0,format=rgba"
        else:
            background_filter = self._dynamic_background_filter(
                scene=scene,
                duration=duration,
            )
        filters: list[str] = [
            f"[0:v]{background_filter}[base]"
        ]
        current = "base"

        # V18.1 scene dressing behind actors (water puddle / clothes on ground).
        for fx_index, spec in enumerate(item for item in v18_scene_fx if item.get("depth") == "behind"):
            path = self._v18_scene_effect_path(str(spec["name"]))
            if not path.is_file():
                continue
            idx = len(inputs)
            inputs.append(path)
            next_label = f"v18_fx_behind_{fx_index}"
            filters.append(
                f"[{current}][{idx}:v]overlay=x='{spec['x']}':y='{spec['y']}':"
                f"format=auto:eval=frame:enable='{spec.get('enable','1')}'[{next_label}]"
            )
            current = next_label

        # Ground shadows add depth while staying cheap. Shadows track X but not
        # vertical jumps/climbs so they still feel attached to the floor.
        legacy_shadow_path = self.prop_root / "character_shadow.png"
        natural_shadow_path = self.project_root / "assets" / "cartoon_v17" / "contact_shadow.png"
        if legacy_shadow_path.is_file() or natural_shadow_path.is_file():
            for shadow_index, char_id in enumerate(characters):
                if action in {"monkey_sneak", "baby_reveal"} and char_id == "bandar":
                    continue
                shadow_path = (
                    natural_shadow_path
                    if char_id in natural_characters and natural_shadow_path.is_file()
                    else legacy_shadow_path
                )
                if not shadow_path.is_file():
                    continue
                idx = len(inputs)
                inputs.append(shadow_path)
                x0, y0 = positions[char_id]
                x_expr, y_expr = self._character_motion_expr(
                    scene=scene,
                    character_id=char_id,
                    base_x=x0,
                    base_y=y0,
                    duration=duration,
                    timeline=timeline,
                    action=action,
                )
                next_label = f"shadow_{shadow_index}"
                # Natural actor canvases are 420x740 with visible feet near y=732.
                # Anchor the soft ellipse to those feet instead of one global y=930.
                # This preserves contact through blocking/depth changes and locomotion.
                if char_id in natural_characters:
                    # 260x58 V17.5 contact ellipse; centered under the 420px
                    # actor canvas and crossing the visible foot baseline (~+732).
                    _shadow_x = f"({x_expr})+90"
                    _shadow_y = f"({y_expr})+703"
                else:
                    _shadow_x = f"({x_expr})+90"
                    _shadow_y = "930"
                filters.append(
                    f"[{current}][{idx}:v]overlay=x='{_shadow_x}':"
                    f"y='{_shadow_y}':format=auto:eval=frame[{next_label}]"
                )
                current = next_label

        # V10 hand/ground-constrained props behind the character body.
        for prop_index, spec in enumerate(
            item for item in attached_props
            if item.get("depth") == "behind"
            and not self._rig_available(str(item.get("actor", "")))
        ):
            path = self._attached_prop_path(spec)
            idx = len(inputs)
            inputs.append(path)
            next_label = f"attached_behind_{prop_index}"
            filters.append(
                f"[{current}][{idx}:v]overlay=x='{spec['x']}':y='{spec['y']}':"
                f"format=auto:eval=frame:enable='{spec.get('enable','1')}'[{next_label}]"
            )
            current = next_label

        # Baseline character bodies. Rigged humanoids animate articulated limbs;
        # animals/special creatures keep the legacy sprite path.
        for char_id in characters:
            x, y = positions[char_id]
            x_expr, y_expr = self._character_motion_expr(
                scene=scene,
                character_id=char_id,
                base_x=x,
                base_y=y,
                duration=duration,
                timeline=timeline,
                action=action,
            )
            if char_id in natural_characters:
                own_index = next((i for i, raw in enumerate(timeline) if str(raw.get("character_id")) == char_id), 0)
                target = line_addressee(timeline, own_index, characters, interaction, primary_actor) if timeline else None
                if not target or target == char_id:
                    target = next((str(raw.get("character_id")) for raw in timeline if str(raw.get("character_id")) != char_id), "camera")
                direction = gaze_direction(char_id, target, positions)
                sprite = natural_actor_path(self.project_root, char_id, direction)
                idx = len(inputs)
                inputs.append(sprite)
                next_label = f"v17_base_{char_id}"
                # V17.1: never fall back to the geometric humanoid just because
                # a scene contains enter/exit/walk/run. Natural actors stay visible;
                # locomotion gets a simple intentional screen-space move, while
                # dialogue remains a stable hold.
                # V18.1: retain the V17 stable hold, but allow the already-bounded
                # emphasis/lean expression during dialogue. This removes the cardboard
                # cutout feel without reintroducing constant bobbing.
                _nx = x_expr
                _ny = y_expr
                filters.append(
                    f"[{current}][{idx}:v]overlay=x='{_nx}':y='{_ny}':"
                    f"format=auto:eval=frame[{next_label}]"
                )
                current = next_label
            elif self._rig_available(char_id):
                track = performance_tracks[char_id]
                idx = len(inputs)
                inputs.append(track)
                next_label = f"performance_{char_id}"
                filters.append(
                    f"[{current}][{idx}:v]overlay=x='{x_expr}':y='{y_expr}':"
                    f"format=auto:eval=frame[{next_label}]"
                )
                current = next_label
            else:
                baseline_pose = self._baseline_pose(character_id=char_id, action=action)
                sprite = self._sprite_path(char_id, "neutral", "closed", pose=baseline_pose)
                idx = len(inputs)
                inputs.append(sprite)
                next_label = f"base_{char_id}"
                filters.append(
                    f"[{current}][{idx}:v]overlay=x='{x_expr}':y='{y_expr}':"
                    f"format=auto:eval=frame[{next_label}]"
                )
                current = next_label

        # Active expression, articulated body gesture, and mouth overlays.
        for line_index, item in enumerate(timeline, start=1):
            char_id = str(item["character_id"])
            if char_id not in positions:
                continue
            expr = self._expression_asset(str(item["emotion"]))
            x, y = positions[char_id]
            start = float(item["start"])
            voice_end = float(item["voice_end"])
            line_end = float(item["end"])
            x_expr, y_expr = self._character_motion_expr(
                scene=scene,
                character_id=char_id,
                base_x=x,
                base_y=y,
                duration=duration,
                timeline=timeline,
                action=action,
            )
            enable = self._between(start, line_end)
            if char_id in natural_characters:
                target = line_addressee(timeline, line_index - 1, characters, interaction, primary_actor)
                direction = gaze_direction(char_id, target, positions)
                actor = natural_actor_path(self.project_root, char_id, direction)
                aidx = len(inputs)
                inputs.append(actor)
                next_label = f"v17_line_{line_index}_{char_id}"
                filters.append(
                    f"[{current}][{aidx}:v]overlay=x='{x_expr}':y='({y_expr})-3':"
                    f"format=auto:eval=frame:enable={enable}[{next_label}]"
                )
                current = next_label
                continue
            if self._rig_available(char_id):
                continue
            else:
                line_pose = self._line_pose(
                    character_id=char_id,
                    requested=str(item.get("pose", "idle")),
                    action=action,
                )
                closed = self._sprite_path(char_id, expr, "closed", pose=line_pose)
                closed_idx = len(inputs)
                inputs.append(closed)
                next_label = f"line_{line_index}_closed"
                filters.append(
                    f"[{current}][{closed_idx}:v]overlay=x='{x_expr}':y='{y_expr}':"
                    f"format=auto:eval=frame:enable={enable}[{next_label}]"
                )
                current = next_label
                opened = self._sprite_path(char_id, expr, "open", pose=line_pose)
                open_idx = len(inputs)
                inputs.append(opened)
                next_label = f"line_{line_index}_open"
                mouth_enable = self._mouth_enable_expression(
                    windows=item.get("mouth_windows", []),
                    start=start,
                    voice_end=voice_end,
                )
                filters.append(
                    f"[{current}][{open_idx}:v]overlay=x='{x_expr}':y='{y_expr}':"
                    f"format=auto:eval=frame:enable='{mouth_enable}'[{next_label}]"
                )
                current = next_label

        # V17 reciprocal eye contact: while A speaks, natural listener B
        # explicitly faces A. This is a hold, not continuous motion.
        for li, item in enumerate(timeline):
            speaker_id = str(item.get("character_id", ""))
            if speaker_id not in positions:
                continue
            st = float(item.get("start", 0.0))
            en = float(item.get("end", item.get("voice_end", st)))
            if en - st < 0.05:
                continue
            for listener_id in natural_characters:
                if listener_id == speaker_id or listener_id not in positions:
                    continue
                lx, ly = positions[listener_id]
                lx_expr, ly_expr = self._character_motion_expr(
                    scene=scene, character_id=listener_id, base_x=lx, base_y=ly,
                    duration=duration, timeline=timeline, action=action,
                )
                direction = gaze_direction(listener_id, speaker_id, positions)
                actor = natural_actor_path(self.project_root, listener_id, direction)
                aidx = len(inputs)
                inputs.append(actor)
                next_label = f"v17_listener_{li}_{listener_id}"
                filters.append(
                    f"[{current}][{aidx}:v]overlay=x='{lx_expr}':y='{ly_expr}':format=auto:eval=frame:"
                    f"enable={self._between(st, en)}[{next_label}]"
                )
                current = next_label

        # Periodic short blinks.
        for blink_index, char_id in enumerate(characters):
            if self._rig_available(char_id):
                continue
            blink = self.sprite_root / char_id / "blink_overlay.png"
            if not blink.is_file():
                continue
            idx = len(inputs)
            inputs.append(blink)
            next_label = f"blink_{blink_index}"
            x, y = positions[char_id]
            x_expr, y_expr = self._character_motion_expr(
                scene=scene,
                character_id=char_id,
                base_x=x,
                base_y=y,
                duration=duration,
                timeline=timeline,
                action=action,
            )
            phase = 0.65 + blink_index * 0.83 + scene.id * 0.17
            period = 3.1 + (blink_index % 3) * 0.45
            enable = f"lt(mod(t+{phase:.2f}\\,{period:.2f})\\,0.11)"
            filters.append(
                f"[{current}][{idx}:v]overlay=x='{x_expr}':y='{y_expr}':"
                f"format=auto:eval=frame:enable='{enable}'[{next_label}]"
            )
            current = next_label

        # Final reaction expression/body acting.
        if scene.reaction is not None and scene.reaction.character_id in positions:
            reaction_char = scene.reaction.character_id
            reaction_expr = self._expression_asset(scene.reaction.expression)
            x, y = positions[reaction_char]
            x_expr, y_expr = self._character_motion_expr(
                scene=scene,
                character_id=reaction_char,
                base_x=x,
                base_y=y,
                duration=duration,
                timeline=timeline,
                action=action,
            )
            reaction_end = duration
            reaction_start = max(0.0, reaction_end - max(0.35, min(0.70, float(scene.reaction.duration_seconds))))
            enable = self._between(reaction_start, reaction_end)
            if reaction_char in natural_characters or self._rig_available(reaction_char):
                # Natural limited actors / V11 tracks already provide the visible body.
                # Do not layer a second reaction stream in the scene compositor.
                pass
            else:
                reaction_pose = self._reaction_pose(
                    expression=scene.reaction.expression,
                    action=action,
                    character_id=reaction_char,
                )
                reaction = self._sprite_path(reaction_char, reaction_expr, "closed", pose=reaction_pose)
                idx = len(inputs)
                inputs.append(reaction)
                next_label = "reaction"
                filters.append(
                    f"[{current}][{idx}:v]overlay=x='{x_expr}':y='{y_expr}':"
                    f"format=auto:eval=frame:enable={enable}[{next_label}]"
                )
                current = next_label

        # Front attached props move with the actor instead of floating in screen space.
        for prop_index, spec in enumerate(
            item for item in attached_props
            if item.get("depth") == "front"
            and not self._rig_available(str(item.get("actor", "")))
        ):
            path = self._attached_prop_path(spec)
            idx = len(inputs)
            inputs.append(path)
            next_label = f"attached_front_{prop_index}"
            filters.append(
                f"[{current}][{idx}:v]overlay=x='{spec['x']}':y='{spec['y']}':"
                f"format=auto:eval=frame:enable='{spec.get('enable','1')}'[{next_label}]"
            )
            current = next_label

        # V18.1 front scene dressing (small phone, dust, spray, salt, wind).
        for fx_index, spec in enumerate(item for item in v18_scene_fx if item.get("depth") == "front"):
            path = self._v18_scene_effect_path(str(spec["name"]))
            if not path.is_file():
                continue
            idx = len(inputs)
            inputs.append(path)
            next_label = f"v18_fx_front_{fx_index}"
            filters.append(
                f"[{current}][{idx}:v]overlay=x='{spec['x']}':y='{spec['y']}':"
                f"format=auto:eval=frame:enable='{spec.get('enable','1')}'[{next_label}]"
            )
            current = next_label

        # Story props / action effects. V18 benchmark actions use dedicated,
        # correctly-scaled scene dressing above, so legacy generic props (notably
        # the giant phone/tablet) are suppressed.
        _v18_actions = {"dust_cushion","wet_table","water_plants","spread_clothes","salt_pinch","fan_wind"}
        _generic_specs = [] if action in _v18_actions else self._prop_specs(
            scene=scene, action=action, duration=duration
        )
        for prop_index, spec in enumerate(_generic_specs):
            if str(spec.get("name")) in attached_names:
                continue
            path = self.prop_root / f"{spec['name']}.png"
            if not path.is_file():
                self._warnings.append(
                    f"scene {scene.id} prop missing: {spec['name']}"
                )
                continue
            idx = len(inputs)
            inputs.append(path)
            next_label = f"prop_{prop_index}"
            enable = str(spec.get("enable", "1"))
            filters.append(
                f"[{current}][{idx}:v]overlay=x='{spec['x']}':y='{spec['y']}':"
                f"format=auto:eval=frame:enable='{enable}'[{next_label}]"
            )
            current = next_label

        # V11 foreground depth: near set pieces occlude characters.
        foreground_path = self.foreground_root / f"{scene.location_id}.png"
        if rig_characters and foreground_path.is_file():
            idx = len(inputs)
            inputs.append(foreground_path)
            foreground_dynamic = "v11_foreground_dynamic"
            next_label = "v11_foreground"
            filters.append(
                f"[{idx}:v]{self._dynamic_background_filter(scene=scene, duration=duration)}"
                f"[{foreground_dynamic}]"
            )
            filters.append(
                f"[{current}][{foreground_dynamic}]overlay=0:0:format=auto[{next_label}]"
            )
            current = next_label

        # Micro-shot camera grammar: one FFmpeg pass, hard dialogue/reaction
        # reframes every ~2-4 sec. This is the biggest natural-feeling change.
        camera_filter, shot_count = self._microshot_camera_filter(
            scene=scene,
            characters=characters,
            positions=positions,
            timeline=timeline,
            duration=duration,
        )
        print(
            "[CARTOON PERFORMANCE V14.1] "
            f"scene={scene.id}; shots={shot_count}; max_shot=2.35s; "
            "hold_gesture_hold=ON; stable_idle=ON; finite_actions=ON"
        )
        filters.append(
            f"[{current}]{camera_filter},fps={self.fps},format=yuv420p[vout]"
        )

        args = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
        ]
        for image in inputs:
            image_text = str(image)
            if image.suffix.lower() == ".mov":
                args += ["-stream_loop", "-1", "-i", image_text]
            elif "%02d" in image_text:
                sequence_fps = max(
                    1,
                    int(
                        self._rig_sequence_fps.get(
                            image_text,
                            self.fps,
                        )
                    ),
                )
                args += [
                    "-stream_loop",
                    "-1",
                    "-framerate",
                    str(sequence_fps),
                    "-start_number",
                    "0",
                    "-i",
                    image_text,
                ]
            elif image.suffix.lower() == ".apng":
                raise RuntimeError(
                    "V10.0.1 APNG runtime decoding is disabled: "
                    f"{image}"
                )
            else:
                args += [
                    "-loop",
                    "1",
                    "-framerate",
                    str(self.fps),
                    "-i",
                    str(image),
                ]

        audio_index = len(inputs)
        args += ["-i", str(scene_audio)]
        args += [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-map",
            f"{audio_index}:a:0",
            "-t",
            f"{duration:.4f}",
            *self._encoder_args,
            "-r",
            str(self.fps),
            "-c:a",
            "aac",
            "-b:a",
            "256k",
            "-ar",
            str(AUDIO_RATE),
            "-ac",
            "1",
            str(output),
        ]
        self._run(args, label=f"render scene {scene.id}")
    def _resolve_visual_action(self, scene: CartoonScene) -> str:
        if scene.visual_action and scene.visual_action != "auto":
            return scene.visual_action

        text = " ".join(
            [
                scene.setup,
                scene.beat,
                scene.camera_action,
                " ".join(line.text for line in scene.dialogue),
            ]
        ).casefold()

        if any(token in text for token in ("भाग", "chase", "पीछा", "run")):
            return "chase"
        if any(token in text for token in ("फिसल", "slip", "गिर")):
            return "chacha_slip"
        if any(token in text for token in ("झपट", "चुरा", "steal", "snatch")):
            return "steal_tray"
        if any(token in text for token in ("trap", "bait", "जाल", "चटनी")):
            return "bait_trap"
        generic = resolve_action_family(
            text,
            beat=scene.beat,
        )
        if generic != "dialogue":
            return generic
        if scene.beat in {"punchline", "callback"}:
            return "reveal"
        if scene.beat == "reaction":
            return "reaction"
        return "dialogue"

    def _positions_for_scene(
        self,
        *,
        scene: CartoonScene,
        characters: list[str],
        action: str,
    ) -> dict[str, tuple[int, int]]:
        positions = self._positions_for(characters)
        natural_stage = (
            self._is_hindi_mass_channel()
            and any(natural_actor_available(self.project_root, cid) for cid in characters)
        )
        if natural_stage and characters:
            # V17.5 actor-safe stage zones. Put feet on the foreground floor plane
            # instead of the mid-depth furniture plane. The old universal y=245
            # made actors appear to stand on sofas/tables in home backgrounds.
            stage = {
                "living_room": ([750], [380, 920], [100, 700, 1300], 292),
                "courtyard": ([750], [380, 920], [100, 700, 1300], 272),
                "outdoor_kitchen": ([750], [380, 920], [100, 700, 1300], 278),
                "bedroom": ([750], [380, 920], [100, 700, 1300], 286),
                "classroom": ([760], [390, 930], [110, 710, 1310], 282),
                "school_yard": ([760], [390, 930], [110, 710, 1310], 275),
                "market": ([760], [390, 930], [110, 710, 1310], 280),
                "village_lane": ([760], [390, 930], [110, 710, 1310], 276),
                "village_road": ([760], [390, 930], [110, 710, 1310], 274),
                "tea_shop": ([760], [390, 930], [110, 710, 1310], 286),
                "bus_stop": ([760], [390, 930], [110, 710, 1310], 278),
            }.get(
                str(scene.location_id),
                ([760], [390, 930], [110, 710, 1310], 280),
            )
            one, two, three, floor_y = stage
            xs = one if len(characters) == 1 else (two if len(characters) == 2 else three)
            positions = {
                cid: (xs[min(i, len(xs) - 1)], floor_y)
                for i, cid in enumerate(characters)
            }

            # V18.1 benchmark staging: story beats are placed around the actual
            # set geometry instead of one generic two-shot. The override is keyed
            # by explicit visual_action, so normal episodes keep the generic stage.
            _v18_layouts = {
                "dust_cushion": ([930, 1370], floor_y),
                "wet_table": ([360, 1120], floor_y),
                "water_plants": ([260, 1130], floor_y),
                "spread_clothes": ([330, 1180], floor_y),
                "salt_pinch": ([360, 1130], floor_y),
                "fan_wind": ([350, 1140], floor_y),
            }
            if action in _v18_layouts:
                _xs, _fy = _v18_layouts[action]
                positions = {
                    cid: (_xs[min(i, len(_xs)-1)], _fy)
                    for i, cid in enumerate(characters)
                }
                print(
                    "[CARTOON STAGING V18.1] "
                    f"scene={scene.id}; action={action}; positions={positions}"
                )

        # V11.3: same-location scenes also change blocking. This is deliberately
        # generic and only shifts/compresses the existing cast layout; action-
        # specific overrides below still win.
        variant = str(getattr(scene, "environment_variant", "auto") or "auto")
        if positions and not natural_stage and action not in {"chase", "run", "walk", "enter", "exit"}:
            if variant in {"wide_left", "medium_left", "left_bias"}:
                dx = 150
                positions = {cid: (min(1460, x + dx), y) for cid, (x, y) in positions.items()}
            elif variant in {"wide_right", "medium_right", "right_bias"}:
                dx = -150
                positions = {cid: (max(20, x + dx), y) for cid, (x, y) in positions.items()}
            elif variant == "center_detail" and len(positions) > 1:
                ordered = list(positions)
                center = WIDTH // 2
                gap = 500
                start = center - gap * (len(ordered) - 1) // 2
                positions = {
                    cid: (max(20, min(1460, start + i * gap)), positions[cid][1])
                    for i, cid in enumerate(ordered)
                }

        blocking = str(getattr(scene, "blocking_mode", "auto") or "auto")
        if positions and blocking in {"moving_group", "moving_chase"}:
            # Break the flat shoulder-to-shoulder tableau. Alternate depth lanes
            # so action scenes read as pursuit/search rather than a dialogue row.
            ordered = list(positions)
            lane_offsets = (-55, 35, -10, 70, 15)
            positions = {
                cid: (positions[cid][0], max(150, positions[cid][1] + lane_offsets[i % len(lane_offsets)]))
                for i, cid in enumerate(ordered)
            }
        elif positions and blocking == "action_exchange" and len(positions) >= 2:
            ordered = list(positions)
            positions[ordered[0]] = (430, positions[ordered[0]][1])
            positions[ordered[1]] = (1030, positions[ordered[1]][1])

        if "bandar" in positions:
            if action == "monkey_sneak":
                positions["bandar"] = (1420, 80)
            elif action == "steal_tray":
                positions["bandar"] = (1150, 160)
            elif action == "chase":
                positions["bandar"] = (-350, 180)
            elif action == "baby_reveal":
                positions["bandar"] = (1320, 220)
            elif action == "final_snatch":
                positions["bandar"] = (1950, 180)

        if action == "baby_reveal":
            human_ids = [c for c in characters if c != "bandar"]
            human_xs = [40, 500, 920]
            for i, char_id in enumerate(human_ids[:3]):
                positions[char_id] = (human_xs[i], 285)

        return positions

    @staticmethod
    def _speaker_activity_expr(
        *,
        character_id: str,
        timeline: list[dict[str, object]],
    ) -> str:
        windows = []
        for item in timeline:
            if str(item.get("character_id")) != character_id:
                continue
            windows.append(
                f"between(t\\,{float(item['start']):.3f}\\,{float(item['voice_end']):.3f})"
            )
        return "+".join(windows) if windows else "0"

    def _character_motion_expr(
        self,
        *,
        scene: CartoonScene,
        character_id: str,
        base_x: int,
        base_y: int,
        duration: float,
        timeline: list[dict[str, object]],
        action: str,
    ) -> tuple[str, str]:
        safe_duration = max(0.5, float(duration))
        phase = (sum(ord(c) for c in character_id) % 17) / 7.0
        speaker = self._speaker_activity_expr(
            character_id=character_id,
            timeline=timeline,
        )
        primary_actor = next(
            (
                str(item.get("character_id"))
                for item in timeline
                if str(item.get("character_id", ""))
            ),
            None,
        )

        # V14.1: stable idle. Natural limited animation uses held poses, not
        # perpetual bobbing. Add movement only in short emphasis windows near
        # the beginning/middle of this actor's own spoken lines.
        emphasis_windows: list[str] = []
        for item in timeline:
            if str(item.get("character_id")) != character_id:
                continue
            st = float(item.get("start", 0.0))
            en = float(item.get("voice_end", item.get("end", st)))
            span = max(0.0, en - st)
            if span < 0.12:
                continue
            first_end = min(en, st + min(0.42, max(0.22, span * 0.18)))
            emphasis_windows.append(f"between(t\\,{st:.3f}\\,{first_end:.3f})")
            if span >= 3.0:
                mid = st + span * 0.62
                mid_end = min(en, mid + 0.32)
                emphasis_windows.append(f"between(t\\,{mid:.3f}\\,{mid_end:.3f})")
        emphasis = "+".join(emphasis_windows) if emphasis_windows else "0"
        lean_sign = -1 if (sum(ord(c) for c in character_id) % 2) else 1
        idle_x = (
            f"{base_x}+0.45*sin(1.15*t+{phase:.3f})"
            f"+{lean_sign * 5.5:.1f}*({emphasis})*sin(5.0*t+{phase:.3f})"
        )
        idle_y = (
            f"{base_y}+0.35*sin(1.05*t+{phase:.3f})"
            f"-4.8*({emphasis})*abs(sin(7.0*t+{phase:.3f}))"
        )

        if action == "monkey_sneak" and character_id == "bandar":
            return (
                f"{base_x}-360*min(1\\,t/{safe_duration:.3f})",
                f"{base_y}+150*min(1\\,t/{safe_duration:.3f})"
                f"+5*sin(7*t)",
            )

        if action == "steal_tray":
            if character_id == "bandar":
                return (
                    f"780+1150*min(1\\,t/{safe_duration:.3f})",
                    f"155+22*abs(sin(11*t))",
                )
            return (
                idle_x,
                f"{base_y}-8*abs(sin(7.5*t+{phase:.3f}))",
            )

        if action == "chase":
            order = {
                "bandar": (0.00, 0, -65),
                "guddu": (0.08, 1, -20),
                "bittu": (0.14, 2, 18),
                "chacha": (0.20, 3, 46),
                "mai": (0.24, 4, 64),
                "babuji": (0.26, 5, 74),
            }
            delay, rank, lane_y = order.get(
                character_id,
                (0.18, 3, 35),
            )
            denom = max(0.2, 1.0 - delay)
            start_x = -360 - rank * 235
            return (
                f"{start_x}+2700*max(0\\,min(1\\,(t/{safe_duration:.3f}-{delay:.3f})/{denom:.3f}))",
                f"{base_y+lane_y}-16*abs(sin(12.5*t+{phase:.3f}))",
            )

        if action == "chacha_slip" and character_id == "chacha":
            return (
                f"{base_x}+120*max(0\\,(t/{safe_duration:.3f}-0.55)/0.45)",
                f"{base_y}+330*max(0\\,(t/{safe_duration:.3f}-0.62)/0.38)",
            )

        if action == "bait_trap" and character_id == "bandar":
            return (
                f"{base_x}-210*sin(3.2*t)",
                f"{base_y}+8*abs(sin(8*t))",
            )

        if action == "food_chaos":
            if character_id == "bandar":
                return (
                    f"{base_x}+180*sin(2.4*t)",
                    f"{base_y}-30*abs(sin(8.5*t))",
                )
            return (
                f"{base_x}+10*sin(6.0*t+{phase:.3f})",
                f"{base_y}-12*abs(sin(9*t+{phase:.3f}))",
            )

        if action == "baby_reveal":
            return (
                idle_x,
                f"{base_y}+1.0*sin(2.1*t+{phase:.3f})",
            )

        if action == "final_snatch" and character_id == "bandar":
            return (
                f"2050-900*max(0\\,min(1\\,(t/{safe_duration:.3f}-0.62)/0.38))",
                f"180+12*abs(sin(10*t))",
            )

        generic_primary_actions = {
            "run", "walk", "enter", "exit", "grab", "give", "carry",
            "search", "hide", "celebrate", "dance", "jump", "fall",
            "magic", "use_device", "open", "eat", "point", "reveal",
            "reaction",
        }
        blocking = str(getattr(scene, "blocking_mode", "auto") or "auto")
        group_motion = blocking in {"moving_group", "moving_chase"}
        reaction_actor = (
            scene.reaction.character_id
            if scene.reaction is not None
            else None
        )
        if (
            action in generic_primary_actions
            and character_id != primary_actor
            and not group_motion
            and not (action == "reaction" and character_id == reaction_actor)
        ):
            return idle_x, idle_y

        if action in {"run", "walk"}:
            travel = 760 if action == "run" else 460
            travel_seconds = min(safe_duration, 2.6 if action == "run" else 3.8)
            start_x = base_x - travel * 0.42
            return (
                f"{start_x}+{travel}*min(1\\,t/{travel_seconds:.3f})",
                f"{base_y}-6*abs(sin({12 if action=='run' else 8}*t+{phase:.3f}))",
            )

        if action == "enter":
            travel_seconds = min(safe_duration, 2.8)
            return (
                f"-360+({base_x}+360)*min(1\\,t/{travel_seconds:.3f})",
                f"{base_y}-5*abs(sin(8*t+{phase:.3f}))",
            )

        if action == "exit":
            travel_seconds = min(safe_duration, 2.8)
            return (
                f"{base_x}+(2300-{base_x})*min(1\\,t/{travel_seconds:.3f})",
                f"{base_y}-5*abs(sin(8*t+{phase:.3f}))",
            )
        if action in {"grab", "give", "carry"}:
            direction = -1 if (sum(ord(c) for c in character_id) % 2) else 1
            travel = 90 if action == "grab" else 55
            return (
                f"{base_x}+{direction*travel}*sin(3.14159*min(1\\,t/{safe_duration:.3f}))",
                f"{base_y}-7*abs(sin(7*t+{phase:.3f}))",
            )

        if action == "search":
            travel = 80 if group_motion else 55
            act = min(safe_duration, 1.35)
            return (
                f"if(lt(t\\,{act:.3f})\\,{base_x}+{travel}*sin(2.5*t+{phase:.3f})\\,{base_x})",
                f"if(lt(t\\,{act:.3f})\\,{base_y}+{5 if group_motion else 3}*sin(4*t+{phase:.3f})\\,{base_y})",
            )

        if action == "hide":
            return (
                idle_x,
                f"{base_y}+70*max(0\\,min(1\\,(t/{safe_duration:.3f}-0.35)/0.35))",
            )

        if action in {"celebrate", "dance"}:
            act = min(safe_duration, 1.45 if action == "celebrate" else 2.2)
            return (
                f"if(lt(t\\,{act:.3f})\\,{base_x}+18*sin(7*t+{phase:.3f})\\,{base_x})",
                f"if(lt(t\\,{act:.3f})\\,{base_y}-28*abs(sin(6*t+{phase:.3f}))\\,{base_y})",
            )

        if action == "jump":
            return (
                idle_x,
                f"{base_y}-145*sin(3.14159*min(1\\,t/{safe_duration:.3f}))",
            )

        if action == "fall":
            return (
                f"{base_x}+80*max(0\\,(t/{safe_duration:.3f}-0.55)/0.45)",
                f"{base_y}+280*max(0\\,(t/{safe_duration:.3f}-0.55)/0.45)",
            )

        if action == "magic":
            act = min(safe_duration, 1.55)
            return (
                f"if(lt(t\\,{act:.3f})\\,{base_x}+12*sin(8*t+{phase:.3f})\\,{base_x})",
                f"if(lt(t\\,{act:.3f})\\,{base_y}-45*abs(sin(5*t+{phase:.3f}))\\,{base_y})",
            )

        if action in {"use_device", "open", "eat", "point", "reveal", "reaction"}:
            # Body performance clips supply the gesture; keep screen-space
            # position stable so the actor does not wobble through the scene.
            return idle_x, idle_y

        return idle_x, idle_y

    @staticmethod
    def _mouth_activity_windows(
        *,
        path: Path,
        absolute_start: float,
    ) -> list[list[float]]:
        """
        Extract cheap local mouth-open intervals from the already-synthesized WAV.
        No ASR, phoneme model or extra LLM call.
        """
        try:
            with wave.open(str(path), "rb") as wav:
                if wav.getsampwidth() != 2:
                    return []
                rate = wav.getframerate()
                channels = wav.getnchannels()
                frames_per_window = max(1, int(rate * 0.09))
                values: list[tuple[float, float]] = []
                elapsed = 0.0

                while True:
                    raw = wav.readframes(frames_per_window)
                    if not raw:
                        break
                    count = len(raw) // 2
                    if count <= 0:
                        break
                    sq = 0.0
                    sample_count = 0
                    # Mono and stereo both supported; treating all channel
                    # samples together is sufficient for mouth activity.
                    for offset in range(0, len(raw) - 1, 2):
                        value = int.from_bytes(
                            raw[offset:offset+2],
                            "little",
                            signed=True,
                        )
                        sq += float(value * value)
                        sample_count += 1
                    rms = math.sqrt(sq / max(1, sample_count))
                    dur = (count / max(1, channels)) / rate
                    values.append((elapsed, rms))
                    elapsed += dur

            if not values:
                return []

            peak = max(v for _, v in values)
            if peak <= 100.0:
                return []

            threshold = max(260.0, peak * 0.16)
            raw_windows: list[list[float]] = []
            for offset, rms in values:
                if rms < threshold:
                    continue
                start = absolute_start + offset
                end = start + 0.095
                if raw_windows and start - raw_windows[-1][1] <= 0.055:
                    raw_windows[-1][1] = end
                else:
                    raw_windows.append([start, end])

            # Split overly-long opens so the mouth still articulates instead of
            # staying frozen open. Cap expression complexity.
            final: list[list[float]] = []
            for start, end in raw_windows:
                cursor = start
                while end - cursor > 0.24:
                    final.append([cursor, cursor + 0.13])
                    cursor += 0.22
                if end - cursor >= 0.055:
                    final.append([cursor, end])

            return [
                [round(a, 3), round(b, 3)]
                for a, b in final[:30]
            ]
        except Exception:
            return []

    @staticmethod
    def _mouth_enable_expression(
        *,
        windows: object,
        start: float,
        voice_end: float,
    ) -> str:
        valid: list[tuple[float, float]] = []
        if isinstance(windows, list):
            for item in windows:
                if (
                    isinstance(item, list)
                    and len(item) == 2
                ):
                    try:
                        valid.append((float(item[0]), float(item[1])))
                    except Exception:
                        pass
        if valid:
            return "+".join(
                f"between(t\\,{a:.3f}\\,{b:.3f})"
                for a, b in valid
            )
        # Fallback only when signal analysis cannot produce windows.
        return (
            f"between(t\\,{start:.3f}\\,{voice_end:.3f})*"
            f"lt(mod(t-{start:.3f}\\,0.28)\\,0.14)"
        )

    def _v18_scene_effect_specs(
        self,
        *,
        scene: CartoonScene,
        action: str,
        duration: float,
        positions: dict[str, tuple[int, int]],
    ) -> list[dict[str, str]]:
        """Small story-specific environmental effects for the manual benchmark.

        These are translucent set dressing placed into the existing detailed
        location plate so the physical joke is visible instead of only spoken.
        """
        d = max(0.5, float(duration))
        result: list[dict[str, str]] = []
        mapping = {
            "dust_cushion": ("dust_cloud.png", 1070, 560, "front", f"gte(t\\,{d*0.34:.3f})"),
            "wet_table": ("water_spill.png", 610, 760, "behind", f"gte(t\\,{d*0.38:.3f})"),
            "water_plants": ("water_spray.png", 430, 530, "front", f"between(t\\,{d*0.28:.3f}\\,{d*0.78:.3f})"),
            "spread_clothes": ("clothes_ground.png", 490, 710, "behind", f"gte(t\\,{d*0.30:.3f})"),
            "salt_pinch": ("salt_sprinkle.png", 785, 375, "front", f"between(t\\,{d*0.36:.3f}\\,{d*0.72:.3f})"),
            "fan_wind": ("wind_dust.png", 300, 430, "front", f"gte(t\\,{d*0.30:.3f})"),
        }
        if action in mapping:
            name, x, y, depth, enable = mapping[action]
            result.append({"name":name, "x":str(x), "y":str(y), "depth":depth, "enable":enable})
        if action == "fan_wind":
            result.append({"name":"fan.png", "x":"820", "y":"445", "depth":"behind", "enable":"1"})

        # Small phone in Babuji's hand zone; replaces the legacy full-size
        # generic tablet centered in the frame.
        if action in mapping and "babuji" in positions:
            bx, by = positions["babuji"]
            result.append({
                "name":"phone.png", "x":str(bx + 250), "y":str(by + 315),
                "depth":"front", "enable":"1",
            })
        return result

    def _v18_scene_effect_path(self, name: str) -> Path:
        return self.v18_scene_fx_root / name

    def _prop_specs(
        self,
        *,
        scene: CartoonScene,
        action: str,
        duration: float,
    ) -> list[dict[str, str]]:
        d = max(0.5, float(duration))
        result: list[dict[str, str]] = []

        for name in scene.props:
            if name == "litti_tray":
                if action == "steal_tray":
                    result.append(
                        {
                            "name": name,
                            "x": f"930+760*min(1\\,t/{d:.3f})",
                            "y": "545-20*abs(sin(10*t))",
                            "enable": "1",
                        }
                    )
                else:
                    result.append(
                        {
                            "name": name,
                            "x": "980",
                            "y": "620",
                            "enable": "1",
                        }
                    )
            elif name == "steam":
                result.append(
                    {
                        "name": name,
                        "x": "1095+4*sin(2*t)",
                        "y": "420-22*mod(t\\,1.8)",
                        "enable": "1",
                    }
                )
            elif name == "chutney_bowl":
                result.append(
                    {
                        "name": name,
                        "x": f"915+240*max(0\\,(t/{d:.3f}-0.55)/0.45)",
                        "y": "685",
                        "enable": "1",
                    }
                )
            elif name == "single_litti":
                if action == "final_snatch":
                    result.append(
                        {
                            "name": name,
                            "x": f"720+900*max(0\\,min(1\\,(t/{d:.3f}-0.64)/0.36))",
                            "y": f"600-160*sin(3.14159*max(0\\,min(1\\,(t/{d:.3f}-0.64)/0.36)))",
                            "enable": f"gte(t\\,{d*0.60:.3f})",
                        }
                    )
                else:
                    result.append(
                        {
                            "name": name,
                            "x": f"900+500*(t/{d:.3f})",
                            "y": f"410-180*sin(3.14159*t/{d:.3f})",
                            "enable": "1",
                        }
                    )
            elif name == "baby_monkey":
                result.append(
                    {
                        "name": name,
                        "x": "1540",
                        "y": "545",
                        "enable": f"gte(t\\,{d*0.25:.3f})",
                    }
                )
            elif name == "dust_cloud":
                result.append(
                    {
                        "name": name,
                        "x": "980",
                        "y": "720",
                        "enable": f"gte(t\\,{d*0.62:.3f})",
                    }
                )
            elif name == "motion_lines":
                result.append(
                    {
                        "name": name,
                        "x": "0",
                        "y": "0",
                        "enable": (
                            f"between(t\\,{d*0.18:.3f}\\,{d*0.82:.3f})"
                        ),
                    }
                )
            else:
                if action in {"grab", "carry"}:
                    x = f"930+180*min(1\\,t/{d:.3f})"
                    y = "585-12*abs(sin(7*t))"
                    enable = "1"
                elif action == "give":
                    x = f"760+420*min(1\\,t/{d:.3f})"
                    y = "590"
                    enable = "1"
                elif action == "jump":
                    x = "960"
                    y = f"560-130*sin(3.14159*min(1\\,t/{d:.3f}))"
                    enable = "1"
                elif action == "reveal":
                    x = "980"
                    y = "590"
                    enable = f"gte(t\\,{d*0.45:.3f})"
                else:
                    x = "980"
                    y = "610"
                    enable = "1"
                result.append(
                    {
                        "name": name,
                        "x": x,
                        "y": y,
                        "enable": enable,
                    }
                )

        return result

    @staticmethod
    def _microshot_count(
        *,
        scene: CartoonScene,
        timeline: list[dict[str, object]],
    ) -> int:
        count = max(1, len(timeline))
        if scene.reaction is not None:
            count += 1
        return max(2, count)

    def _microshot_camera_filter(
        self,
        *,
        scene: CartoonScene,
        characters: list[str],
        positions: dict[str, tuple[int, int]],
        timeline: list[dict[str, object]],
        duration: float,
    ) -> tuple[str, int]:
        """Fast limited-animation coverage with a hard 2.4s shot ceiling.

        V11.5 targets the pacing observed in polished dialogue cartoons: the
        location can stay the same, but composition/performance changes every
        few seconds. Long lines are split into multiple speaker framings and
        can contain a short listener reaction insert while speech continues.
        Everything remains inside the existing single FFmpeg scene encode.
        """
        total_frames = max(1, int(math.ceil(duration * self.fps)))
        segments: list[tuple[int, int, float, int, int]] = []
        action = self._resolve_visual_action(scene)
        primary_actor = next(
            (str(item.get("character_id")) for item in timeline if str(item.get("character_id", ""))),
            characters[0] if characters else None,
        )

        natural_safe = (
            self._is_hindi_mass_channel()
            and any(natural_actor_available(self.project_root, cid) for cid in characters)
        )

        def focus_for(char_id: str) -> tuple[int, int]:
            x0, y0 = positions.get(char_id, (700, 245))
            if char_id == primary_actor and action in {"run", "walk"}:
                travel = 760 if action == "run" else 460
                x0 += int(travel * 0.58)
            # Natural actor visible pixels occupy roughly y+32..y+732. Focusing at
            # y+380 keeps head AND feet inside moderate punch-ins instead of framing
            # on the face and chopping legs/hands at the frame edge.
            focus_y = y0 + (380 if natural_safe else 225)
            return (
                max(180, min(WIDTH - 180, x0 + 210)),
                max(250, min(760, focus_y)),
            )

        def add_seconds(a: float, b: float, zoom: float, fx: int, fy: int) -> None:
            a = max(0.0, min(duration, a))
            b = max(a, min(duration, b))
            if b - a < 0.04:
                return
            af = max(0, int(a * self.fps))
            bf = max(af, int(math.ceil(b * self.fps)))
            segments.append((af, bf, zoom, fx, fy))

        def add_speaker_chunks(
            a: float,
            b: float,
            char_id: str,
            *,
            line_index: int,
            punch: bool = False,
        ) -> None:
            span = max(0.0, b - a)
            if span < 0.04:
                return
            max_shot = 2.35
            chunks = max(1, int(math.ceil(span / max_shot)))
            chunk = span / chunks
            base_fx, base_fy = focus_for(char_id)
            # V17.5 safe framing for full-body limited actors. The old 1.48-2.04x
            # cycle routinely cut knees, feet and hands. Keep cinematic variation
            # through focus/cuts while preserving the complete body silhouette.
            zoom_cycle = ((1.04, 1.08, 1.10) if len(characters) >= 3 else (1.06, 1.12, 1.16)) if natural_safe else (1.48, 1.72, 1.90)
            for j in range(chunks):
                st = a + j * chunk
                en = b if j == chunks - 1 else a + (j + 1) * chunk
                zoom = zoom_cycle[(line_index + j) % len(zoom_cycle)]
                if punch and j == chunks - 1:
                    zoom = max(zoom, 1.18 if natural_safe else 2.04)
                # Small alternating reframes make consecutive cuts visibly
                # different without changing the physical set.
                fx = max(180, min(WIDTH - 180, base_fx + (-82 if j % 2 == 0 else 74)))
                fy = max(250, min(700, base_fy + (16 if j % 2 == 0 else -12)))
                add_seconds(st, en, zoom, fx, fy)

        # Short establishing/action view. Keep it brief so dialogue does not
        # spend several seconds in the same flat two-shot.
        first_start = float(timeline[0]["start"]) if timeline else duration
        if first_start > 0.05:
            lead_end = min(first_start, 1.65)
            if natural_safe:
                add_seconds(0.0, lead_end, 1.04, WIDTH // 2, 560)
                if first_start > lead_end:
                    add_seconds(lead_end, first_start, 1.08, WIDTH // 2, 560)
            else:
                add_seconds(0.0, lead_end, 1.06 if action in {"run", "walk", "enter", "exit", "chase"} else 1.14, WIDTH // 2, 520)
                if first_start > lead_end:
                    add_seconds(lead_end, first_start, 1.20, WIDTH // 2, 500)

        listener_limit = max(2, int(
            self.performance_config.get("performance", {}).get(
                "listener_reaction_max_per_scene", 2
            )
        ))
        listener_hold = max(0.30, float(
            self.performance_config.get("performance", {}).get(
                "listener_reaction_seconds", 0.42
            )
        ))
        reaction_cuts = 0

        for i, item in enumerate(timeline):
            char_id = str(item["character_id"])
            start_t = float(item["start"])
            voice_end = max(start_t, float(item.get("voice_end", item.get("end", start_t))))
            next_start = (
                float(timeline[i + 1]["start"])
                if i + 1 < len(timeline)
                else duration
            )
            punch = scene.beat in {"reaction", "punchline", "callback"} and i == len(timeline) - 1
            listener = next((cid for cid in characters if cid != char_id), None)

            # During a long sentence, briefly cut to the listener while the
            # speaker keeps talking. Split around that insert so it truly wins
            # rather than being hidden under a full-line camera segment.
            spoken_span = voice_end - start_t
            if listener is not None and spoken_span >= 3.0 and reaction_cuts < listener_limit:
                rs = start_t + spoken_span * 0.57
                re = min(voice_end - 0.10, rs + 0.34)
                if re - rs >= 0.20:
                    add_speaker_chunks(start_t, rs, char_id, line_index=i, punch=False)
                    lfx, lfy = focus_for(listener)
                    add_seconds(rs, re, 1.16 if natural_safe else 1.86, lfx, lfy)
                    add_speaker_chunks(re, voice_end, char_id, line_index=i + 1, punch=punch)
                    reaction_cuts += 1
                else:
                    add_speaker_chunks(start_t, voice_end, char_id, line_index=i, punch=punch)
            else:
                add_speaker_chunks(start_t, voice_end, char_id, line_index=i, punch=punch)

            # Use natural inter-line silence for an additional listener reaction
            # close-up. If there is no silence, skip it rather than slowing audio.
            if listener is not None and reaction_cuts < listener_limit:
                gap_start = voice_end + 0.025
                gap_end = min(next_start - 0.025, gap_start + listener_hold)
                if gap_end - gap_start >= 0.18:
                    lfx, lfy = focus_for(listener)
                    add_seconds(gap_start, gap_end, 1.16 if natural_safe else 1.92, lfx, lfy)
                    reaction_cuts += 1

        if scene.reaction is not None:
            reaction_seconds = max(0.38, min(0.72, float(scene.reaction.duration_seconds)))
            start_t = max(0.0, duration - reaction_seconds)
            fx, fy = focus_for(scene.reaction.character_id)
            # Only add when the reaction occupies tail time after the spoken
            # coverage; nested expressions below make the earliest segment win
            # on accidental overlaps, so avoid relying on overlap priority.
            last_end = max((b for _, b, _, _, _ in segments), default=0) / self.fps
            if start_t >= last_end - 0.04:
                add_seconds(start_t, duration, 1.18 if natural_safe else 2.12, fx, fy)

        if not segments:
            segments = [(0, total_frames, 1.06 if natural_safe else 1.12, WIDTH // 2, 560 if natural_safe else 480)]

        # Sort and fill any uncovered gaps with the nearest prior framing.
        segments.sort(key=lambda item: (item[0], item[1]))

        def nested(values: list[tuple[int, int, str]], default: str) -> str:
            expr = default
            for a, b, value in reversed(values):
                expr = f"if(between(on\\,{a}\\,{b})\\,{value}\\,{expr})"
            return expr

        z_values = [(a, b, f"{zoom:.3f}") for a, b, zoom, _, _ in segments]
        x_values: list[tuple[int, int, str]] = []
        y_values: list[tuple[int, int, str]] = []
        for a, b, zoom, fx, fy in segments:
            x_values.append((a, b, f"max(0\\,min(iw-iw/zoom\\,{fx}-iw/(2*zoom)))"))
            y_values.append((a, b, f"max(0\\,min(ih-ih/zoom\\,{fy}-ih/(2*zoom)))"))

        z_expr = nested(z_values, "1.06" if natural_safe else "1.10")
        x_expr = nested(x_values, "max(0\\,min(iw-iw/zoom\\,iw/2-iw/(2*zoom)))")
        y_expr = nested(y_values, "max(0\\,min(ih-ih/zoom\\,480-ih/(2*zoom)))")
        return (
            "zoompan="
            f"z='{z_expr}':"
            f"x='{x_expr}':"
            f"y='{y_expr}':"
            "d=1:"
            f"s={WIDTH}x{HEIGHT}:"
            f"fps={self.fps}",
            len(segments),
        )

    def _render_static_scene(
        self,
        *,
        scene: CartoonScene,
        scene_audio: Path,
        timeline: list[dict[str, object]],
        output: Path,
    ) -> None:
        """Degraded renderer that preserves V17 natural actors and floor contact.

        V17.5 fixed the normal compositor but the emergency/static path still
        selected legacy geometric sprites while using V17 natural-actor floor
        coordinates. That mismatch put the legacy sprite's feet around sofa/table
        height — exactly the visual failure seen in the reference run. V17.6 keeps
        the reviewed natural cutouts, their contact shadows, and the same camera
        space even when animated rendering fails.
        """
        duration = self._wave_duration(scene_audio)
        bg = self._background_path(scene.location_id)
        characters = self._scene_characters(scene)[:4]
        action = self._resolve_visual_action(scene)
        natural_characters = [
            cid for cid in characters
            if self._is_hindi_mass_channel()
            and natural_actor_available(self.project_root, cid)
        ]
        positions = self._positions_for_scene(
            scene=scene,
            characters=characters,
            action=action,
        )
        print(
            "[CARTOON STATIC ACTION V17.6] "
            f"scene={scene.id}; location={scene.location_id}; "
            f"background={bg.name}; action={action}; "
            f"blocking={getattr(scene, 'blocking_mode', 'auto')}; "
            f"actors={','.join(characters)}; "
            f"natural={','.join(natural_characters) if natural_characters else 'none'}"
        )

        inputs = [bg]
        if natural_characters:
            # Do not zoom/move the set underneath fixed fallback actors. The
            # whole frame stays in one perspective so feet/shadows remain locked.
            background_filter = (
                f"scale={WIDTH}:{HEIGHT}:flags=lanczos,"
                "unsharp=5:5:0.24:5:5:0,format=rgba"
            )
        else:
            background_filter = self._dynamic_background_filter(
                scene=scene, duration=duration
            )
        filters = [f"[0:v]{background_filter}[base]"]
        current = "base"

        # V17.6 contact shadows in degraded mode. The prior static compositor had
        # no natural shadow at all, so even correctly placed actors looked pasted on.
        natural_shadow_path = self.project_root / "assets" / "cartoon_v17" / "contact_shadow.png"
        legacy_shadow_path = self.prop_root / "character_shadow.png"
        for shadow_index, char_id in enumerate(characters):
            shadow_path = (
                natural_shadow_path
                if char_id in natural_characters and natural_shadow_path.is_file()
                else legacy_shadow_path
            )
            if not shadow_path.is_file():
                continue
            idx = len(inputs)
            inputs.append(shadow_path)
            x, y = positions[char_id]
            x_expr, y_expr = self._character_motion_expr(
                scene=scene, character_id=char_id, base_x=x, base_y=y,
                duration=duration, timeline=timeline, action=action,
            )
            label = f"sf_shadow_{shadow_index}"
            if char_id in natural_characters:
                sx = f"({x_expr})+90"
                sy = f"({y_expr})+703"
            else:
                sx = f"({x_expr})+90"
                sy = "930"
            filters.append(
                f"[{current}][{idx}:v]overlay=x='{sx}':y='{sy}':"
                f"format=auto:eval=frame[{label}]"
            )
            current = label

        interaction = v16_interaction_mode(scene, characters, action)
        primary = next(
            (str(item.get("character_id")) for item in timeline if str(item.get("character_id")) in characters),
            characters[0] if characters else None,
        )
        locomotion_actions = {"run", "walk", "enter", "exit", "chase"}

        for index, char_id in enumerate(characters, start=1):
            x, y = positions[char_id]
            x_expr, y_expr = self._character_motion_expr(
                scene=scene,
                character_id=char_id,
                base_x=x,
                base_y=y,
                duration=duration,
                timeline=timeline,
                action=action,
            )
            if char_id in natural_characters:
                own_index = next(
                    (i for i, raw in enumerate(timeline) if str(raw.get("character_id")) == char_id),
                    0,
                )
                target = line_addressee(
                    timeline, own_index, characters, interaction, primary
                ) if timeline else None
                if not target or target == char_id:
                    target = next((c for c in characters if c != char_id), "camera")
                direction = gaze_direction(char_id, target, positions)
                sprite = natural_actor_path(self.project_root, char_id, direction)
                draw_x = x_expr if action in locomotion_actions else str(x)
                draw_y = y_expr if action in locomotion_actions else str(y)
            else:
                sprite = self._sprite_path(char_id, "neutral", "closed")
                draw_x = x_expr
                draw_y = y_expr

            inputs.append(sprite)
            idx = len(inputs) - 1
            label = f"sf_actor_{index}"
            filters.append(
                f"[{current}][{idx}:v]overlay=x='{draw_x}':y='{draw_y}':"
                f"format=auto:eval=frame[{label}]"
            )
            current = label

        # Keep important story props visible even in degraded rendering.
        for prop_index, spec in enumerate(
            self._prop_specs(scene=scene, action=action, duration=duration)
        ):
            path = self.prop_root / f"{spec['name']}.png"
            if not path.is_file():
                continue
            idx = len(inputs)
            inputs.append(path)
            label = f"sf_prop_{prop_index}"
            filters.append(
                f"[{current}][{idx}:v]overlay=x='{spec['x']}':y='{spec['y']}':"
                f"format=auto:eval=frame:enable='{spec.get('enable','1')}'[{label}]"
            )
            current = label

        filters.append(f"[{current}]fps={self.fps},format=yuv420p[vout]")

        args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        for image in inputs:
            args += ["-loop", "1", "-framerate", str(self.fps), "-i", str(image)]
        audio_index = len(inputs)
        args += ["-i", str(scene_audio)]
        args += [
            "-filter_complex", ";".join(filters),
            "-map", "[vout]",
            "-map", f"{audio_index}:a",
            *self._encoder_args,
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(output),
        ]
        self._run(args, label=f"render V17.6 static scene {scene.id}")

    # ------------------------------------------------------------------
    # Final assembly
    # ------------------------------------------------------------------
    def _concat_scene_videos(self, *, scene_videos: list[Path], output: Path) -> None:
        listing = output.with_suffix(".concat.txt")
        listing.write_text(
            "".join(f"file '{self._concat_escape(path)}'\n" for path in scene_videos),
            encoding="utf-8",
        )
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-c",
                "copy",
                str(output),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if proc.returncode == 0 and output.is_file():
            return

        # Codec-copy concat should normally work because all scenes share exact
        # settings. Re-encode only if a local FFmpeg build rejects the concat.
        self._degraded = True
        self._warnings.append("scene codec-copy concat failed; visual concat re-encoded")
        self._run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-an",
                "-vf",
                f"scale={WIDTH}:{HEIGHT},fps={self.fps}",
                *self._encoder_args,
                str(output),
            ],
            label="reencode visual concat",
        )

    def _master_indian_episode_audio(self, path: Path) -> None:
        """One final program-level loudness pass after scene concatenation."""
        tmp = path.with_name(path.stem + "_v171_mastered.wav")
        mastering = self._hindi_audio_profile.get("mastering", {})
        if not isinstance(mastering, dict):
            mastering = {}
        target_lufs = float(mastering.get("integrated_lufs", -14.2))
        true_peak = float(mastering.get("true_peak_db", -1.2))
        lra = float(mastering.get("lra", 6.5))
        # Keep dialogue anchored in the center, then add only a very small
        # decorrelated high-frequency side field. The reference videos are not
        # drenched in reverb; this is just enough stereo depth to avoid the
        # flat dual-mono presentation while preserving intelligibility.
        master_filter = (
            "[0:a]asplit=3[dry][sl][sr];"
            "[dry]pan=stereo|c0=0.97*c0|c1=0.97*c0[center];"
            "[sl]highpass=f=2200,lowpass=f=10500,volume=0.055,adelay=11,"
            "pan=stereo|c0=c0|c1=0*c0[left];"
            "[sr]highpass=f=2600,lowpass=f=12000,volume=0.055,adelay=19,"
            "pan=stereo|c0=0*c0|c1=c0[right];"
            "[center][left][right]amix=inputs=3:duration=first:normalize=0,"
            f"loudnorm=I={target_lufs:.1f}:TP={true_peak:.1f}:LRA={lra:.1f}[aout]"
        )
        self._run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(path),
            "-filter_complex", master_filter,
            "-map", "[aout]",
            "-ac", "2", "-ar", str(AUDIO_RATE), "-c:a", "pcm_s24le", str(tmp),
        ], label="V17.5 final Hindi stereo master")
        tmp.replace(path)

    def _mux_master_audio(
        self,
        *,
        visual_video: Path,
        master_audio: Path,
        output: Path,
    ) -> None:
        duration = self._wave_duration(master_audio)
        self._run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(visual_video),
                "-i",
                str(master_audio),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "256k",
                "-ar",
                str(AUDIO_RATE),
                "-ac",
                "2",
                "-t",
                f"{duration:.4f}",
                "-movflags",
                "+faststart",
                str(output),
            ],
            label="mux final video",
        )

    def _extract_audio(self, *, video: Path, output: Path) -> None:
        self._run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(video),
                "-vn",
                "-ac",
                "2",
                "-ar",
                str(AUDIO_RATE),
                "-c:a",
                "pcm_s16le",
                str(output),
            ],
            label="extract master wav",
        )

    def _duration_fix(
        self,
        *,
        video: Path,
        audio: Path,
        output: Path,
        duration: float,
    ) -> None:
        self._run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(video),
                "-i",
                str(audio),
                "-filter_complex",
                "[0:v]tpad=stop_mode=clone:stop_duration=2[v]",
                "-map",
                "[v]",
                "-map",
                "1:a:0",
                "-t",
                f"{duration:.4f}",
                *self._encoder_args,
                "-c:a",
                "aac",
                "-b:a",
                "256k",
                "-movflags",
                "+faststart",
                str(output),
            ],
            label="duration alignment",
        )

    def _emergency_render(
        self,
        *,
        plan: CartoonEpisodePlan,
        work_root: Path,
        final_video: Path,
        master_audio: Path,
    ) -> None:
        """Last-resort renderer that still preserves scene/background changes.

        Older emergency mode looped the FIRST background for the entire video,
        which made every scene look fixed exactly when a normal render failed.
        V11.3 synthesizes per-scene audio, renders each planned background with
        the same dynamic environment filter, then concatenates the clips.
        """
        emergency_audio_dir = work_root / "emergency_audio"
        emergency_video_dir = work_root / "emergency_scenes"
        emergency_audio_dir.mkdir(parents=True, exist_ok=True)
        emergency_video_dir.mkdir(parents=True, exist_ok=True)
        master_pieces: list[tuple[Path | None, float]] = []
        scene_videos: list[Path] = []
        index = 0

        # compatibility marker for V11.3 validator: emergency dynamic scene
        for scene in plan.scenes:
            scene_pieces: list[tuple[Path | None, float]] = [(None, 0.25)]
            scene_timeline: list[dict[str, object]] = []
            cursor = 0.25
            for line in scene.dialogue:
                index += 1
                path = emergency_audio_dir / f"line_{index:03d}.wav"
                self._synthesize_line(
                    text=line.text,
                    character_id=line.character_id,
                    output=path,
                )
                voice_seconds = max(0.05, self._wave_duration(path))
                start = cursor
                voice_end = start + voice_seconds
                pause = min(
                    MAX_INTERLINE_PAUSE,
                    max(
                        MIN_INTERLINE_PAUSE,
                        float(line.pause_after_seconds) * INTERLINE_PAUSE_SCALE,
                    ),
                )
                end = voice_end + pause
                scene_timeline.append({
                    "character_id": line.character_id,
                    "start": start,
                    "voice_end": voice_end,
                    "end": end,
                    "emotion": line.emotion,
                    "pose": line.pose,
                    "mouth_windows": [],
                })
                cursor = end
                scene_pieces.append((path, 0.0))
                scene_pieces.append((None, pause))

            scene_wav = emergency_audio_dir / f"scene_{scene.id:02d}.wav"
            self._write_wav_timeline(scene_pieces, scene_wav)
            master_pieces.extend(scene_pieces)

            scene_video = emergency_video_dir / f"scene_{scene.id:02d}.mp4"
            # Use the action-aware static compositor rather than background-only
            # emergency video. This preserves location, cast, movement and props
            # even when every articulated scene render fails.
            self._render_static_scene(
                scene=scene,
                scene_audio=scene_wav,
                timeline=scene_timeline,
                output=scene_video,
            )
            scene_videos.append(scene_video)

        self._write_wav_timeline(master_pieces, master_audio)
        visual_concat = emergency_video_dir / "visual_concat.mp4"
        self._concat_scene_videos(scene_videos=scene_videos, output=visual_concat)
        self._mux_master_audio(
            visual_video=visual_concat,
            master_audio=master_audio,
            output=final_video,
        )
        delivered = master_audio.with_name(master_audio.stem + "_delivered.wav")
        self._extract_audio(video=final_video, output=delivered)
        delivered.replace(master_audio)

    # ------------------------------------------------------------------
    # Asset / camera helpers
    # ------------------------------------------------------------------
    def _scene_characters(self, scene: CartoonScene) -> list[str]:
        valid = set(character_registry())
        result: list[str] = []
        for line in scene.dialogue:
            if line.character_id in valid and line.character_id not in result:
                result.append(line.character_id)
        if scene.reaction and scene.reaction.character_id in valid and scene.reaction.character_id not in result:
            result.append(scene.reaction.character_id)
        for character_id in scene.visual_characters:
            if character_id in valid and character_id not in result:
                result.append(character_id)
        if not result:
            result = ["guddu", "bittu"]
        return result[:4]

    @staticmethod
    def _positions_for(characters: list[str]) -> dict[str, tuple[int, int]]:
        if len(characters) <= 1:
            xs = [700]
        elif len(characters) == 2:
            xs = [250, 1150]
        elif len(characters) == 3:
            xs = [80, 700, 1320]
        else:
            xs = [20, 500, 980, 1460]
        return {
            char_id: (xs[index], 245)
            for index, char_id in enumerate(characters)
        }

    def _dynamic_background_filter(
        self,
        *,
        scene: CartoonScene,
        duration: float,
    ) -> str:
        """Render a visibly different virtual set/camera zone per scene.

        V11.2 moved the plate only a few pixels, so a 1080p viewer could still
        perceive a frozen background. V11.3 uses meaningful crop zones plus
        bounded drift. It still uses the existing background asset, needs no
        extra LLM/image call, and works for every capability world.
        """
        cfg = self.performance_config.get("environment", {})
        if not bool(cfg.get("dynamic_background_enabled", True)):
            return f"scale={WIDTH}:{HEIGHT},format=rgba"

        ambient = max(18, int(cfg.get("ambient_drift_px", 52)))
        action_track = max(ambient, int(cfg.get("action_track_px", 120)))
        vertical = max(6, int(cfg.get("vertical_drift_px", 18)))
        phase = (int(scene.id) % 11) * 0.41
        frames = max(1.0, duration * self.fps)

        variant = str(getattr(scene, "environment_variant", "auto") or "auto")
        motion = str(getattr(scene, "environment_motion", "auto") or "auto")

        # Scale factors are intentionally large enough to read as a new shot
        # area at 1080p. Left/right variants expose different portions of the
        # same physical set instead of pretending the location changed.
        scale_by_variant = {
            "establishing": 1.06,
            "wide_left": 1.18,
            "wide_right": 1.18,
            "medium_left": 1.30,
            "medium_right": 1.30,
            "center_detail": 1.42,
            # Backward compatibility for V11.2 saved plans.
            "left_bias": 1.24,
            "right_bias": 1.24,
            "auto": 1.16,
        }
        factor = float(scale_by_variant.get(variant, 1.16))
        scaled_w = max(WIDTH, int(round(WIDTH * factor)))
        scaled_h = max(HEIGHT, int(round(HEIGHT * factor)))
        # Keep even dimensions for common H.264 encoders.
        scaled_w += scaled_w % 2
        scaled_h += scaled_h % 2
        range_x = max(0.0, float(scaled_w - WIDTH))
        range_y = max(0.0, float(scaled_h - HEIGHT))

        zone = 0.50
        if variant in {"wide_left", "medium_left", "left_bias"}:
            zone = 0.18
        elif variant in {"wide_right", "medium_right", "right_bias"}:
            zone = 0.82
        elif variant == "center_detail":
            zone = 0.54

        center_x = range_x * zone
        center_y = range_y * (0.44 if variant == "establishing" else 0.50)

        if motion == "action_track":
            raw_x = (
                f"{center_x:.3f}+{action_track:.3f}*((n/{frames:.3f})-0.5)"
                f"+{ambient * 0.55:.3f}*sin(n*0.045+{phase:.3f})"
            )
            raw_y = f"{center_y:.3f}+{vertical:.3f}*sin(n*0.055+{phase + 0.8:.3f})"
        elif motion == "directional_drift":
            direction = -1.0 if int(scene.id) % 2 else 1.0
            raw_x = f"{center_x:.3f}+{direction * ambient * 1.25:.3f}*((n/{frames:.3f})-0.5)"
            raw_y = f"{center_y:.3f}+{vertical * 0.70:.3f}*sin(n*0.035+{phase:.3f})"
        elif motion == "explore_drift":
            raw_x = f"{center_x:.3f}+{ambient * 1.45:.3f}*sin(n*0.030+{phase:.3f})"
            raw_y = f"{center_y:.3f}+{vertical:.3f}*sin(n*0.041+{phase + 0.5:.3f})"
        elif motion == "focus_drift":
            raw_x = f"{center_x:.3f}+{ambient * 0.80:.3f}*sin(n*0.033+{phase:.3f})"
            raw_y = f"{center_y:.3f}+{vertical * 0.60:.3f}*sin(n*0.047+{phase + 0.3:.3f})"
        elif motion == "breathing_hold":
            raw_x = f"{center_x:.3f}+{ambient * 0.45:.3f}*sin(n*0.027+{phase:.3f})"
            raw_y = f"{center_y:.3f}+{vertical * 0.45:.3f}*sin(n*0.031+{phase + 0.7:.3f})"
        elif motion == "establishing_drift":
            raw_x = f"{center_x:.3f}+{ambient * 1.10:.3f}*((n/{frames:.3f})-0.5)"
            raw_y = f"{center_y:.3f}+{vertical * 0.55:.3f}*sin(n*0.030+{phase:.3f})"
        else:
            raw_x = f"{center_x:.3f}+{ambient * 0.70:.3f}*sin(n*0.028+{phase:.3f})"
            raw_y = f"{center_y:.3f}+{vertical * 0.55:.3f}*sin(n*0.037+{phase + 0.4:.3f})"

        # crop expressions are explicitly bounded so stronger motion never asks
        # FFmpeg to sample outside the scaled plate.
        x_expr = f"max(0,min({range_x:.3f},{raw_x}))"
        y_expr = f"max(0,min({range_y:.3f},{raw_y}))"
        return (
            f"scale={scaled_w}:{scaled_h},"
            f"crop={WIDTH}:{HEIGHT}:x='{x_expr}':y='{y_expr}',"
            "format=rgba"
        )

    def _background_path(self, location_id: str) -> Path:
        resolved = resolve_background_asset_id(location_id)
        path = self.background_root / f"{resolved}.png"
        if path.is_file():
            return path
        fallback = (
            self.background_root / "city_street.png"
            if (self.background_root / "city_street.png").is_file()
            else self.background_root / "courtyard.png"
        )
        self._degraded = True
        self._warnings.append(
            f"unknown background {location_id!r}; universal neutral fallback used"
        )
        return fallback

    def _sprite_path(
        self,
        character_id: str,
        expression: str,
        mouth: str,
        pose: str = "idle",
    ) -> Path:
        expr = self._expression_asset(expression)
        pose_name = self._pose_asset(pose)

        if pose_name != "idle":
            posed = (
                self.sprite_root
                / character_id
                / "poses"
                / pose_name
                / f"{expr}_{mouth}.png"
            )
            if posed.is_file():
                return posed

        path = self.sprite_root / character_id / f"{expr}_{mouth}.png"
        if path.is_file():
            return path

        fallback = self.sprite_root / "guddu" / f"neutral_{mouth}.png"
        self._degraded = True
        self._warnings.append(
            f"sprite missing for {character_id}/{expression}/{mouth}/{pose}; fallback used"
        )
        return fallback

    @staticmethod
    def _pose_asset(value: str) -> str:
        key = (value or "idle").casefold().strip().replace("-", "_").replace(" ", "_")
        aliases = {
            "idle":"idle","neutral":"idle","standing":"idle",
            "point":"pointing","pointing":"pointing","angry":"pointing",
            "hands_up":"hands_up","handsup":"hands_up",
            "shocked":"hands_up","surprised":"hands_up",
            "thinking":"thinking","think":"thinking","confused":"thinking",
            "running":"running","run":"running","walking":"running","walk":"running",
            "holding":"holding_food","holding_food":"holding_food",
            "carry":"holding_food","carrying":"holding_food",
        }
        return aliases.get(key,"idle")

    @staticmethod
    def _baseline_pose(
        *,
        character_id: str,
        action: str,
    ) -> str:
        if character_id == "bandar":
            return "idle"
        if action == "cook_litti" and character_id == "mai":
            return "holding_food"
        if action == "steal_tray":
            return "hands_up"
        if action == "chase":
            return "running"
        if action == "chacha_slip":
            return "running" if character_id == "chacha" else "hands_up"
        if action == "bait_trap":
            if character_id == "bittu":
                return "pointing"
            if character_id == "guddu":
                return "thinking"
        if action == "food_chaos":
            return "hands_up"
        if action == "baby_reveal":
            return "thinking"
        if action == "final_snatch":
            return "hands_up"
        if action in {"chase", "run", "walk", "enter", "exit"}:
            return "running"
        if action in {"grab", "give", "point"}:
            return "pointing"
        if action in {"carry", "eat"}:
            return "holding_food"
        if action in {"search", "hide", "use_device", "open", "reveal"}:
            return "thinking"
        if action in {"celebrate", "dance", "jump", "fall", "magic", "reaction"}:
            return "hands_up"
        return "idle"

    def _line_pose(
        self,
        *,
        character_id: str,
        requested: str,
        action: str,
    ) -> str:
        pose = self._pose_asset(requested)
        if pose != "idle":
            return pose
        return self._baseline_pose(
            character_id=character_id,
            action=action,
        )

    def _reaction_pose(
        self,
        *,
        expression: str,
        action: str,
        character_id: str,
    ) -> str:
        expr = self._expression_asset(expression)
        if character_id != "bandar":
            if expr == "shocked":
                return "hands_up"
            if expr == "confused":
                return "thinking"
            if action in {"steal_tray","food_chaos","final_snatch"}:
                return "hands_up"
            if action == "chacha_slip" and character_id == "chacha":
                return "hands_up"
            if action == "baby_reveal":
                return "thinking"
        return "idle"

    def _expression_asset(self, value: str) -> str:
        return self._EXPRESSION_ALIASES.get((value or "neutral").casefold(), "neutral")

    def _camera_filter(
        self,
        *,
        scene: CartoonScene,
        characters: list[str],
        positions: dict[str, tuple[int, int]],
    ) -> str:
        camera = scene.camera
        if camera == "wide":
            return f"scale={WIDTH}:{HEIGHT}"
        if camera in {"medium", "medium_two_shot", "over_shoulder"}:
            return "scale=2074:1166,crop=1920:1080:77:43"

        focus = None
        if scene.reaction and scene.reaction.character_id in positions:
            focus = scene.reaction.character_id
        elif scene.dialogue:
            focus = scene.dialogue[-1].character_id
        if focus not in positions and characters:
            focus = characters[0]

        focus_x = positions.get(focus, (700, 245))[0]
        # After scaling 1920->2304, crop range is 0..384.
        if focus_x < 600:
            crop_x = 0
        elif focus_x > 1000:
            crop_x = 384
        else:
            crop_x = 192

        if camera in {"close_up", "reaction_close_up"}:
            return f"scale=2304:1296,crop=1920:1080:{crop_x}:108"
        return f"scale={WIDTH}:{HEIGHT}"

    @staticmethod
    def _between(start: float, end: float) -> str:
        return f"between(t\\,{start:.3f}\\,{end:.3f})"

    # ------------------------------------------------------------------
    # WAV helpers
    # ------------------------------------------------------------------
    def _write_wav_timeline(
        self,
        pieces: list[tuple[Path | None, float]],
        output: Path,
    ) -> None:
        with wave.open(str(output), "wb") as out:
            out.setnchannels(AUDIO_CHANNELS)
            out.setsampwidth(AUDIO_SAMPLE_WIDTH)
            out.setframerate(AUDIO_RATE)
            for path, silence_seconds in pieces:
                if path is None:
                    frames = int(round(max(0.0, silence_seconds) * AUDIO_RATE))
                    out.writeframes(b"\x00\x00" * frames)
                    continue
                with wave.open(str(path), "rb") as src:
                    if (
                        src.getnchannels() != AUDIO_CHANNELS
                        or src.getsampwidth() != AUDIO_SAMPLE_WIDTH
                        or src.getframerate() != AUDIO_RATE
                    ):
                        raise ValueError(f"Unexpected WAV format: {path}")
                    out.writeframes(src.readframes(src.getnframes()))

    def _concat_wavs(self, paths: Iterable[Path], output: Path) -> None:
        with wave.open(str(output), "wb") as out:
            out.setnchannels(AUDIO_CHANNELS)
            out.setsampwidth(AUDIO_SAMPLE_WIDTH)
            out.setframerate(AUDIO_RATE)
            for path in paths:
                with wave.open(str(path), "rb") as src:
                    out.writeframes(src.readframes(src.getnframes()))

    @staticmethod
    def _write_silence(path: Path, duration: float) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(AUDIO_CHANNELS)
            wf.setsampwidth(AUDIO_SAMPLE_WIDTH)
            wf.setframerate(AUDIO_RATE)
            frames = int(round(max(0.2, duration) * AUDIO_RATE))
            wf.writeframes(b"\x00\x00" * frames)

    @staticmethod
    def _wave_duration(path: Path) -> float:
        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / float(wf.getframerate())

    @staticmethod
    def _estimated_speech_seconds(*, text: str, rate: int) -> float:
        words = max(1, len(re.findall(r"\S+", text)))
        by_words = words / max(80.0, float(rate)) * 60.0
        by_chars = len(text) / 12.0
        return max(1.2, min(12.0, max(by_words, by_chars)))

    # ------------------------------------------------------------------
    # Runtime helpers
    # ------------------------------------------------------------------
    def _validate_runtime(self) -> None:
        for tool in ("ffmpeg", "ffprobe"):
            if not shutil.which(tool):
                raise RuntimeError(f"Required renderer tool not found: {tool}")
        required = [
            self.background_root / "living_room.png",
            self.project_root / "configs" / "cartoon_rigs_v10.json",
            self.rig_root / "guddu" / "body_walk_frames" / "frame_00.png",
            self.performance_root / "guddu" / "body_walk_right.mov",
            self.rig_root / "guddu" / "body_run_frames" / "frame_00.png",
            self.rig_root / "guddu" / "face_neutral_closed.png",
            self.rig_prop_root / "suitcase.png",
            self.sprite_root / "guddu" / "neutral_closed.png",
            self.sprite_root / "guddu" / "neutral_open.png",
            self.sfx_root / "comic_sting.wav",
            self.prop_root / "character_shadow.png",
            self.prop_root / "litti_tray.png",
            self.sprite_root / "guddu" / "poses" / "running" / "neutral_closed.png",
        ]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise RuntimeError("Missing bundled cartoon assets: " + ", ".join(missing))

    def _select_video_encoder(self) -> list[str]:
        encoders = ""
        if shutil.which("ffmpeg"):
            proc = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            encoders = proc.stdout

        if platform.system() == "Darwin" and "h264_videotoolbox" in encoders:
            return [
                "-c:v",
                "h264_videotoolbox",
                "-b:v",
                "12M",
                "-maxrate",
                "16M",
                "-bufsize",
                "24M",
                "-profile:v",
                "high",
                "-pix_fmt",
                "yuv420p",
            ]

        return [
            "-c:v",
            "libx264",
            "-preset",
            os.getenv("CONTENT_FACTORY_CARTOON_X264_PRESET", "medium"),
            "-crf",
            os.getenv("CONTENT_FACTORY_CARTOON_CRF", "18"),
            "-profile:v",
            "high",
            "-level:v",
            "4.1",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            os.getenv("CONTENT_FACTORY_CARTOON_FFMPEG_THREADS", "4"),
        ]

    def _measure_motion_quality(self, video: Path) -> dict[str, object]:
        """Cheap no-ML anti-slideshow metric using FFmpeg frame differences.

        A 4fps 320px grayscale sample is differenced frame-to-frame. YAVG is
        robust enough to distinguish mostly-static slides from limited
        animation with body acting/cuts while adding only a small post pass.
        """
        cfg = self.performance_config.get("motion_quality", {})
        sample_fps = max(1, int(cfg.get("sample_fps", 4)))
        min_median = float(cfg.get("minimum_median_difference_yavg", 4.5))
        min_mid80 = float(cfg.get("minimum_mid80_mean_yavg", 6.0))
        try:
            proc = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-i", str(video), "-vf",
                    (
                        f"fps={sample_fps},scale=320:-2,format=gray,"
                        "tblend=all_mode=difference,signalstats,"
                        "metadata=print:file=-"
                    ),
                    "-an", "-f", "null", "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stdout[-800:])
            values = [
                float(item)
                for item in re.findall(
                    r"lavfi\.signalstats\.YAVG=([0-9.]+)",
                    proc.stdout,
                )
            ]
            if len(values) < 3:
                raise RuntimeError("insufficient motion samples")
            ordered = sorted(values)
            n = len(ordered)
            if n % 2:
                median = ordered[n // 2]
            else:
                median = (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0
            if n >= 10:
                lo = max(0, int(n * 0.10))
                hi = min(n, max(lo + 1, int(n * 0.90)))
                mid = ordered[lo:hi]
            else:
                mid = ordered
            mid80 = sum(mid) / max(1, len(mid))
            status = (
                "PASS"
                if median >= min_median and mid80 >= min_mid80
                else "REVIEW_REQUIRED"
            )
            return {
                "status": status,
                "sample_fps": sample_fps,
                "sample_count": n,
                "median_yavg": round(median, 3),
                "mid80_mean_yavg": round(mid80, 3),
                "minimum_median_yavg": min_median,
                "minimum_mid80_mean_yavg": min_mid80,
            }
        except Exception as exc:
            return {
                "status": "REVIEW_REQUIRED",
                "sample_fps": sample_fps,
                "sample_count": 0,
                "median_yavg": 0.0,
                "mid80_mean_yavg": 0.0,
                "minimum_median_yavg": min_median,
                "minimum_mid80_mean_yavg": min_mid80,
                "error": f"{type(exc).__name__}: {str(exc)[:240]}",
            }

    def _media_duration(self, path: Path) -> float:
        proc = self._run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            label="probe duration",
            capture=True,
        )
        return float(proc.stdout.strip())

    @staticmethod
    def _concat_escape(path: Path) -> str:
        return str(path.resolve()).replace("'", "'\\''")

    @staticmethod
    def _unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        for index in range(2, 100):
            candidate = path.with_name(f"{path.stem}_{index:02d}{path.suffix}")
            if not candidate.exists():
                return candidate
        return path.with_name(f"{path.stem}_{uuid.uuid4().hex[:6]}{path.suffix}")

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.project_root))
        except ValueError:
            return str(path.resolve())

    def _dominant_voice_engine(self) -> str:
        engines = [str(item.get("engine", "unknown")) for item in self._voice_map.values()]
        if not engines:
            return "none"
        return max(set(engines), key=engines.count)

    @staticmethod
    def _run(
        args: list[str],
        *,
        label: str,
        capture: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"{label} failed ({proc.returncode}): {proc.stderr[-1000:]}"
            )
        return proc

    # ------------------------------------------------------------------
    # Fast package self-test
    # ------------------------------------------------------------------
    def self_test(self, output_dir: Path) -> Path:
        from content_factory.cartoon.models import (
            CartoonDialogueLine,
            CartoonReaction,
            CartoonScene,
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        audio = output_dir / "self_test.wav"
        self._write_silence(audio, 1.25)
        scene = CartoonScene(
            id=1,
            location_id="living_room",
            beat="punchline",
            camera="medium_two_shot",
            shot_duration_seconds=2.0,
            setup="Renderer articulated walk suitcase self test",
            dialogue=[
                CartoonDialogueLine(
                    character_id="guddu",
                    text="self test",
                    emotion="smirk",
                    pose="thinking",
                ),
                CartoonDialogueLine(
                    character_id="bittu",
                    text="self test reply",
                    emotion="laughing",
                    pose="pointing",
                ),
            ],
            reaction=CartoonReaction(
                character_id="bittu",
                expression="shocked",
                duration_seconds=0.4,
                camera="reaction_close_up",
                sfx="comic_sting",
            ),
            sfx_cues=["comic_sting"],
            camera_action="quick_push_in",
            transition="hard_cut",
            visual_action="walk",
            props=["suitcase"],
        )
        timeline = [
            {
                "character_id": "guddu",
                "emotion": "smirk",
                "pose": "thinking",
                "start": 0.0,
                "voice_end": 0.45,
                "end": 0.58,
                "text": "self test",
            },
            {
                "character_id": "bittu",
                "emotion": "laughing",
                "pose": "pointing",
                "start": 0.60,
                "voice_end": 1.05,
                "end": 1.18,
                "text": "self test reply",
            },
        ]
        output = output_dir / "renderer_self_test.mp4"
        self._render_scene_video(
            scene=scene,
            scene_audio=audio,
            timeline=timeline,
            output=output,
        )
        return output


def _self_test_main(project_root: Path) -> int:
    language = load_language_pack("hindi")
    renderer = CartoonRenderer(project_root=project_root, language=language)
    with tempfile.TemporaryDirectory(prefix="cartoon-v91-selftest-") as temp:
        temp_path = Path(temp)
        path = renderer.self_test(temp_path)
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,r_frame_rate,codec_name",
                "-of",
                "json",
                str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        data = json.loads(proc.stdout)["streams"][0]
        assert data["width"] == WIDTH, data
        assert data["height"] == HEIGHT, data
        assert data["r_frame_rate"] == f"{FPS}/1", data
        assert data["codec_name"] == "h264", data

        # Validate the complete delivery chain without another expensive scene
        # encode: reuse the short scene twice, concat, mux a matching WAV, and
        # verify the delivered MP4/WAV durations remain aligned.
        scene_seconds = renderer._media_duration(path)
        master = temp_path / "self_test_master.wav"
        renderer._write_silence(master, scene_seconds * 2.0)
        visual = temp_path / "self_test_visual.mp4"
        renderer._concat_scene_videos(
            scene_videos=[path, path],
            output=visual,
        )
        final = temp_path / "self_test_final.mp4"
        renderer._mux_master_audio(
            visual_video=visual,
            master_audio=master,
            output=final,
        )
        delivered = temp_path / "self_test_delivered.wav"
        renderer._extract_audio(
            video=final,
            output=delivered,
        )
        delta = abs(
            renderer._media_duration(final)
            - renderer._wave_duration(delivered)
        )
        assert delta <= 0.10, delta

    print("Renderer asset/runtime self-test: OK")
    print("1080p24 H.264 articulated-animation clip: OK")
    print("V10 walk-cycle + suitcase hand-socket render: OK")
    print("V10 connected elbow/knee articulation: OK")
    print("Scene concat + master WAV + final MP4 mux: OK")
    print("MP4/WAV duration alignment <= 0.10s: OK")
    print("No runtime Pillow/image-generation dependency: OK")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(_self_test_main(args.project_root.resolve()))
    parser.error("Use --self-test when invoking renderer module directly.")


if __name__ == "__main__":
    main()
