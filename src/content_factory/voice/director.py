from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable


LANGUAGE_ALIASES = {
    "en": "en_US",
    "english": "en_US",
    "en_us": "en_US",
    "hi": "hi_IN",
    "hindi": "hi_IN",
    "हिंदी": "hi_IN",
    "हिन्दी": "hi_IN",
    "hinglish": "hi_IN",
    "es": "es_ES",
    "es_es": "es_ES",
    "es_mx": "es_MX",
    "spanish": "es_ES",
    "español": "es_ES",
    "fr": "fr_FR",
    "french": "fr_FR",
    "français": "fr_FR",
    "de": "de_DE",
    "german": "de_DE",
    "deutsch": "de_DE",
    "pt": "pt_BR",
    "pt_br": "pt_BR",
    "portuguese": "pt_BR",
    "português": "pt_BR",
    "id": "id_ID",
    "id_id": "id_ID",
    "indonesian": "id_ID",
    "bahasa indonesia": "id_ID",
    "it": "it_IT",
    "italian": "it_IT",
    "ja": "ja_JP",
    "japanese": "ja_JP",
    "日本語": "ja_JP",
    "ko": "ko_KR",
    "korean": "ko_KR",
    "한국어": "ko_KR",
    "zh": "zh_CN",
    "chinese": "zh_CN",
    "中文": "zh_CN",
    "ar": "ar_SA",
    "ar_sa": "ar_SA",
    "arabic": "ar_SA",
    "العربية": "ar_SA",
    "bn": "bn_BD",
    "bn_bd": "bn_BD",
    "bengali": "bn_BD",
    "বাংলা": "bn_BD",
    "ur": "ur_PK",
    "ur_pk": "ur_PK",
    "urdu": "ur_PK",
    "اردو": "ur_PK",
    "ta": "ta_IN",
    "tamil": "ta_IN",
    "தமிழ்": "ta_IN",
    "te": "te_IN",
    "telugu": "te_IN",
    "తెలుగు": "te_IN",
    "mr": "mr_IN",
    "marathi": "mr_IN",
    "मराठी": "mr_IN",
    "pa": "pa_IN",
    "punjabi": "pa_IN",
    "ਪੰਜਾਬੀ": "pa_IN",
    "gu": "gu_IN",
    "gujarati": "gu_IN",
    "ગુજરાતી": "gu_IN",
    "kn": "kn_IN",
    "kannada": "kn_IN",
    "ಕನ್ನಡ": "kn_IN",
    "ml": "ml_IN",
    "malayalam": "ml_IN",
    "മലയാളം": "ml_IN",
    "vi": "vi_VN",
    "vietnamese": "vi_VN",
    "tr": "tr_TR",
    "turkish": "tr_TR",
    "ru": "ru_RU",
    "russian": "ru_RU",
    "русский": "ru_RU",
}


@dataclass(frozen=True)
class VoiceProfile:
    locale: str
    role: str
    style: str
    character: str | None
    voice_key: str | None = None
    speaker_id: int | None = None
    backend: str | None = None
    length_scale: float = 1.0
    noise_scale: float = 0.667
    noise_w_scale: float = 0.8
    rate_wpm: int = 185


class VoiceDirector:
    """
    Decide language, speaker role and delivery.

    Narrator identity stays stable within one video.
    Character labels get stable character-specific voices.
    Scene emotion changes prosody, not randomly the speaker identity.
    """

    def __init__(
        self,
        *,
        language_override: str = "auto",
    ) -> None:
        self._language_override = language_override.strip().lower() or "auto"

    def profile_for(
        self,
        *,
        text: str,
        audience: str,
        topic: str,
        segment_index: int,
        total_segments: int,
    ) -> VoiceProfile:
        locale = self.detect_locale(
            text=text,
            audience=audience,
            topic=topic,
        )

        character, spoken_text = self.extract_character(text)

        if character:
            role = "character"
        else:
            role = "narrator"

        style = self._style_for(
            spoken_text,
            segment_index=segment_index,
            total_segments=total_segments,
        )

        speed = {
            "hook": 0.93,
            "energetic": 0.94,
            "curious": 0.98,
            "serious": 1.04,
            "warm": 1.02,
            "neutral": 1.00,
        }[style]

        rate_wpm = {
            "hook": 205,
            "energetic": 200,
            "curious": 185,
            "serious": 172,
            "warm": 176,
            "neutral": 185,
        }[style]

        # Slight variation only. Large noise shifts sound synthetic.
        noise = {
            "hook": 0.72,
            "energetic": 0.71,
            "curious": 0.68,
            "serious": 0.62,
            "warm": 0.65,
            "neutral": 0.667,
        }[style]

        width_noise = {
            "hook": 0.86,
            "energetic": 0.84,
            "curious": 0.82,
            "serious": 0.72,
            "warm": 0.76,
            "neutral": 0.80,
        }[style]

        return VoiceProfile(
            locale=locale,
            role=role,
            style=style,
            character=character,
            length_scale=speed,
            noise_scale=noise,
            noise_w_scale=width_noise,
            rate_wpm=rate_wpm,
        )

    def detect_locale(
        self,
        *,
        text: str,
        audience: str,
        topic: str,
    ) -> str:
        if self._language_override != "auto":
            return self._normalize_locale(
                self._language_override
            )

        combined_context = f"{audience} {topic}".lower()

        # Audience declaration wins because narration language should follow
        # intended viewers, not random English product/entity names.
        #
        # IMPORTANT:
        # Never use raw substring checks for short language codes such as
        # "en", "hi", "es". For example, "en" can accidentally match normal
        # words inside an audience description and incorrectly force English.
        audience_aliases = [
            (alias, locale)
            for alias, locale in LANGUAGE_ALIASES.items()
            if len(alias) > 2
        ]

        # Prefer longer/more-specific aliases first:
        # "hinglish" before "hi", "english" before "en", etc.
        audience_aliases.sort(
            key=lambda item: len(item[0]),
            reverse=True,
        )

        for alias, locale in audience_aliases:
            pattern = (
                r"(?<![\w])"
                + re.escape(alias)
                + r"(?![\w])"
            )
            if re.search(
                pattern,
                combined_context,
                flags=re.IGNORECASE,
            ):
                return locale

        # Locale/code declarations are allowed only as complete tokens.
        # Examples: "hi", "hi_IN", "es", "en_US".
        context_tokens = {
            token.lower()
            for token in re.findall(
                r"[A-Za-z]{2}(?:_[A-Za-z]{2})?",
                combined_context,
            )
        }

        for token in context_tokens:
            if token in LANGUAGE_ALIASES:
                return LANGUAGE_ALIASES[token]

        # Strong script-based Unicode detection.
        devanagari = len(
            re.findall(r"[\u0900-\u097F]", text)
        )
        arabic = len(
            re.findall(r"[\u0600-\u06FF]", text)
        )
        cyrillic = len(
            re.findall(r"[\u0400-\u04FF]", text)
        )
        japanese = len(
            re.findall(r"[\u3040-\u30FF]", text)
        )
        korean = len(
            re.findall(r"[\uAC00-\uD7AF]", text)
        )
        han = len(
            re.findall(r"[\u4E00-\u9FFF]", text)
        )

        visible_letters = max(
            1,
            len(re.findall(r"[^\W\d_]", text, flags=re.UNICODE)),
        )

        if devanagari / visible_letters >= 0.12:
            return "hi_IN"
        if arabic / visible_letters >= 0.12:
            return "ar_SA"
        if cyrillic / visible_letters >= 0.12:
            return "ru_RU"
        if japanese / visible_letters >= 0.08:
            return "ja_JP"
        if korean / visible_letters >= 0.08:
            return "ko_KR"
        if han / visible_letters >= 0.12:
            return "zh_CN"

        # Optional local language classifier if the user installs langid.
        try:
            import langid  # type: ignore

            code, confidence = langid.classify(text)
            if confidence > -20:
                family_map = {
                    "en": "en_US",
                    "hi": "hi_IN",
                    "es": "es_ES",
                    "fr": "fr_FR",
                    "de": "de_DE",
                    "pt": "pt_BR",
                    "it": "it_IT",
                    "ja": "ja_JP",
                    "ko": "ko_KR",
                    "zh": "zh_CN",
                    "ar": "ar_SA",
                    "ru": "ru_RU",
                }
                if code in family_map:
                    return family_map[code]
        except Exception:
            pass

        return "en_US"

    @staticmethod
    def extract_character(
        text: str,
    ) -> tuple[str | None, str]:
        """
        Recognize explicit dialogue labels:
          Maya: We should go now.
          अर्जुन: चलो शुरू करते हैं।

        We do not guess a real person's voice from an unlabeled quote.
        """
        match = re.match(
            r"^\s*([^\n:]{1,32})\s*:\s+(.+)$",
            text.strip(),
            flags=re.DOTALL,
        )

        if not match:
            return None, text.strip()

        label = match.group(1).strip()
        dialogue = match.group(2).strip()

        blocked = {
            "http",
            "https",
            "note",
            "example",
            "step",
            "section",
            "chapter",
        }

        if label.lower() in blocked:
            return None, text.strip()

        return label, dialogue

    @staticmethod
    def character_slot(
        character: str,
        slots: int,
    ) -> int:
        if slots <= 0:
            return 0

        digest = hashlib.sha256(
            character.lower().encode("utf-8")
        ).digest()

        return int.from_bytes(
            digest[:4],
            "big",
        ) % slots

    @staticmethod
    def _style_for(
        text: str,
        *,
        segment_index: int,
        total_segments: int,
    ) -> str:
        lower = text.lower()

        if segment_index <= 2:
            return "hook"

        if segment_index >= max(1, total_segments - 1):
            return "warm"

        if "?" in text:
            return "curious"

        if any(
            token in lower
            for token in (
                "breaking",
                "warning",
                "risk",
                "serious",
                "confirmed",
                "reported",
                "investigation",
                "security",
                "death",
                "injury",
            )
        ):
            return "serious"

        if any(
            token in lower
            for token in (
                "amazing",
                "exciting",
                "incredible",
                "wow",
                "big reveal",
                "game-changing",
                "game changing",
                "let's go",
                "चलो",
                "कमाल",
            )
        ):
            return "energetic"

        return "neutral"

    @staticmethod
    def _normalize_locale(
        value: str,
    ) -> str:
        normalized = value.strip().lower()

        if normalized in LANGUAGE_ALIASES:
            return LANGUAGE_ALIASES[normalized]

        if re.match(r"^[a-z]{2}_[A-Z]{2}$", value):
            return value

        if re.match(r"^[a-z]{2}_[a-z]{2}$", normalized):
            family, region = normalized.split("_", 1)
            return f"{family}_{region.upper()}"

        if re.match(r"^[a-z]{2}$", normalized):
            return LANGUAGE_ALIASES.get(
                normalized,
                f"{normalized}_{normalized.upper()}",
            )

        return "en_US"
