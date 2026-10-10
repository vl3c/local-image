---
name: local-image
description: Generate or edit images locally with Qwen-Image-2.1 through ComfyUI on this machine's GPU (text-to-image, instruction edits with up to 10 reference images, enhance), look at every result yourself, iterate on the prompt or seed, and deliver the keepers to a folder the user names. Strong at rendering text inside images. Use when the user asks for a local image, local image generation or editing, Qwen-Image, ComfyUI, or wants an image made without a cloud service.
---

# local-image: generate and edit images on the local GPU

The model is fast (about 5–80 s per image once warm, by size and quality) and unusually good at lettering, but it
fails quietly: a misspelled word, the wrong object edited, or an edit that did nothing. You are
the art director. You write the prompt, run it, **look at every result**, and iterate until it
matches the request or you have to tell the user it doesn't.

## How a request looks

The user asks something like: "Make a local image of a bakery chalkboard that says FRESH BREAD
7AM". You own the whole loop.

1. **Check** the GPU and the server (step 1). Start the server if needed.
2. **Write the prompt** (step 3). Quote any text that must appear.
3. **Draft** with `--preview`, 1–4 images.
4. **Look** at each one with the Read tool (step 4). Check it against the request, not against
   how good it looks.
5. **Iterate:** change the prompt, the seed, or edit the best draft. Stop after about five rounds
   and show the user the closest one, saying what is still wrong.
6. **Finalize** the keeper at full quality (same seed, no `--preview`), or `--enhance` it if
   the composition must not move.
7. **Deliver** with `--out` to where the user wants it (step 6).
8. **Report back:**
   - the file paths;
   - the final prompt and seed, which reproduce the image exactly;
   - how many rounds it took and what you had to fix;
   - anything that still doesn't match;
   - that the server is still running and holding VRAM (step 7).

**When to ask the user:**
- Before stopping any other program that holds the GPU (step 1): it may be in use.
- When the request is ambiguous in a way a draft can't settle (style, which of several
  elements to change). Otherwise make a reasonable choice, show a draft and let them steer.
- Before writing an image into their project, if they didn't say where it goes.

All paths below are relative to this skill's base directory (the folder containing this file).
`README.md` has the full details: page controls, speeds, troubleshooting.

## Ground rules

- **Everything stays local.** The server listens on 127.0.0.1 only. Never send the user's
  prompts or reference images to any other service. Don't reach for a cloud generator as a
  fallback without asking.
- **Use your own judgment on content,** exactly as if you were drawing it yourself. A local model
  with no filter is not a reason to make something you wouldn't otherwise make: no sexual content
  involving minors, no sexual or degrading images of real people, and no realistic fakes of real
  people or documents meant to deceive.
- **Licence:** the weights are under the Qwen Research License, which permits "research or
  evaluation purposes only" (see `LICENSE-MODELS.md`). If the user plans to ship, sell or
  publish the image commercially, say so once, briefly. It is their call.
- **Reference images the user gives you are copied into `ComfyUI/input/`** and stay there. Say
  so if they seem sensitive. Everything in `ComfyUI/input/` and `ComfyUI/output/` is gitignored.

## 1. Check the GPU and the server

```bash
curl -s http://127.0.0.1:8188/system_stats | head -c 200     # JSON means the server is up
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
```

(If the user set `LOCAL_IMAGE_PORT`, the server is on that port instead of 8188.)

**This stack needs about 15.5 GB of a 16 GB card,** so nothing else large on the GPU can run
alongside it. If the `local-gpu` skill is installed, use it to see what holds the GPU and to
switch (it asks before stopping anything). Otherwise check `nvidia-smi` and **ask the user
before stopping other GPU programs**: they may be in use. Never kill a process you didn't
start; stop other tools with their own stop script, or ask the user to.

If this ComfyUI is already up and the card is full, that's this server, and it's fine.

**Start the server in its own window:**

```bash
cmd //c "$(cygpath -w "<base dir>/start.cmd")" --no-browser
```

`start.cmd` always opens the server in a visible console window titled "local-image ComfyUI
server - close this window to stop it" and returns at once, so the user can see it's running and
stop it by closing the window; `--no-browser` skips opening the page. Tell the user the window is
theirs to close. The window shows the address, one line per image job and any errors; everything
the server prints goes to `<base dir>/logs/server.log` (the previous run is
`server.previous.log`): **if the server doesn't come up, read the end of that log** rather than
retrying blindly.

It binds in a few seconds. The first generation afterwards also loads ~17 GB of weights. The
`--wait` flag below covers the startup, so you can start the server and generate right away.

**If `ComfyUI/.venv` is missing,** the tool isn't installed. `install.ps1` downloads about 30 GB;
ask the user before running it.

## 2. Commands

Run the CLI with any Python 3 (it only uses the standard library):

```bash
python "<base dir>/scripts/generate.py" "<prompt>" --preview --count 2 --wait 120 --out <dir>
python "<base dir>/scripts/generate.py" "<prompt>" --seed 42 --size 1664x928 --out <dir>
python "<base dir>/scripts/generate.py" "<change>" --edit a.png [--edit b.png ...] --scale 1024 --out <dir>
python "<base dir>/scripts/generate.py" "" --enhance keeper.png --out <dir>
python "<base dir>/scripts/generate.py" "<prompt>" --fit 1920x1080 --out <dir>
python "<base dir>/scripts/generate.py" "<object>" --cutout --size 1024x1024 --preview --count 2 --out <dir>
```

| Flag | Meaning |
|---|---|
| `--preview` | 20 steps instead of 40: about half the time. Use it for every draft. |
| `--seed N` | Reproduces an image exactly. Printed on every run; note it for the keepers. |
| `--size WxH` | Multiples of 16, default `1328x1328`. Other good ones: `1664x928` (16:9), `928x1664` (9:16), `1472x1104` (4:3), `1024x1024` (fast). Ignored when editing. |
| `--fit WxH` | Deliver exactly WxH, any numbers (e.g. `1920x1080` for video): renders near it, then scales and centre-crops. Plain RGB. Use this whenever the user names an exact delivery size. |
| `--cutout` | One object as a black silhouette on plain white, then cut out (step 5). `--cutout object` keeps its colours. Needs `--out`. Put the prompt before the flag. |
| `--rgb` | Save plain RGB. The VAE's alpha channel is slightly under fully opaque in places; drop it for anything that gets composited. |
| `--count N` | Several different images in one batch from one seed. Faster than separate runs. To reproduce one of them, rerun with the same seed *and* count: the batch comes back in the same order. |
| `--edit IMG` | A reference image to edit. Repeat for up to 10; the output takes the first one's shape. |
| `--scale N` | Output size when editing (default 1328). Higher is much slower. |
| `--enhance IMG` | Refines the pixels (denoise 0.45). It can't recompose, so it's safe for a keeper. |
| `--wait S` | Wait up to S seconds for the server to come up. |
| `--timeout S` | Give up on the result after S seconds (default 900). The job still finishes on the server. |
| `--out DIR` | Copy results to DIR with the prompt metadata stripped. Prints the full paths. Never overwrites: a name that already exists gets a `_1` suffix. |
| `--keep-metadata` | With `--out`, keep the embedded prompt, seed and workflow. |

An identical request (same prompt, seed and settings) comes back instantly from the server's
cache: it returns the earlier files again rather than rendering. To get a different image,
change the seed.

**Exit codes:**
- 0: done. With `--out`, the printed paths are the images.
- 1: failed, no server, lost the server, or timed out. The message says which.
- 2: bad arguments, including an `--edit` or `--enhance` image that doesn't exist.

Without `--out` the images are only in `ComfyUI/output/`, which keeps the metadata. Always pass
`--out`: drafts go to your scratchpad (or a temp folder), and keepers go where the user wants
them.

**Timing measured on an RTX 5080, warm (20 / 40 steps):** 1024² about 5 / 10 s, 1328² 11 / 21 s,
1664² 20 / 40 s, 2048² 40 / 79 s. An edit at the same scale costs a little more.

## 3. Write the prompt

- **Describe the image, not the task:** subject, setting, composition, light, style, medium.
  "A small bakery storefront, a black chalkboard beside the window, morning sun, 35mm photo"
  beats "make a bakery picture".
- **Put the text you want rendered in double quotes:** `a chalkboard that reads "FRESH BREAD
  7AM"`. Several separate pieces of text in one image work. Keep each short, and spell out
  capitalization.
- **There is no negative prompt.** The model samples guidance-free, so a negative prompt is
  discarded. Say what you want instead: "an empty street" rather than "no people".
- **Editing: name the exact element** when there's more than one candidate. "Change the sign"
  in a scene with a sign and a chalkboard may edit the chalkboard. Say "the hanging wooden sign
  above the door".
- **Changing text: say to erase the old text and write the new** in the same style, and try
  another seed if it doesn't take. In testing, "change the text to read X" and "replace the words
  X with Y" both returned the input unchanged on one seed, at both qualities. "Erase the chalk
  writing and write X in the same chalk style" on a new seed worked the first time.
- **Edits preserve identity well:** faces, products, lettering style and lighting survive
  weather, material and colour changes. Chain edits on the latest good result.

## 4. Look at every result

Open each image with the Read tool before you judge it or show it to the user. Check:

- **Every quoted string, letter by letter.** Wrong or doubled letters are the most common
  failure, and they're easy to miss at a glance.
- **Counts, positions and spatial relations** stated in the prompt.
- **For an edit:** did the named element change, and did everything else stay put?
- **The failed-edit signature:** the output is the input again, often over-sharpened and more
  saturated, with an HDR-like crunch. The model ignored the instruction. Rephrase it (step 3)
  and change the seed. Running the same prompt at full quality won't fix it.
- **Artifacts:** mangled hands, melted text, a duplicated object, edges that don't match.

**What to change when it misses:**
- Composition wrong: change the seed, or the prompt's description of the layout.
- Text wrong in an otherwise good image: edit that image to fix the text. It's cheaper than
  rerolling everything.
- Style wrong: rephrase the style or medium.
- Several near-misses: ask for `--count 4` and pick the best.

**When you finalize at full quality,** the composition usually holds but can drift, since 40
steps take a different path from the same seed. Look again. If it drifted, use `--enhance` on
the preview instead: it cannot move anything.

## 5. Silhouettes and cut-outs

For a shape to trace or composite (a hand pose, a tool, an icon, a figure), use `--cutout`.
It wraps the prompt so the model draws one object as a solid black silhouette on a plain white
background, then runs `scripts/cutout.py`, which writes next to each image:
`NAME_cutout.png` (transparent background), `NAME_mask.png` (white on black),
`NAME_contour.svg` and `NAME_contour.json` (the outline; outer loops and holes marked) and
**`NAME_check.png`: the cut-out on a checkerboard with the outline drawn in.**

- **Write only the object in the prompt** ("a raised fist, seen from the front"); the flag adds the
  background and framing. `--size 1024x1024` is plenty and fast.
- **Look at the `_check.png`,** not the raw image. Red lines are outer outlines, blue are holes.
- **Read the warnings it prints.** "touches the frame edge" means the object is cropped (fine
  for a hand cut at the wrist, not for a sword); "isn't plain" means the background
  failed and the cut is unreliable: reroll the seed.
- **Fix the cleanup without regenerating** by running the script again on the same image with
  ComfyUI's Python (it needs numpy, scipy and Pillow, which that environment has):

  ```bash
  "<base dir>/ComfyUI/.venv/Scripts/python.exe" "<base dir>/scripts/cutout.py" <dir>/qwen21_00012_.png --out <dir> --open 17
  ```

  | Problem in the check image | Option |
  |---|---|
  | A thin extra bit (a rod through a fist, a wire, stray hair) | `--open R`, R a bit over half its width in px |
  | A gap splits something that should be one piece | `--close R`, R a bit over half the gap |
  | A stray second object kept | `--keep 1` (by default every part over 1% of the largest stays) |
  | A real hole got filled, or you want no holes at all | `--fill-holes 0` keeps every hole, `--fill-holes 1` fills them all |

- **The model is the bigger lever:** a cast shadow, a floor line or a second object is easier to
  fix with a new seed or a more specific prompt than with cleanup options.
- `cutout.py` works on any image with a plain background, or real transparency, not only
  on results from here.

## 6. Deliver

- **Write keepers with `--out` into the folder the user named.** If they didn't name one and the
  image is for their project, ask where it goes.
- **Files are PNG,** RGBA unless `--fit`, `--rgb` or `--cutout` made them RGB, named like
  `qwen21_00018_.png`. Rename them to something meaningful if they're going into a project.
- **`--out` strips the prompt metadata.** That matters for anything that ends up in a public
  repo or gets shared. The original with metadata stays in `ComfyUI/output/`.
- **Showing the result:** the user can't see what you Read. Send the images with SendUserFile,
  or give the paths.
- **For a web page or doc,** convert or resize with the tools the project already uses. Don't
  install an image library just for that without asking.

## 7. When you're done

The server keeps the models in VRAM while it runs. That's what makes the next image fast, but
it also blocks anything else that needs the GPU. **Leave it running and tell the user** it's up.
Stop it when they're done or want the GPU for something else:

```bash
cmd //c "<base dir>\\stop.cmd"
```

It stops this install's ComfyUI processes (a launcher and the real server), leaves any other
ComfyUI alone, and reports the VRAM freed. Exit 0 means stopped or not running, 1 means
something survived. Don't restart whatever you stopped earlier unless the user asks.

The user can also use the tool by hand at `http://127.0.0.1:8188/simple`: a prompt box with
reference images, presets and an *Edit this* button on every result. Running `start.cmd` with no
arguments opens that page.
