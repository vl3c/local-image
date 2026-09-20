# local-image

A private, fully local image generator and editor built on **Qwen-Image-2.1** and ComfyUI —
with a one-page UI that is just a prompt box and a Generate button.

No node graphs, no cloud, no accounts. Your prompts and images never leave the machine.

```
install.ps1   →   start.cmd   →   http://127.0.0.1:8188/simple
```

---

## What it does

- **Generate** from a text prompt, at eight preset aspect ratios up to 2K.
- **Edit** an image by describing the change — up to 10 reference images at once.
- **Iterate**: every result has an *Edit this* button, so you can chain edits.
- **Preview → commit**: a fast 20-step draft, then re-render the one you like at full quality.
- **Enhance**: refine an image's actual pixels, when you need the composition to stay put.

Qwen-Image-2.1 is unusually good at rendering *text inside images* — signs, labels,
handwriting, dense captions — which is what makes it worth running locally.

## Requirements

| | |
|---|---|
| OS | Windows 10/11 |
| GPU | NVIDIA, 16 GB VRAM comfortably; 12 GB will work but stream heavily |
| Disk | ~30 GB (24 GB weights + ~4 GB PyTorch) |
| RAM | 32 GB |
| Python | 3.13 (via the `py` launcher) |

The bf16 weights need ~33 GB of RAM to offload and are *not* used here; this setup runs
int8-quantized weights throughout, which fit in VRAM and are near-lossless.

## Install

```powershell
git clone <your-repo-url> local-image
cd local-image
.\install.ps1
```

That clones ComfyUI beside the scripts, builds an isolated venv, installs a CUDA build of
PyTorch, installs the UI node, and downloads ~24 GB of weights with SHA256 verification.
Re-running is safe — finished steps are skipped and downloads resume.

Useful switches:

```powershell
.\install.ps1 -ComfyUI D:\ai\ComfyUI   # install somewhere else
.\install.ps1 -SkipModels              # code only, fetch weights later
.\install.ps1 -AllModels               # also grab the smaller w4a8 encoder
.\install.ps1 -CudaIndex cu129         # older driver
.\install.ps1 -SyncNodeOnly            # just re-copy the UI after editing it
```

## Use it

**`start.cmd`** launches the server and opens the page. Leave the console window open;
closing it stops the server and frees the VRAM.

Or drive it from the command line:

```bash
python scripts/generate.py "a neon sign reading OPEN LATE, rainy night"
python scripts/generate.py "a lighthouse at dawn" --size 1664x928 --seed 42 --preview
python scripts/generate.py "make the sky stormy" --edit photo.png
python scripts/generate.py "..." --enhance output/qwen21_00003_.png
```

Images are written to `<ComfyUI>/output/` and stay there until you delete them. Each PNG
embeds the prompt, seed and parent image, so you can always trace how one was made.

## Two ways to improve a draft

They are not the same operation, and the difference matters:

| | **Full quality** | **Enhance** |
|---|---|---|
| starts from | the seed, fresh noise | the image's actual pixels |
| composition | usually preserved — **can drift** | cannot drift |
| detail gained | full 40-step render | less, but safe |
| shown on | previews only | every result |

Re-running a seed at a higher step count changes how the sampler discretizes the same
trajectory. Usually both land on the same image; when a composition is underdetermined the
coarse path can settle somewhere else entirely. In testing that happened roughly one time
in five. *Enhance* re-encodes the pixels you are looking at and denoises only partway
(0.45), so it physically cannot reframe the shot.

## Measured performance

RTX 5080 (16 GB), int8 DiT + int8 encoder, `--use-ck-attention`, warm:

| Resolution | Preview (20 steps) | Full (40 steps) |
|---|---|---|
| 1024² | ~5.5s | ~9.7s |
| 1328² | ~11s | ~21s |
| 1664² | ~20s | ~40s |
| 2048² | ~40s | ~79s |

Editing costs roughly 2× a generation at the same size, because the reference image's
latents are prepended to the sequence.

Peak VRAM sits at ~15.5 GB of 16.3 GB at every resolution — ComfyUI's dynamic memory
manager deliberately fills the card and streams weights as needed. That is expected, not
a problem.

### Things that helped, and things that didn't

- **`--use-ck-attention`: −15%** (11.4s → 9.7s at 1024²). Enabled by default in `start.cmd`.
  Sage attention was equivalent (9.9s); flash attention needs a package that isn't installed.
- **Triton: no measurable effect** on its own (41.1s → 40.2s at 1664², within noise).
  `install.ps1` installs it anyway since it is small and some kernels want it.
- **int8 vs 4-bit text encoder: no measurable quality difference.** Both got counting
  ("exactly three cups… exactly two bottles"), dense text rendering, and spatial negation
  ("*under* the table, not on it") correct on identical seeds. int8 is the default only
  because it costs nothing once ck attention is on (+0.3s, +700 MB VRAM). If VRAM is
  tight, `qwen3vl_8b_w4a8` is 3 GB smaller and gave up nothing in testing.

## Model variants

Declared in [`models.json`](models.json), fetched from
[Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1), all checksum-verified.

| File | Size | Role |
|---|---|---|
| `qwen_image_2.1_int8_convrot` | 7.3 GB | 7B DiT — the denoiser |
| `qwen3vl_8b_int8_convrot` | 9.4 GB | Qwen3-VL-8B text encoder (default) |
| `qwen3vl_8b_w4a8` | 6.3 GB | 4-bit encoder (optional, `-AllModels`) |
| `qwen_image_2.1_vae_bf16` | 0.7 GB | 64-channel RGBA VAE |

Switch models from the **Advanced** section of the page without restarting.

## Privacy

This runs entirely offline once installed. See [PRIVACY.md](PRIVACY.md) for the audit.
In short, `start.cmd` binds **loopback only** (`--listen 127.0.0.1`, not reachable from
your network) and passes `--disable-api-nodes` and `--disable-manager-ui`, so the paid
cloud nodes ComfyUI bundles cannot load and the node registry is unreachable.

Weights load from `.safetensors` only — a data-only format, so no code executes on load.

Your images and prompts are gitignored and never committed. Before pushing:

```bash
python scripts/check_repo_safe.py
```

which fails on large files, weights, images, local paths, emails and credential-shaped
strings. Run it before making the repo public.

## Licensing

The code here is MIT ([LICENSE](LICENSE)).

**The model weights are not.** Qwen-Image-2.1 is released under the Qwen Research License,
which restricts commercial use. This repo does not redistribute any weights — it downloads
them from HuggingFace, where you accept that license. See
[LICENSE-MODELS.md](LICENSE-MODELS.md) before using output commercially.

ComfyUI is GPL-3.0 and is cloned at install time, not vendored here.

## Notes for anyone extending this

Two things cost real debugging time and are easy to miss:

1. **Reference image slots are namespaced.** `TextEncodeQwenImage21` uses ComfyUI
   "autogrow" inputs, so in the API workflow format the key is `images.image_1`, not
   `image_1`. The un-namespaced form fails with
   `unexpected keyword argument 'image_1'`.

2. **Negative prompts do nothing.** The model is sampled guidance-free at `cfg 1.0`, and
   ComfyUI drops the unconditional branch entirely at that value
   (`comfy/samplers.py`, the `disable_cfg1_optimization` check). There is no negative
   prompt box in the UI because it could only ever be decorative. Steer with positive
   phrasing instead.

Also: editing requires the VAE wired into the text-encode node. Without it the reference
images are only *seen* by the text encoder rather than becoming reference latents, which
gives you "inspired by" instead of a real edit.
