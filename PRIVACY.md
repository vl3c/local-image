# Privacy

The question this file answers: **can you edit private photos here without anything
leaving the machine?**

Short answer: **yes, using the `/simple` page this repo adds.** The caveats below are
about ComfyUI's *stock* interface, not this one, and the flags in `start.cmd` close them.

This is based on a static audit — reading code and tracing call graphs, not packet
capture — of ComfyUI at commit **`99073836`**, which is the revision `install.ps1` pins by
default. If you install with `-Commit latest` you get whatever master is that day, and
none of the specific findings below are guaranteed to still describe it.

## What was checked

**The generation path performs no network I/O.** `execution.py`, `comfy_execution/`, and
all 139 node modules in `comfy_extras/` contain no outbound network calls. The
third-party packages (`comfy_kitchen`, which provides `--use-ck-attention`, plus
`comfy_aimdo` and `comfy_angle`) contain no network code at all.

One dormant exception, for completeness: `comfy/k_diffusion/utils.py:42` contains a
`urlopen` inside a `download_file` helper that has no callers anywhere in the tree. It
is dead code, but it exists.

**The server binds loopback only.** There is exactly one socket bind in the tree, and
`--listen 127.0.0.1` reaches it directly. No UPnP, no mDNS, no tunnelling, no second
port. Not reachable from your LAN. (`127.0.0.1` is also ComfyUI's default — passing it
explicitly is documentation, not a fix.) ComfyUI additionally ships an origin-check
middleware that stops a malicious web page from driving your local server.

**`--disable-api-nodes` installs a Content-Security-Policy header** on every response:

```
connect-src 'self' data:
```

This is the strongest single control here, and it is a browser-level one. It means a page
served by ComfyUI *cannot* open a connection to any third-party host, regardless of what
its JavaScript tries to do. Verified live with `curl -D -` against a running server.

**The asset indexer and its database are local-only.** The asset system is off by
default; even enabled, `app/assets/` has no HTTP client capability. The SQLite DB lives
under `user/` and is never uploaded.

**Nothing auto-downloads.** The frontend, workflow templates and docs are pre-installed
pip packages served from disk. The one GitHub fetch in `app/frontend_management.py` is
unreachable unless you pass a non-default `--front-end-version`.

**Weights load from `.safetensors` only** — a data-only format, so no code executes on
load. This setup never uses `.ckpt` or `.bin` pickles.

**This repo's page makes no external requests.** `custom_nodes/qwen_simple_ui.py` imports
only `torch`, `comfy.model_management`, `folder_paths`, `aiohttp.web` and
`server.PromptServer`. The page it serves loads no CDN script, no webfont, no external
stylesheet — it uses system fonts. Every request is same-origin and relative:
`/models/...`, `/upload/image`, `/prompt`, `/history/...`, `/view`, plus a WebSocket built
from `location.host`.

**`compare.html` makes no requests beyond the images next to it.** `scripts/compare.py`
writes it with inline styles and script, system fonts, and relative links to the images in the
same folder (and to the image an edit started from). Opened from disk, it talks to nothing.

One correction worth recording, because it is easy to repeat: ComfyUI sets
`HF_HUB_DISABLE_TELEMETRY=1` and `DO_NOT_TRACK=1` at startup, but its own source comments
those as having no effect on core ComfyUI — they exist for the benefit of custom nodes.
They are a courtesy to the ecosystem, not a control on ComfyUI itself.

## The two caveats — both in the stock UI

These apply to `http://127.0.0.1:8188/` (ComfyUI's node-graph interface), **not** to
`/simple`. If you only open `/simple`, neither is reachable.

**1. Sentry is initialized with `enabled: true`** in the bundled frontend,
unconditionally. What it does *not* do matters: session replay is off, so there is no DOM
recording and no screenshots of your images; performance tracing is off; and all default
integrations are disabled, so there is no global error hook or breadcrumb collection.
Initialization alone transmits nothing. What it *does* mean is that explicit
`reportError()` calls could reach sentry.io — and since error context is serialised
several levels deep, it cannot be *proven* that a filename could never appear in a message.

However: with `--disable-api-nodes` set, the CSP `connect-src 'self'` header above means
**the browser refuses the connection anyway**. Belt and braces.

**2. A version check contacts `api.comfy.org`** with your ComfyUI version, form factor and
locale when the stock UI loads. No image or prompt data. **`--disable-api-nodes` disables
it**, which is one more reason `start.cmd` passes that flag.

Two further findings, both benign: Datadog RUM is bundled (~250 KB) but **never
initialized** — nothing calls `init()` and no client token exists in any app chunk. Host
telemetry is double-gated behind a feature flag defaulting false *and* an Electron desktop
bridge absent in browsers, so in a browser its code is never even fetched.

## What `start.cmd` does about it

```
--listen 127.0.0.1           loopback only (also the default)
--disable-api-nodes          THE important one: no cloud nodes, no api.comfy.org
                             version check, and adds connect-src 'self' CSP
--disable-manager-ui         defensive only - see note
--disable-all-custom-nodes   with the whitelist below
--whitelist-custom-nodes qwen_simple_ui.py
```

Two honest notes on that list. `--disable-manager-ui` is effectively a **no-op** in this
install: the manager only activates with `--enable-manager`, and the `comfyui_manager`
package is not installed at all. It is there so the flag survives if someone later
installs it — not because it is closing anything today. And `--listen 127.0.0.1` restates
the default rather than changing behaviour.

The whitelist is the forward-looking control. Custom nodes are the realistic vector by
which something that imports `requests` could appear later; this pins loading to the one
node in this repo. The value must include the `.py` extension — ComfyUI compares the raw
directory entry, so `qwen_simple_ui` without it silently loads nothing and `/simple` 404s.

Verified after applying these: `/simple` responds, `EmptyQwenImage21Latent` and `KSampler`
are present, the bundled cloud nodes return `{}`, and the CSP header is on every response.

## Options not enabled by default

- **`--disable-metadata`** stops the prompt, seed and parent image being embedded in saved
  PNGs. That provenance is useful — it is how you reproduce a result or trace an edit
  chain — so it stays on. Add the flag if you share images widely and would rather not
  ship the prompt inside them. Local privacy, not egress.
- **`HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`.** `huggingface_hub` is installed and
  not forced offline, so a future custom node — or a model-path typo making
  `from_pretrained` fall through to a repo-id lookup — could reach the Hub. That would
  transmit a repo name, never your images. Setting both closes it. (It would *not* affect
  `scripts/download_models.py`, which uses plain `urllib` and ignores those variables.)
- **A per-process outbound firewall rule** on `<ComfyUI>\.venv\Scripts\python.exe`. This is
  the one control that upgrades every "found no evidence of egress" here into "verified",
  because static analysis cannot prove a negative about code it did not execute. Worth
  doing if the photos are genuinely sensitive.

## Bottom line

Use `/simple`. It loads no third-party code, so the stock-UI caveats are moot by
construction, and the backend it talks to makes no outbound requests during generation.
Your images stay in `<ComfyUI>/input/` and `<ComfyUI>/output/`, both gitignored, and
nothing in this repo ever uploads them.
