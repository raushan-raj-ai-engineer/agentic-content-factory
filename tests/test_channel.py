import json
import random
from collections import Counter
import pytest
from content_factory.channel.catalog import lesson
from content_factory.channel.production import checked_solution
from content_factory.channel.browser_demo import load_demo


def test_algorithm_traces_against_independent_oracles():
    rng=random.Random(918)
    for _ in range(150):
        nums=[rng.randint(-4,4) for _ in range(rng.randrange(13))]
        target=rng.randint(-8,8)
        ordered=sorted(nums)
        item=lesson('binary-search',ordered,target)
        assert (item.result==-1 and target not in ordered) or (0<=item.result<len(ordered) and ordered[item.result]==target)
        checked_solution(item)
        item=lesson('two-sum',nums,target)
        pairs=[(i,j) for i in range(len(nums)) for j in range(i+1,len(nums)) if nums[i]+nums[j]==target]
        assert (item.result is None and not pairs) or (item.result is not None and tuple(item.result) in pairs)
        checked_solution(item)
        item=lesson('move-zeroes',nums)
        assert item.result==[n for n in nums if n!=0]+[0]*nums.count(0)
        assert item.inputs['values']==nums
        checked_solution(item)
        text=''.join(rng.choice('aAb 1') for _ in range(rng.randrange(13)))
        item=lesson('palindrome',text=text)
        assert item.result==(text==text[::-1]);checked_solution(item)
        item=lesson('character-frequency',text=text)
        assert item.result==dict(Counter(text));checked_solution(item)


@pytest.mark.parametrize('args', [('binary-search',[3,1]),('two-sum',[True]),('move-zeroes',list(range(13)))])
def test_invalid_arrays(args):
    with pytest.raises(ValueError):lesson(*args)


def test_browser_recipe_validation(tmp_path):
    config=tmp_path/'demo.json';(tmp_path/'index.html').write_text('<h1>Demo</h1>')
    data={'title':'demo','page':'index.html','steps':[{'title':'Start','narration':'This is a test narration.'}]}
    config.write_text(json.dumps(data));assert load_demo(config)['resolved_page'].startswith('file:')
    data['page']='../outside.html';config.write_text(json.dumps(data))
    with pytest.raises(ValueError):load_demo(config)
    data['page']='index.html';data['steps'][0]['actions']=[{'type':'evaluate','code':'alert(1)'}];config.write_text(json.dumps(data))
    with pytest.raises(ValueError):load_demo(config)


def test_sme_lesson_contract_and_visual_cues():
    from content_factory.channel.pedagogy import sme_review

    item = lesson('binary-search')
    review = sme_review(item)
    assert review['passed'] is True
    assert item.scenes[0].stage == 'hook'
    assert any(scene.stage == 'concept' for scene in item.scenes)
    assert any(scene.stage == 'code' for scene in item.scenes)
    assert any(scene.stage == 'edge-cases' for scene in item.scenes)
    trace = next(scene for scene in item.scenes if scene.stage == 'trace')
    assert {'LOW', 'MID', 'HIGH'} <= set(trace.pointers)
    assert trace.comparison
    assert trace.callout


def test_study_pacing_never_speeds_up_fast_voice():
    from content_factory.channel.pedagogy import adaptive_tempo, target_wpm

    text = ' '.join(['word'] * 150)
    tempo = adaptive_tempo(text=text, raw_seconds=45.0, stage='trace')
    assert 0.78 <= tempo <= 1.0
    assert target_wpm('trace') < 160
