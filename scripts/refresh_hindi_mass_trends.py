#!/usr/bin/env python3
from __future__ import annotations
import os
from content_factory.cartoon.indian_comedy_v15 import current_safe_trend_themes, reset_trend_cache_for_tests

os.environ["CONTENT_FACTORY_HINDI_TRENDS"] = "auto"
reset_trend_cache_for_tests()
themes = current_safe_trend_themes()
print("Safe Indian comedy trend themes:")
for theme in themes:
    print(f"- {theme}")
