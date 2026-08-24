#!/usr/bin/env bash
set -uo pipefail

PROJECT="/Users/maa/agentic-content-factory"
MODEL="${OLLAMA_MODEL:-llama3.2}"

cd "$PROJECT" || exit 1
source .venv/bin/activate

mkdir -p logs artifacts

OLD_LOG_COUNT="$(find logs -maxdepth 1 -type f 2>/dev/null | wc -l | tr -d ' ')"
find logs -maxdepth 1 -type f -delete 2>/dev/null || true
echo "[LOG] Cleared ${OLD_LOG_COUNT:-0} old log file(s)."

STAMP="$(date +%Y%m%d-%H%M%S)"
FULL_LOG="$PROJECT/logs/content-factory-$STAMP.log"
SUMMARY_LOG="$PROJECT/logs/content-factory-$STAMP.summary.log"

RUNNER_PID=""

cleanup() {
  EXIT_CODE=$?
  trap - INT TERM EXIT

  if [[ -n "${RUNNER_PID:-}" ]] && kill -0 "$RUNNER_PID" 2>/dev/null; then
    echo
    echo "[STOP] Stopping content-factory..."
    pkill -P "$RUNNER_PID" 2>/dev/null || true
    kill -TERM "$RUNNER_PID" 2>/dev/null || true
    sleep 1
    pkill -P "$RUNNER_PID" 2>/dev/null || true
    kill -KILL "$RUNNER_PID" 2>/dev/null || true
  fi

  echo "[STOP] Releasing Ollama model: $MODEL"
  ollama stop "$MODEL" >/dev/null 2>&1 || true
  echo "[STOP] Cleanup complete."
  exit "$EXIT_CODE"
}

on_interrupt() {
  echo
  echo "[STOP] Ctrl+C received."
  exit 130
}

trap on_interrupt INT TERM
trap cleanup EXIT

export CONTENT_FACTORY_GEO="${CONTENT_FACTORY_GEO:-IN}"
export CONTENT_FACTORY_LANGUAGE="${CONTENT_FACTORY_LANGUAGE:-auto}"
export PYTHONUNBUFFERED=1

CMD=(content-factory --topic "__AUTO__")

echo "Mode: AUTO REAL-TRENDS"
echo "Google Trends region: $CONTENT_FACTORY_GEO"
echo "Language: $CONTENT_FACTORY_LANGUAGE"
echo "Artifacts: $PROJECT/artifacts/<topic>/<run-id>/"
echo "Full log: $FULL_LOG"
echo "Compact log: $SUMMARY_LOG"
echo
echo "Press Ctrl+C anytime for clean shutdown."
echo "------------------------------------------------------------"

(
  "${CMD[@]}" 2>&1 \
    | tee "$FULL_LOG" \
    | python -u -c '
import sys

important = (
    "[START]",
    "[DONE]",
    "[FAILED]",
    "[AUTO]",
    "[AUTO SOURCE]",
    "[TREND]",
    "[GROUNDING]",
    "[EVIDENCE]",
    "[AUTHENTICITY]",
    "[FACT]",
    "[SCRIPT]",
    "[THUMBNAIL]",
    "[PACKAGING]",
    "[RETENTION]",
    "[GROWTH]",
    "[PRODUCTION]",
    "[VOICE]",
    "[VISUAL QA]",
    "[VIDEO]",
    "[VISUAL ROUTE]",
    "[VISUAL]",
    "[ARTIFACT]",
    "[RESOURCE]",
    "[CACHE]",
    "[PERF]",
    "[MONETIZATION]",
    "[YOUTUBE]",
    "[AUTO APPROVAL]",
    "[APPROVAL]",
    "Run ID:",
    "Topic:",
    "Status:",
    "Failed Agent:",
    "Error:",
)

for line in sys.stdin:
    if any(token in line for token in important):
        print(line, end="", flush=True)
'
) &

RUNNER_PID=$!
wait "$RUNNER_PID"
STATUS=$?
RUNNER_PID=""

grep -E \
'^\[START\]|^\[DONE\]|^\[FAILED\]|^\[AUTO\]|^\[AUTO SOURCE\]|^\[TREND\]|^\[EVIDENCE\]|^\[GROUNDING\]|^\[AUTHENTICITY\]|^\[FACT\]|^\[SCRIPT\]|^\[GROWTH\]|^\[RETENTION\]|^\[PACKAGING\]|^\[THUMBNAIL\]|^\[PRODUCTION\]|^\[VOICE\]|^\[VISUAL QA\]|^\[VISUAL ROUTE\]|^\[THUMBNAIL\]|^\[VIDEO\]|^\[VISUAL\]|^\[ARTIFACT\]|^\[PERF\]|^\[CACHE\]|^\[RESOURCE\]|^\[MONETIZATION\]|^\[YOUTUBE\]|^\[AUTO APPROVAL\]|^\[APPROVAL\]|^Run ID:|^Topic:|^Status:|^Failed Agent:|^Error:' \
"$FULL_LOG" > "$SUMMARY_LOG" || true

if grep -q "^\[FACT\] BLOCKED" "$FULL_LOG" 2>/dev/null; then
  STATUS=2
  echo
  echo "[FAILED] Run blocked by factual safety gate."
fi

echo
echo "------------------------------------------------------------"
echo "Run exit code: $STATUS"
echo "Full log:"
echo "  $FULL_LOG"
echo "Compact summary:"
echo "  $SUMMARY_LOG"
echo
echo "Latest monetization report:"
bash "$PROJECT/scripts/show_monetization_report.sh" "$PROJECT" || true

exit "$STATUS"
