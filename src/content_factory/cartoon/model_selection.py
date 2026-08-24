from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


_MODEL_KEYS = (
    "OLLAMA_MODEL",
    "CONTENT_FACTORY_LLM_MODEL",
    "LLM_MODEL",
    "CONTENT_FACTORY_CARTOON_FAST_MODEL",
)
_DEFAULT_MODEL = "llama3.2"


@dataclass(frozen=True)
class ModelSelection:
    model: str
    source: str
    key: str | None = None


def project_root_from_cli(cli_file: str | Path) -> Path:
    """Resolve project root from src/content_factory/cartoon/cli.py."""
    path = Path(cli_file).resolve()
    try:
        return path.parents[3]
    except IndexError:
        return Path.cwd().resolve()


def _clean_value(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in {"'", '"'}
    ):
        value = value[1:-1]
    else:
        # Allow simple inline comments in .env, but do not strip '#' when it
        # is part of a quoted value (quoted values were already handled).
        value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
    return value.strip()


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        values[key] = _clean_value(raw_value)
    return values


def _read_yaml_model(path: Path) -> str:
    """Read llm.model from local.yaml without requiring PyYAML."""
    if not path.is_file():
        return ""

    lines = path.read_text(encoding="utf-8").splitlines()
    llm_indent: int | None = None
    inside_llm = False

    for raw_line in lines:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip())
        stripped = raw_line.strip()

        if re.fullmatch(r"llm\s*:\s*", stripped):
            inside_llm = True
            llm_indent = indent
            continue

        if inside_llm and llm_indent is not None:
            if indent <= llm_indent:
                inside_llm = False
            else:
                match = re.match(r"model\s*:\s*(.+?)\s*$", stripped)
                if match:
                    return _clean_value(match.group(1))

    # Compatibility fallback for older files that placed model at top level.
    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            continue
        match = re.match(r"model\s*:\s*(.+?)\s*$", stripped)
        if match:
            return _clean_value(match.group(1))
    return ""


def resolve_model(
    *,
    project_root: Path,
    cli_model: str | None = None,
    environ: dict[str, str] | None = None,
    default_model: str = _DEFAULT_MODEL,
) -> ModelSelection:
    """Resolve Ollama model with deterministic precedence.

    Precedence:
      --model CLI argument
      > process/terminal environment
      > project .env
      > configs/local.yaml
      > built-in fallback

    `.env` is parsed directly instead of sourced by the shell. This means a
    terminal export is never overwritten by the file and arbitrary shell code
    in `.env` cannot execute.
    """
    if cli_model and cli_model.strip():
        return ModelSelection(cli_model.strip(), "cli_argument", "--model")

    env = os.environ if environ is None else environ
    for key in _MODEL_KEYS:
        value = str(env.get(key, "")).strip()
        if value:
            return ModelSelection(value, "terminal_env", key)

    dotenv_values = _read_dotenv(project_root / ".env")
    for key in _MODEL_KEYS:
        value = dotenv_values.get(key, "").strip()
        if value:
            return ModelSelection(value, ".env", key)

    yaml_value = _read_yaml_model(project_root / "configs" / "local.yaml")
    if yaml_value:
        return ModelSelection(yaml_value, "configs/local.yaml", "llm.model")

    return ModelSelection(default_model, "built_in_default", None)
