# LLM Startup Fallback — v0.6.4

## Behavior

- `LLM_PROVIDER=auto` tries configured cloud providers first, then Ollama.
- `LLM_PROVIDER=gemini|openai|anthropic|compatible` remains the requested primary provider.
- If an explicitly selected cloud provider cannot be configured or prepared and `LLM_OLLAMA_FALLBACK=true`, startup falls back to local Ollama.
- The Ollama fallback always starts with `model=auto`; cloud model names are never reused for local fallback.
- Ollama inspects `/api/tags` and selects an installed Qwen/Llama model using the local preference order.
- Once `[LLM LOCK]` is printed, the selected provider/model is fixed for the rest of that workflow. There is no silent mid-run provider switching.

## Recommended .env

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=...
LLM_OLLAMA_FALLBACK=true
OLLAMA_MODEL=auto
```

For fully automatic startup selection:

```env
LLM_PROVIDER=auto
LLM_FALLBACK_ORDER=gemini,openai,anthropic,compatible,ollama
LLM_OLLAMA_FALLBACK=true
OLLAMA_MODEL=auto
```

## Logs

If the cloud provider starts successfully:

```text
[LLM LOCK] provider=gemini, model=<configured-model>, selection=explicit; ...
```

If startup falls back:

```text
[LLM FALLBACK] requested=gemini, fallback=ollama, model=qwen3:4b-instruct; reason=...
[LLM LOCK] provider=ollama, model=qwen3:4b-instruct, selection=fallback-to-ollama; ...
```
