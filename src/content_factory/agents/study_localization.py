from __future__ import annotations

from content_factory.agents.base import Agent
from content_factory.modes import is_study_mode
from content_factory.orchestration.state import WorkflowState


_LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "hi": "Hindi",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "ar": "Arabic",
    "id": "Indonesian",
    "bn": "Bengali",
    "ur": "Urdu",
}

_MARKET_NAMES = {
    "US": "United States",
    "GB": "United Kingdom",
    "IN": "India",
    "CA": "Canada",
    "AU": "Australia",
    "MX": "Mexico",
    "ES": "Spain",
    "BR": "Brazil",
    "FR": "France",
    "DE": "Germany",
    "JP": "Japan",
}


def normalize_locale(value: str | None) -> str:
    raw = (value or "").strip().replace("-", "_")
    if not raw:
        return ""
    parts = raw.split("_", 1)
    language = parts[0].lower()
    if len(parts) == 1 or not parts[1]:
        return language
    return f"{language}_{parts[1].upper()}"


def localization_fields(locale: str) -> dict[str, str]:
    normalized = normalize_locale(locale)
    if not normalized:
        return {}
    if "_" in normalized:
        language, geo = normalized.split("_", 1)
    else:
        language, geo = normalized, ""

    language_name = _LANGUAGE_NAMES.get(language, language)
    market_name = _MARKET_NAMES.get(geo, geo)

    if normalized == "en_US":
        language_name = "English (United States)"
    elif normalized == "en_GB":
        language_name = "English (United Kingdom)"
    elif normalized == "en_IN":
        language_name = "English (India)"

    return {
        "target_language": language,
        "target_language_name": language_name,
        "target_market_geo": geo,
        "target_market_name": market_name,
        "target_locale": normalized,
    }


class StudyLocalizationAgent(Agent):
    """Apply a deterministic narration locale after topic selection.

    Study videos default to U.S. English regardless of the market in which the
    topic was discovered. Users may override the locale explicitly. Current/
    news videos keep the market language selected by TrendResearchAgent unless
    the user explicitly requests a locale.
    """

    @property
    def name(self) -> str:
        return "Study Localization Agent"

    async def execute(self, state: WorkflowState) -> WorkflowState:
        requested = normalize_locale(
            str(state.metadata.get("requested_locale") or "")
        )

        source = "trend"
        locale = requested

        if requested:
            source = "user"
        elif is_study_mode(state):
            locale = "en_US"
            source = "study-default"

        if locale:
            fields = localization_fields(locale)
            state.metadata.update(fields)
            state.metadata["localization_source"] = source

            if locale == "en_US":
                state.metadata["localization_style"] = "American English"
            else:
                state.metadata["localization_style"] = fields.get(
                    "target_language_name", locale
                )

            print(
                "[LOCALIZATION] "
                f"source={source}, "
                f"language={fields.get('target_language_name', '-')}, "
                f"locale={fields.get('target_locale', '-')}, "
                f"market={fields.get('target_market_geo', '-') or '-'}"
            )

        return state
