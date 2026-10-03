# LLM Runtime Resilience — v0.6.5

## Why this release exists

A 12-minute Study Mode lesson previously used four large structured script calls. On small-memory Apple Silicon, a local 3B/4B Ollama model could finish one chunk and then exceed both the primary and rescue timeout on the next chunk, aborting the entire workflow.

## New behavior

### Cloud primary

When `LLM_OLLAMA_FALLBACK=true`, Gemini/OpenAI/Anthropic/OpenAI-compatible remains the primary provider. Its own retry policy runs first. If a retryable runtime failure remains — 429/quota, retryable 5xx, timeout, or network failure — the provider switches once to Ollama. The failed request is retried locally and all later text-agent calls stay on Ollama.

Non-retryable request/schema/content errors do not silently switch providers.

### Local primary

Study Mode now generates six smaller semantic chunks instead of four large chunks. If a bounded chunk and its compact rescue both time out, the engine tries another installed Ollama model according to `CONTENT_FACTORY_OLLAMA_FAILOVER_ORDER`, then generates a much smaller micro-section. In Study Mode only, a final continuity-safe section prevents one slow local request from destroying the entire run.

### Ollama output bound

`CONTENT_FACTORY_OLLAMA_NUM_PREDICT` caps runaway local generations. Default: `2400` tokens globally; Study Script/Micro structured calls are internally capped at `1100`.

## Expected logs

Cloud runtime switch:

```text
[LLM RUNTIME FALLBACK] from=gemini:<model>, to=ollama:<model>; reason=...
```

Local model switch:

```text
[LLM LOCAL FAILOVER] from=qwen3:4b-instruct, to=llama3.2:latest; reason=...
```

Study script recovery:

```text
[SCRIPT V23] chunk 2/6 primary=FAIL (TimeoutError); compact rescue
[SCRIPT V23] chunk 2/6 failover=ACTIVE; trying micro-rescue
[SCRIPT V23] chunk 2/6 micro-rescue=PASS words=...
```
