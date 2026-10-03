"""Portable, offline lesson companion. No third-party assets or scripts."""

from __future__ import annotations

import html
import json
import os
from pathlib import Path

from content_factory.voice.timing import wav_seconds


def write_lesson(
    output: Path,
    voice_files: list[str],
    scenes: list,
    storyboards: list[dict],
    title: str,
) -> None:
    by_id = {int(s["scene_id"]): s for s in storyboards}
    active_checks = os.getenv("STUDY_ACTIVE_CHECKS", "off").strip().lower() in {"1", "true", "yes", "on"}
    chapters = []
    offset = 0.0
    for audio, scene in zip(voice_files, scenes, strict=True):
        board = by_id.get(scene.id, {})
        chapters.append(
            {
                "start": offset,
                "title": scene.title,
                "prompt": (board.get("interaction_prompt") or "") if active_checks else "",
                "answer": (board.get("interaction_answer") or "") if active_checks else "",
                "choices": board.get("interaction_choices", []) if active_checks else [],
            }
        )
        offset += wav_seconds(Path(audio))
    payload = json.dumps(chapters, ensure_ascii=False).replace("<", "\\u003c")
    template = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>
:root{color-scheme:dark}body{margin:0;background:#081321;color:#e9f0fa;font:17px system-ui;line-height:1.6}
main{max-width:1200px;margin:auto;padding:28px}h1{font-size:clamp(24px,4vw,40px)}
video{width:100%;border-radius:16px;background:black}section{display:grid;grid-template-columns:1fr 1fr;gap:24px}
article,nav{padding:22px;background:#14263b;border-radius:16px;margin-top:20px}
button,select{font:inherit;background:#23415a;color:white;border:1px solid #58738c;border-radius:8px;padding:9px 13px;margin:4px;cursor:pointer}
button:hover,button:focus{background:#305976;outline:2px solid #65dfc7}
nav button{display:block;text-align:left;width:100%}#answer{color:#82e7c7}small{color:#b6c6d8}
@media(max-width:700px){section{grid-template-columns:1fr}main{padding:14px}}
</style><main><small>STUDY LAB · WATCH → UNDERSTAND → REPLAY</small><h1>__TITLE__</h1>
<video id="video" controls preload="metadata" src="final_video.mp4"></video>
<label>Speed <select id="speed"><option>0.75</option><option selected>1</option><option>1.25</option><option>1.5</option></select></label>
<button id="replay">Replay chapter</button><label><input type="checkbox" id="autopause"> Pause at chapter changes for practice</label>
<section><nav aria-label="Lesson chapters" id="chapters"></nav><article id="practice">
<small id="chapter"></small><h2>Quick check</h2><p id="prompt"></p><div id="choices"></div>
<button id="reveal">Reveal explanation</button><p id="answer" aria-live="polite" hidden></p>
<small>Explain why before revealing. Change an input and predict what happens next.</small>
</article></section></main><script>
const data=__DATA__,video=document.getElementById('video');let current=-1;
const el=id=>document.getElementById(id);
function select(i){if(i===current)return;current=i;const c=data[i];
el('chapter').textContent=c.title;el('prompt').textContent=c.prompt;
el('practice').hidden=!c.prompt;el('answer').textContent=c.answer;el('answer').hidden=true;el('choices').replaceChildren();
(c.choices||[]).forEach(text=>{const b=document.createElement('button');b.textContent=text;b.onclick=()=>{video.pause();el('choices').querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed','false'));b.setAttribute('aria-pressed','true');};el('choices').append(b);});}
data.forEach((c,i)=>{const b=document.createElement('button');b.textContent=`${Math.floor(c.start/60)}:${String(Math.floor(c.start%60)).padStart(2,'0')} · ${c.title}`;b.onclick=()=>{video.currentTime=c.start;select(i);};el('chapters').append(b);});
video.addEventListener('timeupdate',()=>{let i=0;data.forEach((c,j)=>{if(video.currentTime>=c.start)i=j;});if(i!==current){if(current>=0&&el('autopause').checked)video.pause();select(i);}});
el('reveal').onclick=()=>{video.pause();el('answer').hidden=false;};el('speed').onchange=e=>video.playbackRate=Number(e.target.value);
el('replay').onclick=()=>{video.currentTime=data[Math.max(0,current)].start;video.play();};if(data.length)select(0);
</script></html>"""
    output.write_text(
        template.replace("__TITLE__", html.escape(title)).replace("__DATA__", payload),
        encoding="utf-8",
    )
    output.with_suffix(".json").write_text(
        json.dumps(chapters, indent=2, ensure_ascii=False), encoding="utf-8"
    )
