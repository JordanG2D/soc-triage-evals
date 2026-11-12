# Runtime compatibility

The runner targets Python 3.12. Its tested core versions are Inspect AI 0.3.287,
Model2Vec 0.10.0, OpenAI SDK 3.50.0, Anthropic SDK 2.8.0, and
agent-client-protocol 0.12.0. The SDKs are separate from Inspect's own retry layer;
both layers are configured for zero retries before live dispatch.

Inspect 0.3.287 imports Responses API types unavailable in OpenAI SDK 2.54.0 and
requires Anthropic SDK 2.0 or newer. Its ACP integration imports `acp.helpers`,
which is absent from agent-client-protocol 1.0.0; the compatible 0.12.0 release
is pinned even though this project does not start an ACP server.

The supplied Inspect runners explicitly select its native JSON log format.
In the tested Python 3.12 environment, a native `.eval` archive was written with
all 16 samples and a successful result, but reading the compressed archive through
Inspect's asynchronous reader hung. Native JSON logs completed and returned
normally. JSON logs retain Inspect's messages, tool events, sample metadata,
scores and usage; this format choice does not change agent behavior or scoring.
This is a tested environment limitation, not a claim about every Inspect install.
The native task integration uses Inspect's public synchronous `eval()` runner,
which supplies its own event-loop and filesystem lifecycle. Calling `eval_async()`
from a bare `asyncio.run()` loop stalled during initial log writing in the tested
environment, before model dispatch. The supported synchronous runner avoids that
integration issue without background evaluation threads.

In a restricted environment, direct Inspect's data and cache directories to
writable locations using its `platformdirs` configuration:

```sh
XDG_DATA_HOME="$PWD/.cache/xdg" XDG_CACHE_HOME="$PWD/.cache" \
  python scripts/run_inspect.py
```

Local embedding weights are acquired separately using the public model and exact
revision in `config/embedding.json`. Runtime loading verifies the three inference
asset checksums and never downloads missing weights. Tests use a small numeric
encoder only for vector-index arithmetic; the semantic integration check uses the
real acquired Model2Vec weights.
