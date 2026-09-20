# local-image

A private, fully local image generator and editor. Type a prompt, press Generate.

It runs **Qwen-Image-2.1** on your own GPU through ComfyUI, but replaces ComfyUI's
node-graph interface with a single page that is just a prompt box and a button. No
accounts, no cloud, no node wiring. Your prompts and images never leave the machine.

```
.\install.ps1   →   .\start.cmd   →   http://127.0.0.1:8188/simple
```

---

## What it does

- **Generate** from text, at eight preset aspect ratios up to 2K.
- **Edit** by describing a change — up to 10 reference images at once.
- **Iterate** — every result has an *Edit this* button, so edits chain.
- **Preview → commit** — a fast 20-step draft, then re-render the keeper at full quality.
- **Enhance** — refine an image's actual pixels when the composition must not move.

Qwen-Image-2.1 is unusually good at rendering *text inside images* — shop signs, labels,
handwriting, dense captions. That is the main reason to run this one locally.

## What you need

| | |
|---|---|
| OS | Windows 10 / 11 |
| GPU | NVIDIA. 16 GB VRAM is comfortable; 12 GB works but streams weights heavily |
| Disk | **~30 GB free** |
| RAM | 32 GB |
| Software | Python 3.13 (via the `py` launcher) and Git, both on PATH |

No CUDA toolkit needed — the PyTorch wheels bundle what they use. You just need a current
NVIDIA driver.

## Install

```powershell
git clone https://github.com/YOUR-USERNAME/local-image.git
cd local-image
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

The `-ExecutionPolicy Bypass` is needed because stock Windows refuses to run downloaded
scripts. If you would rather not, run `Unblock-File .\install.ps1` once and then just
`.\install.ps1`.

Re-running is safe: finished steps are skipped and downloads resume where they stopped.
Works on both Windows PowerShell 5.1 (the built-in one) and PowerShell 7.

### What install.ps1 puts on your disk

Everything lands **inside the repo folder, in `ComfyUI/`**, which is gitignored. Nothing
is installed system-wide, and your global Python is untouched.

| What | Where | Size |
|---|---|---|
| ComfyUI (shallow clone from GitHub) | `ComfyUI/` | ~100 MB |
| Private virtualenv | `ComfyUI/.venv/` | — |
| PyTorch + CUDA runtime | `ComfyUI/.venv/` | ~4 GB |
| ComfyUI's Python dependencies | `ComfyUI/.venv/` | ~1 GB |
| `triton-windows` (optional, skippable) | `ComfyUI/.venv/` | ~250 MB |
| This repo's UI node, copied in | `ComfyUI/custom_nodes/` | 22 KB |
| Model weights (below) | `ComfyUI/models/` | ~24 GB |

### What it downloads

Weights come from [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1)
on HuggingFace. **Every file is SHA256-verified** against the checksums pinned in
[`models.json`](models.json); a mismatch aborts the install rather than loading the file.
No HuggingFace account or token is required.

| File | Size | What it is |
|---|---|---|
| `qwen_image_2.1_int8_convrot.safetensors` | 7.3 GB | The 7B diffusion transformer — makes the image |
| `qwen3vl_8b_int8_convrot.safetensors` | 9.4 GB | Qwen3-VL-8B text encoder — reads your prompt |
| `qwen_image_2.1_vae_bf16.safetensors` | 0.7 GB | Decodes latents to pixels |
| `qwen3vl_8b_w4a8.safetensors` | 6.3 GB | Optional smaller encoder (`-AllModels`) |

All are `.safetensors` — a data-only format, so **no code executes when weights load**.
This setup never uses `.ckpt` or `.bin` pickle formats.

During install, network traffic goes to: `github.com` (the ComfyUI clone), `pypi.org` and
`files.pythonhosted.org` and `download.pytorch.org` (packages), and `huggingface.co`,
which redirects weight downloads to its CDN (`*.cdn.hf.co`).

Once installed, **the `/simple` page and the backend it talks to make no outbound
requests** — every fetch the page makes is to your own server. ComfyUI's *stock*
node-graph interface at `/` is a different matter; [PRIVACY.md](PRIVACY.md) documents what
it contacts and how `start.cmd` blocks it.

One thing that does not land inside the repo folder: pip's wheel cache, roughly 5 GB of
it, goes to `%LOCALAPPDATA%\pip\Cache`. Pass `-NoPipCache` to skip it, at the cost of
re-downloading if you reinstall.

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
.\install.ps1 -SyncNodeOnly            # just re-copy the UI after editing it
```

**About `-Commit`.** By default the installer checks out the exact ComfyUI revision that
[PRIVACY.md](PRIVACY.md)'s audit was performed against, so what you get matches what was
reviewed. `-Commit latest` tracks master instead — newer, but the audit's specific
findings no longer necessarily describe your copy.

## Use it

**`.\start.cmd`** starts the server and opens the page once it is ready. Leave the console
window open — closing it stops the server and frees your VRAM.

If you installed ComfyUI elsewhere, pass the path: `.\start.cmd D:\ai\ComfyUI`

### Stopping it

Normally: close the `start.cmd` console window. That is the whole answer.

If there is no window to close — the server was started in the background, or the window
got closed without the process dying — run **`.\stop.cmd`**. It reports what it stopped
and how much VRAM came back.

It matches on the ComfyUI command line, so other Python programs you have running are left
alone. Note that ComfyUI re-executes itself at startup, so there are always **two** python
processes to stop: a small launcher and the real server holding the VRAM. Killing only one
in Task Manager can leave the other resident.

There is also a CLI, for scripting or batches:

```bash
python scripts/generate.py "a neon sign reading OPEN LATE, rainy night"
python scripts/generate.py "a lighthouse at dawn" --size 1664x928 --seed 42 --preview
python scripts/generate.py "make the sky stormy" --edit photo.png
python scripts/generate.py "..." --enhance output/qwen21_00003_.png
```

### Where your images go

Generated images are written to `ComfyUI/output/`, reference images you upload to
`ComfyUI/input/`. **Both directories are gitignored entirely** — every file, every
format — so nothing you make or feed in can be committed by accident.

Nothing is auto-deleted. Each PNG embeds its prompt, seed and parent image, so you can
reproduce any result or trace an edit chain backwards. (That metadata survives the
original file but is stripped by most things that re-encode, and you can turn it off —
see PRIVACY.md.)

## Two ways to improve a draft

They are different operations and the difference matters:

| | **Full quality** | **Enhance** |
|---|---|---|
| starts from | the seed, fresh noise | the image's actual pixels |
| composition | usually preserved — **can drift** | cannot drift |
| detail gained | full 40-step render | less, but safe |
| offered on | previews only | every result |

Re-running a seed at a higher step count changes how the sampler discretizes the same
trajectory. Usually both land on the same image; when a composition is underdetermined,
the coarse path can settle somewhere else. In testing that happened about one time in
five. *Enhance* re-encodes the pixels you are looking at and denoises only partway (0.45),
so it physically cannot reframe the shot.

## Speed

RTX 5080 (16 GB), int8 weights, `--use-ck-attention`, warm:

| Resolution | Preview (20 steps) | Full (40 steps) |
|---|---|---|
| 1024² | ~5.5s | ~9.7s |
| 1328² | ~11s | ~21s |
| 1664² | ~20s | ~40s |
| 2048² | ~40s | ~79s |

Editing costs roughly 2× a generation at the same size, because the reference image's
latents are prepended to the sequence.

Peak VRAM sits near 15.5 GB of 16.3 GB at every resolution. That is ComfyUI's memory
manager deliberately filling the card and streaming weights — expected, not a problem.

**What helped, and what didn't.** `--use-ck-attention` was worth **−15%** (11.4s → 9.7s at
1024²) and is on by default; sage attention was equivalent. Triton made no measurable
difference alone. The int8 text encoder showed **no adherence gain** over the 4-bit one —
both handled counting, dense text and spatial negation correctly on identical seeds — so
it is the default only because it costs ~0.3s. If VRAM is tight, use `-AllModels` and pick
`qwen3vl_8b_w4a8` from the page's Advanced section; it gave up nothing in testing.

## Privacy

The `/simple` page and the generation backend make no outbound requests. `start.cmd` binds
**loopback only** and disables the cloud nodes ComfyUI bundles, its node registry, and all
custom nodes except this repo's — which also makes the browser enforce a
`connect-src 'self'` content-security policy, so a page served here cannot reach a third
party even if its JavaScript tried.

[PRIVACY.md](PRIVACY.md) documents the full audit, including two findings about ComfyUI's
*stock* node-graph interface that `/simple` avoids entirely, and the limits of what a
static audit can prove.

Before pushing anything to a public remote:

```bash
python scripts/check_repo_safe.py
```

It fails on large files, weights, images, local paths, email addresses and
credential-shaped strings.

## Licensing

Code here is **MIT** ([LICENSE](LICENSE)).

**The model weights are not.** Qwen-Image-2.1 is released under the Qwen Research License,
which restricts commercial use. This repo redistributes no weights — it downloads them
from HuggingFace, where their licence applies. Read
[LICENSE-MODELS.md](LICENSE-MODELS.md) before using output commercially.

ComfyUI is GPL-3.0 and is cloned at install time, not vendored here.

## Notes for anyone extending this

Two things that cost real debugging time:

1. **Reference image slots are namespaced.** `TextEncodeQwenImage21` uses ComfyUI
   "autogrow" inputs, so in the API workflow format the key is `images.image_1`, not
   `image_1`. The plain name fails with `unexpected keyword argument 'image_1'`.

2. **Negative prompts cannot work here.** The model samples guidance-free at `cfg 1.0`,
   and ComfyUI drops the unconditional branch entirely at that value (the
   `disable_cfg1_optimization` check in `comfy/samplers.py`). There is no negative prompt
   box because it could only ever be decorative. Steer with positive phrasing.

Also: editing needs the VAE wired into the text-encode node. Without it the references are
only *seen* by the text encoder instead of becoming reference latents — "inspired by"
rather than a real edit. And `--whitelist-custom-nodes` matches the raw filename, so it
needs `qwen_simple_ui.py`, extension included; without it nothing loads and `/simple`
404s.
