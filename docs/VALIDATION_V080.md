# Validation — study engine v0.8.0

## Performed in the packaging environment

- Python source compilation: PASS
- Focused study-engine regression and v0.8 semantic-motion tests: PASS
- Non-YouTube automated suite: PASS (`157 passed, 1 deselected`)

Command used for the broader suite:

```bash
python -m pytest -q --ignore=tests/manual --ignore=tests/test_youtube_research.py
```

## Environment limitations

A raw `python -m pytest -q` cannot finish collection in this environment because
`yt_dlp` is not installed for the optional YouTube research tests. Install the
existing `research` extra to run them.

Manim is also not installed in this packaging environment, so the actual
1920x1080 narrated render has not been executed here. Rendering remains the final
acceptance test for motion quality, text readability, camera behavior and
narration synchronization.

Ruff and mypy are declared in the existing `dev` extra but are not installed in
this packaging environment, so no lint/type-check PASS is claimed here.

## Production-machine acceptance check

After installing `.[voice,channel,alignment,research,dev]`, run:

```bash
python -m pytest -q
python -m ruff check .
python -m mypy src
```

Then generate a representative study video and inspect multiple consecutive
moments inside the same scene as well as beginning/25%/50%/75%/end samples. Unit
tests alone are not evidence that a scene feels premium.
