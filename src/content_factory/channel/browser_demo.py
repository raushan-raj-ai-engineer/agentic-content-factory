from __future__ import annotations
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlparse
from content_factory.local_video.media import duration_seconds,run,mux,concat_media
from .production import voice_backend,voice_clip,export_text


def load_demo(path):
    data=json.loads(path.read_text())
    if not isinstance(data,dict) or not isinstance(data.get('title'),str):raise ValueError('Demo requires a title')
    if not isinstance(data.get('steps'),list) or not 1<=len(data['steps'])<=30:raise ValueError('Demo needs 1 to 30 steps')
    page=data.get('page','')
    if not isinstance(page,str) or not page:raise ValueError('Demo page is required')
    parsed=urlparse(page)
    if parsed.scheme:
        if parsed.scheme not in ('http','https'):raise ValueError('Use HTTP(S) URL or a relative HTML file')
        target=page
    else:
        file=(path.parent/page).resolve()
        if not file.is_relative_to(path.parent.resolve()) or not file.is_file():raise ValueError('Local page must exist inside the config folder')
        target=file.as_uri()
    allowed={'click','fill','press','wait','scroll'}
    for step in data['steps']:
        if not isinstance(step,dict):raise ValueError('Each step must be an object')
        if not isinstance(step.get('title'),str) or not isinstance(step.get('narration'),str) or not 10<=len(step['narration'])<=1800:raise ValueError('Each step needs a title and 10–1800 character narration')
        actions=step.get('actions',[])
        if not isinstance(actions,list) or len(actions)>10:raise ValueError('At most 10 actions per step')
        for action in actions:
            if not isinstance(action,dict):raise ValueError('Each action must be an object')
            if action.get('type') not in allowed:raise ValueError('Unsupported browser action')
            if action['type'] in ('click','fill','press') and not isinstance(action.get('selector'),str):raise ValueError('Action selector required')
            if action['type']=='wait' and not 0<=float(action.get('seconds',0))<=10:raise ValueError('Wait must be 0–10 seconds')
    data['resolved_page']=target
    return data


def produce_demo(root,config,voice,headed=False):
    from playwright.sync_api import sync_playwright
    data=load_demo(config)
    out=root/'artifacts'/'channel'/'browser-demo'/uuid4().hex[:12];out.mkdir(parents=True)
    backend=voice_backend(root,voice)
    audios=[];lengths=[]
    for i,step in enumerate(data['steps']):
        audio=out/f'voice_{i:03d}.wav'
        seconds,_pace=voice_clip(backend,step['narration'],audio,stage='trace');lengths.append(seconds);audios.append(audio)
    raw,marks,window=record_steps(data,out,lengths,headed)
    # Browser recordings do not expose audio-clock timestamps. Align the tail of
    # the recorded content to the measured step window; keep raw recording for QA.
    lead=max(0,duration_seconds(raw)-window)
    clips=[]
    for i,((offset,length),audio) in enumerate(zip(marks,audios,strict=True)):
        video=out/f'step_{i:03d}_visual.mp4'
        run(['ffmpeg','-y','-ss',str(lead+offset),'-i',str(raw),'-vf','tpad=stop_mode=clone:stop_duration=0.3','-t',str(length),'-an','-r','24','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-threads','2',str(video)])
        if duration_seconds(video)<length-0.15:raise RuntimeError('Browser recording shorter than expected; inspect raw recording')
        clip=out/f'step_{i:03d}.mp4';mux(video,audio,clip);clips.append(clip)
    final=out/'video.mp4';concat_media(clips,final,reencode=True)
    export_text(out,data['steps'],[duration_seconds(c) for c in clips],data['title'],'An actual recorded browser demonstration with locally synthesized narration.')
    manifest={'mode':'browser-demo','source':data['resolved_page'],'duration_seconds':duration_seconds(final),'raw_recording':str(raw.relative_to(out)),'step_alignment':'measured wall-clock; review action/narration sync','review_required':True}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print(f'OUTPUT: {out}')
    return out


def record_steps(data,out,lengths,headed=False):
    """Record configured browser actions once; independent of speech synthesis."""
    from playwright.sync_api import sync_playwright
    marks=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=not headed)
        context=browser.new_context(viewport={'width':1920,'height':1080},record_video_dir=str(out/'recording'),record_video_size={'width':1920,'height':1080},device_scale_factor=1)
        page=context.new_page();page.set_default_timeout(15000)
        try:
            page.goto(data['resolved_page'],wait_until='load')
            page.wait_for_timeout(500)
            first=time.monotonic()
            for i,(step,length) in enumerate(zip(data['steps'],lengths,strict=True)):
                begin=time.monotonic()
                for action in step.get('actions',[]):
                    kind=action['type']
                    if kind=='click':page.locator(action['selector']).click()
                    elif kind=='fill':page.locator(action['selector']).fill(str(action.get('value','')))
                    elif kind=='press':page.locator(action['selector']).press(str(action.get('key','Enter')))
                    elif kind=='scroll':page.mouse.wheel(0,int(action.get('pixels',400)))
                    elif kind=='wait':page.wait_for_timeout(float(action.get('seconds',0))*1000)
                spent=time.monotonic()-begin
                if spent>length:raise RuntimeError(f'Step {i+1} actions exceed narration duration; shorten actions or extend narration')
                page.wait_for_timeout((length-spent)*1000)
                marks.append((begin-first,length))
                if i==len(data['steps'])-1:page.screenshot(path=str(out/'thumbnail.png'))
            end=time.monotonic()
            recorded=page.video
        finally:
            context.close();browser.close()
        raw=Path(recorded.path())
    return raw,marks,end-first
