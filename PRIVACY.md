# Privacy

The question this file answers: **can you edit private photos here without anything
leaving the machine?**

Short answer: **yes, using the `/simple` page that this repo adds.** The longer answer
has two caveats, both about ComfyUI's *stock* UI rather than this one, and both closed by
the flags in `start.cmd`.

This is based on a static audit of ComfyUI at commit `99073836` — reading the code and
tracing call graphs, not packet capture. Where that distinction matters, it is stated.

## What was checked

**The generation path performs no network I/O.** `execution.py`, `comfy_execution/`, and
all 77 modules in `comfy_extras/` contain zero network primitives. The third-party
packages (`comfy_kitchen`, which provides `--use-ck-attention`, plus `comfy_aimdo` and
`comfy_angle`) contain no network code at all — only licence headers and reference URLs
in comments.

**ComfyUI opts out of upstream telemetry on your behalf**, setting
`HF_HUB_DISABLE_TELEMETRY=1` and `DO_NOT_TRACK=1` at startup (`main.py:41-42`). No
analytics SDK exists anywhere in the Python backend.

**The server binds loopback only.** `--listen 127.0.0.1` reaches aiohttp's `TCPSite`
directly; there is exactly one bind in the tree. No UPnP, no mDNS, no tunnelling, no
second port. It is not reachable from your LAN. ComfyUI additionally ships an origin-check
middleware that stops a malicious web page from driving your local server.

**The asset indexer and its database are local-only.** The asset system is off by default;
even enabled, `app/assets/` imports only `aiohttp.web` (server side) and has no client
capability. The SQLite DB lives under `user/` and is never uploaded.

**Nothing auto-downloads.** The frontend, workflow templates and docs are pre-installed
pip packages served from disk. The one GitHub fetch in `app/frontend_management.py` is
unreachable unless you pass a non-default `--front-end-version`.

**Weights load from `.safetensors` only** — a data-only format. No code executes on load,
which is why this setup never uses `.ckpt`/`.bin` pickles.

**This repo's page makes no external requests.** `custom_nodes/qwen_simple_ui.py` imports
only `torch`, `comfy.model_management`, `folder_paths`, `aiohttp.web` and
`server.PromptServer`. The page it serves loads no CDN script, no webfont, no external
stylesheet — it uses system fonts. Every request it makes is same-origin and relative:
`/models/...`, `/upload/image`, `/prompt`, `/history/...`, `/view`, and a WebSocket built
from `location.host`.

## The two caveats — both about the stock UI

These apply to `http://127.0.0.1:8188/` (ComfyUI's normal node-graph interface), **not** to
`/simple`. If you only ever open `/simple`, neither is reachable.

**1. Sentry is initialized with `enabled: true`** in the bundled frontend, unconditionally
— not gated by any build flag. What it does *not* do matters: session replay is off
(`replaysSessionSampleRate: 0`), so there is no DOM recording and no screenshots of your
images; performance tracing is off; and all default integrations are disabled, so there is
no global error handler or breadcrumb collection. Initialization alone transmits nothing.
What it *does* mean is that explicit `reportError()` calls in the frontend will reach
sentry.io. A handful of those are reachable on a local install (canvas layout failures,
graph serialisation mismatches, workflow load failures). None deliberately carries prompt
text or image data, but a workflow-load error forwards an arbitrary exception, and context
is serialised eight levels deep — so it cannot be *proven* that a filename or prompt
string could never appear in an error message. Low probability, non-zero, stock UI only.

**2. A version check contacts `api.comfy.org`** with your ComfyUI version, form factor and
locale when the stock UI loads. No image or prompt data. **`--disable-api-nodes` disables
it**, which is why `start.cmd` passes that flag.

Two further findings, both benign: Datadog RUM is bundled (248 KB) but **never
initialized** — nothing calls `init()` and no client token exists in any app chunk, so it
is dead weight rather than an egress path. Host telemetry is doubly gated behind a
feature flag that defaults false *and* an Electron desktop bridge absent in a browser, so
in a browser its code is never even fetched.

## What `start.cmd` does about it

```
--listen 127.0.0.1           loopback only
--disable-api-nodes          no cloud nodes; also kills the api.comfy.org version check
--disable-manager-ui         no node registry
--disable-all-custom-nodes   with the whitelist below
--whitelist-custom-nodes qwen_simple_ui.py
```

The whitelist is the forward-looking one. Custom nodes are the realistic vector by which
something that imports `requests` could appear later; this pins loading to the one node
in this repo. The value must include the `.py` extension — ComfyUI matches the raw
filename, and `qwen_simple_ui` without it silently loads nothing.

Verified after applying these: `/simple` responds, `EmptyQwenImage21Latent` and `KSampler`
are present, and the bundled cloud nodes return `{}`.

## Options not enabled by default

- **`--disable-metadata`** stops the prompt, seed and parent image being embedded in saved
  PNGs. That embedded provenance is useful — it is how you trace an edit chain or
  reproduce a result — so it is left on. Add the flag if you plan to share images widely
  and would rather not ship the prompt inside them. It is a local-privacy measure, not an
  egress one.
- **`HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`.** `huggingface_hub` is installed and
  not forced offline, so a future node — or a model-path typo that made `from_pretrained`
  fall through to a repo-id lookup — could reach the Hub. That would transmit a repo name,
  never your images. Setting both in `start.cmd` closes it; it would also break
  `download_models.py` until unset.
- **A per-process outbound firewall rule** on `<ComfyUI>\.venv\Scripts\python.exe`. This is
  the one control that upgrades every "found no evidence of egress" above into "verified",
  because static analysis cannot prove a negative about code it did not execute. Worth
  doing if the photos are genuinely sensitive.

## Bottom line

Use `/simple`. It loads no third-party code, so the stock-UI caveats are moot by
construction, and the backend it talks to makes no outbound requests during generation.
Your images stay in `<ComfyUI>/input/` and `<ComfyUI>/output/`, both gitignored, and
nothing in this repo ever uploads them.
