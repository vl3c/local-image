# local-image

A private, fully local image generator and editor. Type a prompt, press Generate.

It runs **Qwen-Image-2.1** on your own GPU through ComfyUI, but replaces ComfyUI's
node-graph interface with a single page that is just a prompt box and a button. No
accounts, no cloud, no node wiring. Your prompts and images never leave the machine.

```powershell
git clone https://github.com/vl3c/local-image.git
cd local-image
powershell -ExecutionPolicy Bypass -File .\install.ps1   # ~30 GB, mostly weights
.\start.cmd                                              # opens the page for you
```

> **Before you use it:** the code here is MIT, but the model it downloads is licensed for
> **research and evaluation only**. Trying it out and testing it are fine; client work,
> selling images or using them in a product or monetised content needs a separate
> commercial licence from Qwen. See [Licensing](#licensing).

**Contents** — [What it does](#what-it-does) · [Requirements](#requirements) ·
[Install](#install) · [Using it](#using-it) · [Writing prompts](#writing-prompts) ·
[Improving a draft](#improving-a-draft) · [Speed](#speed) ·
[Troubleshooting](#troubleshooting) · [Privacy](#privacy) · [Licensing](#licensing) ·
[Repo layout](#repo-layout) · [Notes for anyone extending this](#notes-for-anyone-extending-this)

---

## What it does

- **Generate** from text, at eight preset aspect ratios up to 2K.
- **Edit** by describing a change — up to 10 reference images at once.
- **Iterate** — every result has an *Edit this* button, so edits chain.
- **Preview → commit** — a fast 20-step draft, then re-render the keeper at full quality.
- **Enhance** — refine an image's actual pixels when the composition must not move.
- **Exact delivery sizes** (command line) — `--fit 1920x1080` renders near the target and
  scales and crops to exactly that.
- **Cut-outs** (command line) — one object on a real transparent background, returned as a
  transparent PNG, a clean mask and its outline as SVG and JSON, ready to trace or composite.

Qwen-Image-2.1 is unusually good at rendering *text inside images* — shop signs, labels,
handwriting, dense captions. That is the main reason to run this one locally rather than
reaching for whatever is in a browser tab.

## Requirements

| | |
|---|---|
| OS | Windows 10 / 11 |
| GPU | NVIDIA, with a current driver (the default CUDA 13 build wants 580 or newer; `-CudaIndex` covers older ones). 16 GB VRAM is comfortable; 12 GB works but streams weights heavily |
| Disk | **~30 GB free** (plus ~5 GB of pip cache elsewhere) |
| RAM | 32 GB |
| Software | Python 3.13 (via the `py` launcher) and Git, both on PATH |

No CUDA toolkit needed — the PyTorch wheels bundle what they use. You just need a current
NVIDIA driver.

The full-precision (bf16) weights would need ~33 GB of system RAM to offload and are *not*
used here. This setup runs int8-quantized weights throughout, which fit in VRAM and are
near-lossless.

## Install

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

`-ExecutionPolicy Bypass` is needed because stock Windows refuses to run downloaded
scripts. If you would rather not type it every time, run `Unblock-File .\install.ps1` once
and then just `.\install.ps1`.

Re-running is safe: finished steps are skipped and downloads resume where they stopped.
Works on both Windows PowerShell 5.1 (the built-in one) and PowerShell 7.

### What it puts on your disk

Everything lands **inside the repo folder, in `ComfyUI/`**, which is gitignored. Nothing is
installed system-wide and your global Python is untouched.

| What | Where | Size |
|---|---|---|
| ComfyUI (cloned from GitHub) | `ComfyUI/` | ~100 MB |
| Private virtualenv | `ComfyUI/.venv/` | — |
| PyTorch + CUDA runtime | `ComfyUI/.venv/` | ~4 GB |
| ComfyUI's Python dependencies | `ComfyUI/.venv/` | ~1 GB |
| `triton-windows` (optional) | `ComfyUI/.venv/` | ~250 MB |
| This repo's UI node, copied in | `ComfyUI/custom_nodes/` | 22 KB |
| Model weights (below) | `ComfyUI/models/` | ~24 GB |

One thing that lands *outside* the repo: pip's wheel cache, roughly 5 GB, goes to
`%LOCALAPPDATA%\pip\Cache`. Pass `-NoPipCache` to skip it, at the cost of re-downloading
if you ever reinstall.

### What it downloads

Weights come from [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1).
**Every file is SHA256-verified** against checksums pinned in [`models.json`](models.json),
and the manifest pins a repo *revision* rather than `main`, so an upstream re-upload fails
loudly instead of silently changing what you get. No HuggingFace account or token needed.

| File | Size | What it is |
|---|---|---|
| `qwen_image_2.1_int8_convrot.safetensors` | 7.3 GB | The 7B diffusion transformer — makes the image |
| `qwen3vl_8b_int8_convrot.safetensors` | 9.4 GB | Qwen3-VL-8B text encoder — reads your prompt |
| `qwen_image_2.1_vae_bf16.safetensors` | 0.7 GB | Decodes latents to pixels |
| `qwen3vl_8b_w4a8.safetensors` | 6.3 GB | Optional smaller encoder (`-AllModels`) |

All are `.safetensors` — a data-only format, so **no code executes when weights load**.
This setup never touches `.ckpt` or `.bin` pickle formats.

During install, traffic goes to `github.com` (the ComfyUI clone), `pypi.org` /
`files.pythonhosted.org` / `download.pytorch.org` (packages), and `huggingface.co`, which
redirects weight downloads to its CDN. After that, see [Privacy](#privacy).

To verify your weights at any time without downloading anything:

```powershell
.\ComfyUI\.venv\Scripts\python.exe scripts\download_models.py --verify --all
```

### Install options

```powershell
.\install.ps1 -ComfyUI D:\ai\ComfyUI   # put the heavy parts on another drive
.\install.ps1 -SkipModels              # code only; fetch the 24 GB later
.\install.ps1 -AllModels               # also grab the optional smaller encoder
.\install.ps1 -CudaIndex cu129         # older driver (or cu128)
.\install.ps1 -PythonVersion 3.12      # if you do not have 3.13
.\install.ps1 -NoTriton                # skip the optional package
.\install.ps1 -NoPipCache              # do not leave ~5 GB in the pip cache
.\install.ps1 -Commit latest           # track ComfyUI master (see below)
.\install.ps1 -SyncNodeOnly            # re-copy the UI node after editing it
```

**About `-Commit`.** By default the installer checks out the exact ComfyUI revision that
[PRIVACY.md](PRIVACY.md)'s audit was performed against, so what you get matches what was
reviewed. `-Commit latest` tracks master instead — newer, but the audit's specific findings
no longer necessarily describe your copy.

## Using it

**`.\start.cmd`** starts the server and opens `http://127.0.0.1:8188/simple` in your
default browser once it is actually ready. (A minimized helper window polls the server and
closes itself; a cold start takes about half a minute because ~17 GB of weights have to
load, which is why it waits rather than guessing a delay.)

Leave the server's window open while you use it. It shows the address, one line per
image job and any errors; everything ComfyUI prints goes to `logs\server.log`, timestamped, with
the previous run kept as `logs\server.previous.log` (`scripts\logtee.py` does this). `logs\` is
gitignored.

If you installed ComfyUI elsewhere, pass the path: `.\start.cmd D:\ai\ComfyUI` (and the same
to `.\stop.cmd`).

The server listens on `127.0.0.1:8188`, ComfyUI's usual port. If another ComfyUI already uses
it, set `LOCAL_IMAGE_PORT` (for example `set LOCAL_IMAGE_PORT=8189`) before `start.cmd`;
`scripts\generate.py` reads the same variable.

### The page

| Control | What it does |
|---|---|
| **Prompt** | What you want. `Ctrl+Enter` also submits. |
| **Reference images** | Optional. Click, drag, or **paste from the clipboard**. Up to 10. Any attached reference switches the page to editing mode. |
| **Size** | Eight presets. Replaced by **Output scale** when editing, because the output shape comes from your first reference. |
| **Quality** | Preview (20 steps) or Full (40). See [Improving a draft](#improving-a-draft). |
| **Seed** | Blank for random. Paste one back to reproduce an image exactly. |
| **How many** | 1, 2 or 4 at once. |
| **Advanced** | Model and text-encoder pickers. Safe to ignore. |

Results stack newest-first with **Full quality**, **Enhance**, **Edit this** and
**Download** buttons.

### Stopping it

Close the `start.cmd` console window. That is the whole answer.

If there is no window to close — it was started with `--here` by a script, or
the window was closed without the process dying — run **`.\stop.cmd`**. It reports what it stopped and
how much VRAM came back. It only stops the server started from *this* install: it matches the
path of this install's `main.py`, so another ComfyUI or any other Python program you run is left
alone. It exits 0 when the server is stopped (or wasn't running) and 1 if anything survived.

To give the GPU back for a while without stopping the server, ask it to unload the models:
`curl -X POST -H "Content-Type: application/json" -d "{\"unload_models\": true, \"free_memory\": true}" http://127.0.0.1:8188/free`.
That leaves about 0.4 GB in use; the next image reloads them from system RAM, about 8 s extra
on the test machine.

ComfyUI re-executes itself at startup, so a running server is always **two** python
processes: a small launcher and the real one holding the VRAM. Ending only one in Task
Manager leaves the other resident — the usual way people end up with VRAM they cannot
account for.

### Command line

```bash
python scripts/generate.py "a neon sign reading OPEN LATE, rainy night"
python scripts/generate.py "a lighthouse at dawn" --size 1664x928 --seed 42 --preview
python scripts/generate.py "make the sky stormy" --edit photo.png
python scripts/generate.py "..." --enhance output/qwen21_00003_.png
python scripts/generate.py "a lighthouse" --wait 120 --out renders
python scripts/generate.py "a foggy city at night" --fit 1920x1080 --out plates
python scripts/generate.py "a raised fist" --cutout --size 1024x1024 --out shapes
```

Needs the server running; `--wait 120` waits for one that is still starting. Sizes must be
multiples of 16; `--size` is ignored when editing (use `--scale`). `--out DIR` copies the
results into `DIR` with the embedded prompt stripped (`--keep-metadata` keeps it), and
`--timeout` stops waiting for a result (default 900 s). `python scripts/generate.py -h` lists
everything.

**Exact sizes for video.** `--fit 1920x1080` delivers exactly 1920×1080, whatever the
numbers. It renders at the target's aspect rounded up to multiples of 16 (1920×1088 here,
so only 4 rows come off top and bottom), or near it within 1–2.4 megapixels for very small
or very large targets, then scales and centre-crops to cover. It works after `--edit` and
`--enhance` too. The result is plain RGB: the model's VAE outputs an alpha channel even for
opaque images, and it dips slightly below fully opaque in places, which can show as faint
see-through specks once composited. `--rgb` drops it without changing the size.

**Cut-outs and silhouettes.** Qwen-Image-2.1 decodes RGBA, and it draws a *real* transparent
background when the prompt asks for "a fully transparent background, PNG with alpha channel"
(16 of 16 seeds in testing; plain "on a transparent background" was ignored). `--cutout` adds
that phrasing to your prompt, for one object as a solid black silhouette (`--cutout object`
keeps its own colours, and works for white objects too), keeps the alpha channel, then runs
`scripts/cutout.py` on each result and writes, next to it:

| File | What it is |
|---|---|
| `NAME_cutout.png` | the image with the background transparent, soft edge |
| `NAME_mask.png` | white object on black, hard edge |
| `NAME_contour.svg` | the outline as one even-odd path, on the same pixel grid as the PNG |
| `NAME_contour.json` | the same outline as point lists, outer loops and holes marked |
| `NAME_check.png` | the cut-out over a checkerboard with the outline drawn in: look at this one |

On a transparent render the cut follows the alpha and keeps the model's soft edge; the
junk colour a render leaves under transparent pixels is replaced, so nothing bleeds into the
edge when the PNG is resized. On an ordinary image with a plain background, the background
colour is read from the image border and the threshold is chosen automatically, light or
dark. Cleanup drops specks, fills pinholes and smooths the edge; separate parts that are big
enough all stay. To adjust, run
`cutout.py` again on the same image with ComfyUI's Python, which has the libraries it needs:

```powershell
.\ComfyUI\.venv\Scripts\python.exe scripts\cutout.py shapes\qwen21_00012_.png --out shapes --open 17
```

| Option | Effect |
|---|---|
| `--open R` | removes anything thinner than about 2R px: a rod through a fist, wires, hairs |
| `--close R` | bridges gaps narrower than about 2R px |
| `--keep N` | only the N largest parts (default: every part over 1% of the largest) |
| `--fill-holes F` | fill holes up to F of the object's area (default 0.002, pinholes only; 0 keeps all, 1 fills all) |
| `--smooth S` | edge blur in px (default 1) |
| `--hard` | hard-edged alpha |

It warns when the object touches the frame (probably cropped), when the background isn't
plain, and when `--keep` drops a large part. It works on any image you already have, too.

The server always opens in its own console window titled "local-image ComfyUI server - close this
window to stop it", and `start.cmd` returns at once, so a server is never running out of sight;
closing the window stops it. `.\start.cmd --no-browser` does the same without opening the page
(that's how agents start it), and `.\start.cmd --here` runs it in the current console instead, for
scripts that manage the process themselves.

### As a Claude Code skill

`SKILL.md` lets Claude Code drive all of this: it generates, looks at each result, iterates,
and hands you the keepers. To install it, link the repo into your skills folder, from the
repo root:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
cmd /c mklink /J "$env:USERPROFILE\.claude\skills\local-image" (Get-Location).Path
```

### Where your images go

Generated images go to `ComfyUI/output/`, references you upload to `ComfyUI/input/`.
**Both directories are gitignored entirely** — every file, every format — so nothing you
make or feed in can be committed by accident.

Nothing is auto-deleted. Each PNG embeds its prompt, seed and parent image, so you can
reproduce any result or trace an edit chain backwards. That metadata survives the original
file but is stripped by anything that re-encodes (messaging apps, screenshots, JPEG
conversion), so keep the originals if provenance matters. You can turn it off — see
PRIVACY.md.

## Writing prompts

**Put text you want rendered in quotes.** `a shop sign that reads "THE INKWELL" in gold
serif lettering` works far better than describing it loosely. This model will render
multiple distinct pieces of text in one image — a sign *and* a chalkboard *and* a footer
line — and usually get all of them right.

**There is no negative prompt, by design.** The model is sampled guidance-free, so a
negative prompt could not do anything (details in
[Notes](#notes-for-anyone-extending-this)). Steer with positive phrasing instead: write
"an empty street at dawn" rather than trying to negate "people".

**When editing, name the element you mean.** If a scene contains several pieces of text,
"change the sign" is ambiguous and the model may pick the wrong one — in testing it
relettered a chalkboard instead of the hanging shop sign above it. "The hanging wooden sign
above the door" fixes it. The same goes for objects in a busy frame.

**Identity holds up well across edits.** Repainting a storefront, changing weather, or
swapping a material generally preserves faces, products, lettering style and lighting.
Chain edits freely with *Edit this*.

## Improving a draft

Two buttons, two genuinely different operations:

| | **Full quality** | **Enhance** |
|---|---|---|
| starts from | the seed, fresh noise | the image's actual pixels |
| composition | usually preserved — **can drift** | cannot drift |
| detail gained | a full 40-step render | less, but safe |
| offered on | previews only | every result |

Re-running a seed at a higher step count changes how the sampler discretizes the same
trajectory. Usually both land on the same image; when a composition is underdetermined the
coarse path can settle somewhere else entirely. It happened once in a handful of test
prompts here — uncommon, but not rare enough to ignore, so treat a preview as a strong
indication rather than a contract.

*Enhance* re-encodes the pixels you are looking at and denoises only partway (0.45), so it
physically cannot reframe the shot. Use it when you like what you are looking at and just
want it sharper.

## Speed

Measured on an RTX 5080 (16 GB), int8 weights, Comfy Kitchen attention, warm:

| Resolution | Preview (20 steps) | Full (40 steps) |
|---|---|---|
| 1024² | ~5.5s | ~9.7s |
| 1328² | ~11s | ~21s |
| 1664² | ~20s | ~40s |
| 2048² | ~40s | ~79s |

Editing costs modestly more than a generation at the same scale — measured ~11.5s against
~9.5s at 1024 — because the reference image has to be VAE-encoded and its latents
prepended to the sequence. Raising **Output scale** when editing costs much more than that,
since it lengthens both the output and the reference. The first generation after starting
the server is far slower than any figure here; that is the one-off model load.

Peak VRAM sits near 15.5 GB of 16.3 GB at every resolution. That is ComfyUI's memory
manager deliberately filling the card and streaming weights. Expected, not a problem.

**What helped, and what didn't.** `--use-ck-attention` was worth **−15%** (11.4s → 9.7s at
1024²); `start.cmd` turns it on whenever the GPU supports it. Sage attention was equivalent. Triton alone made no measurable
difference. The int8 text encoder showed **no adherence gain** over the 4-bit one — both
handled counting, dense text and spatial negation correctly on identical seeds — so it is
the default only because it costs ~0.3s. If VRAM is tight, install with `-AllModels` and
pick `qwen3vl_8b_w4a8` from the page's Advanced section; it gave up nothing in testing.

## Troubleshooting

**Install fails with "Python 3.13 not found".** Run `py --list` to see what you have, then
pass `-PythonVersion` with one of those, or install 3.13 from python.org with the launcher
option ticked.

**Install says "torch cannot see CUDA".** The wheel index does not match your driver. Check
`nvidia-smi`, then delete `ComfyUI\.venv` and re-run with `-CudaIndex cu129` (or `cu128`).
Left unfixed, generation runs on CPU and takes many minutes per image.

**PowerShell refuses to run the script.** Use
`powershell -ExecutionPolicy Bypass -File .\install.ps1`, or `Unblock-File .\install.ps1`.

**`/simple` returns 404.** The custom-node whitelist in `start.cmd` must name the file
*with* its extension — `qwen_simple_ui.py`. Without it nothing loads and the route does not
exist.

**Port 8188 already in use.** Most likely an earlier server that lost its window: run
`.\stop.cmd`. If it says nothing is running, another program (often a separate ComfyUI) has
the port; set `LOCAL_IMAGE_PORT` to another one as described in [Using it](#using-it).

**The server window says Comfy Kitchen attention is not available.** Harmless: `start.cmd`
checks whether your GPU supports that faster attention kernel and leaves it off if not.
Generation is about 15% slower than the timings below; nothing else changes.

**Out of memory, or generation crawls.** This stack wants ~15.5 GB of 16.3 GB. Another
process holding VRAM — a local LLM, a game, a second ComfyUI — will not coexist. Stop it
first. `nvidia-smi` shows what is holding what.

**The browser did not open.** Only the helper failed; the server is fine. Browse to
`http://127.0.0.1:8188/simple` yourself.

**Everything suddenly re-downloads on reinstall.** You passed `-NoPipCache`, or the pip
cache was cleared. Harmless, just slow.

## Privacy

The `/simple` page and the generation backend make no outbound requests. `start.cmd` binds
**loopback only** and disables the cloud nodes ComfyUI bundles, its node registry, and all
custom nodes except this repo's. That last flag also makes ComfyUI serve a
`connect-src 'self'` content-security policy, so a page served here **cannot** reach a third
party even if its JavaScript tried.

[PRIVACY.md](PRIVACY.md) documents the full audit: what was verified, two findings about
ComfyUI's *stock* node-graph interface that `/simple` avoids entirely, and the limits of
what a static audit can prove.

Before pushing to any public remote:

```bash
python scripts/check_repo_safe.py            # working tree
python scripts/check_repo_safe.py --history  # every past commit too
```

It fails on large files, weights, images, local paths, email addresses, hostnames, IP
addresses and credential-shaped strings.

## Licensing

Code here is **MIT** ([LICENSE](LICENSE)).

**The weights are not, and the grant is narrower than it sounds.** Qwen-Image-2.1 is
released under the Qwen Research License, which permits use **"for research or evaluation
purposes only"**. That is narrower than "non-commercial" usually implies. This repo
redistributes no weights — it downloads them from HuggingFace, where that licence applies.

What that means in practice (a plain reading, not legal advice):

| | |
|---|---|
| **Fine** | Trying the model, testing and comparing it, research, learning how it works |
| **Needs a commercial licence from Qwen** | Client or paid work, selling images, using them in a product, an ad or monetised content |
| **Unclear** | Personal creative projects you publish, even unpaid: neither clearly research nor clearly commercial |

The licence limits how you *use the model*, so what is restricted is generating for a
commercial purpose. It does not separately claim ownership of the images.
[LICENSE-MODELS.md](LICENSE-MODELS.md) quotes the relevant clauses; read it before relying
on anything you generate.

ComfyUI is GPL-3.0 and is cloned at install time, not vendored here.

## Repo layout

Only first-party source is tracked. Everything the installer creates is ignored, so
`git status` stays clean after a full install.

```
install.ps1                     one-shot setup; re-runnable
start.cmd                       run the server in its own window, open the page
stop.cmd                        stop it when there is no window to close (scripts/stop.ps1)
SKILL.md                        Claude Code skill: generate, check and iterate
models.json                     weight manifest: URLs, sizes, SHA256
custom_nodes/qwen_simple_ui.py  the /simple page and one helper node
scripts/generate.py             CLI: generate, edit, enhance, --fit, --cutout
scripts/cutout.py               cut an object out along its alpha or a plain background: mask, PNG, outline
scripts/logtee.py               log the server's output; show only what matters in its window
scripts/download_models.py      resumable, checksum-verified downloader
scripts/check_repo_safe.py      pre-publish guard
PRIVACY.md                      network-egress audit
LICENSE-MODELS.md               what the weights actually permit
tests/                          cutout.py tests: ComfyUI's python -m unittest discover tests
```

## Notes for anyone extending this

Four things that cost real debugging time.

**1. Reference image slots are namespaced.** `TextEncodeQwenImage21` uses ComfyUI
"autogrow" inputs, so in the API workflow format the key is `images.image_1`, not
`image_1`. The plain name fails with `unexpected keyword argument 'image_1'`.

**2. Negative prompts cannot work here.** The model samples guidance-free at `cfg 1.0`, and
ComfyUI drops the unconditional branch entirely at that value — see the
`disable_cfg1_optimization` check in `comfy/samplers.py`. Your text would be encoded and
then discarded before a single forward pass. That is why the page has no negative prompt
box.

**3. Editing needs the VAE wired into the text-encode node.** Without it the references are
only *seen* by the text encoder rather than becoming reference latents, which gives you
"inspired by" instead of a real edit.

**4. Windows PowerShell 5.1 has two traps that PowerShell 7 does not.** Both bit this
installer, and neither shows up if you only ever test on pwsh 7:

- With `$ErrorActionPreference = 'Stop'`, **any** stderr output from a native command
  becomes a terminating error. Probing for a missing module writes to stderr by design, so
  every probe here goes through a helper that merges stderr and relaxes the preference.
- It **drops embedded double quotes** when passing arguments to a native executable, so
  `-c "find_spec(\"torch\")"` arrives as `find_spec(torch)` and raises `NameError`. Use
  single quotes inside Python snippets.
- Related: `$PSScriptRoot` is empty while `param()` defaults are evaluated, so a default of
  `(Join-Path $PSScriptRoot 'ComfyUI')` crashes. Resolve paths *after* the param block.

Also: `--whitelist-custom-nodes` matches the raw directory entry, so it needs
`qwen_simple_ui.py` with the extension.
