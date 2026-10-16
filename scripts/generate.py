"""Command-line front end for the same pipeline the web page drives.

If the server isn't running, this starts it with start.cmd, in its own visible window:
close that window, or run stop.cmd, to stop it and free the GPU. It won't start it while
another program holds a large share of the GPU. Everything stays on localhost.

    python scripts/generate.py "a lighthouse at dawn"
    python scripts/generate.py "neon sign reading OPEN LATE" --size 1664x928 --seed 42
    python scripts/generate.py "make the sky stormy" --edit photo.png
    python scripts/generate.py "" --enhance output/qwen21_00003_.png
    python scripts/generate.py "a lighthouse" --out some/dir
    python scripts/generate.py "a foggy city at night" --fit 1920x1080 --out plates
    python scripts/generate.py "a raised fist" --cutout --size 1024x1024 --out shapes

Sizes must be multiples of 16. Editing takes its output shape from the first
reference image, so --size is ignored there; use --scale instead.

--fit WxH delivers exactly WxH, any numbers, for video and the like: it renders at
the nearest size the model takes and then scales and centre-crops to cover the
target (1920x1080 renders at 1920x1088 and loses 4 rows top and bottom). It works
after edits and enhances too, and the result is plain RGB.

--cutout asks for one object as a solid black silhouette (or, with --cutout-object, in its
own colours) on a transparent background, which this model really draws as alpha, then
runs scripts/cutout.py on each result: a transparent PNG, a clean mask, the outline as SVG
and JSON, and a check image. The alpha channel is kept, even with --fit. Rerun cutout.py
by hand on the same file to adjust the cleanup (--open, --close, ...).

--out copies the results into a folder of your choosing, with the embedded
prompt, seed and workflow stripped (the originals in ComfyUI/output keep them).
Once that folder holds two or more images (counting the --edit or --enhance input),
it also gets compare.html, a page opened from disk to flip between them with the keys
1, 2, 3... (see scripts/compare.py); --no-compare skips it.

Exit status: 0 done, 1 failed or no server, 2 bad arguments.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# PNG text chunks: where ComfyUI embeds the prompt and the whole workflow.
PNG_SIGNATURE = bytes.fromhex("89504e470d0a1a0a")
TEXT_CHUNKS = {b"tEXt", b"iTXt", b"zTXt"}

# start.cmd reads the same variable; 8188 unless you set it.
SERVER = "http://127.0.0.1:" + os.environ.get("LOCAL_IMAGE_PORT", "8188")
FULL_STEPS = 40
PREVIEW_STEPS = 20
ENHANCE_DENOISE = 0.45

# --fit renders between these pixel counts, then scales: below about a megapixel the
# model loses detail, and above ~2.4 MP a render costs more than upscaling saves.
FIT_MIN_PIXELS = 1024 * 1024
FIT_MAX_PIXELS = 2048 * 1152

# Starting the server for you: it needs ~15.5 GB of VRAM, so don't when something else
# already holds more than this; and allow a cold start this long to answer.
OTHER_GPU_MB = 4096
START_WAIT = 180

HTTP_TIMEOUT = 60  # per request; a single call only blocks this long, whatever --timeout says
# What a server that is starting, stopping or gone raises: OSError covers URLError,
# refused and reset connections and socket timeouts; the rest are half-sent answers.
SERVER_ERRORS = (OSError, http.client.HTTPException, ValueError)

DIFFUSION = "qwen_image_2.1_int8_convrot.safetensors"
ENCODER = "qwen3vl_8b_int8_convrot.safetensors"
VAE = "qwen_image_2.1_vae_bf16.safetensors"


def api(path: str, payload=None):
    url = SERVER + path
    if payload is None:
        return json.load(urllib.request.urlopen(url, timeout=HTTP_TIMEOUT))
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=HTTP_TIMEOUT))


def upload(path: Path) -> str:
    """Push a local image into ComfyUI's input dir; returns the name to reference."""
    boundary = "----localimage" + str(random.randint(10**9, 10**10))
    body = bytearray()
    for field, value in (("type", "input"), ("overwrite", "true")):
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"\r\n\r\n{value}\r\n".encode()
    body += (f"--{boundary}\r\n"
             f"Content-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
             f"Content-Type: application/octet-stream\r\n\r\n").encode()
    body += path.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(SERVER + "/upload/image", data=bytes(body),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    r = json.load(urllib.request.urlopen(req, timeout=HTTP_TIMEOUT))
    return (r["subfolder"] + "/" if r.get("subfolder") else "") + r["name"]


def wait_for_server(seconds: float) -> bool:
    """True once the server answers; a cold start takes a few seconds to bind."""
    deadline = time.time() + seconds
    while True:
        try:
            api("/system_stats")
            return True
        except SERVER_ERRORS:  # refused, reset or half-answered while starting up
            if time.time() >= deadline:
                return False
            time.sleep(2)


def start_server() -> str | None:
    """Open the server in its own visible window with start.cmd. Returns why not, or None."""
    if not (COMFYUI / ".venv" / "Scripts" / "python.exe").is_file():
        return (f"there is no install at {COMFYUI}. Run install.ps1, or set LOCAL_IMAGE_COMFYUI "
                "to where your ComfyUI is")
    # Already running from this install, just not answering yet (or on another port)? Then
    # the VRAM it holds is ours, and there's nothing to start.
    try:
        running = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                  str(REPO / "scripts" / "stop.ps1"), "-Running", str(COMFYUI)],
                                 capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        running = False
    if running:
        return None
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=20).stdout
        used = int(out.split()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        used = 0  # no nvidia-smi to ask: let the server find out
    if used > OTHER_GPU_MB:
        return (f"another program holds {used / 1024:.1f} GB of the GPU, and this needs about "
                "15.5 GB. Stop it first (nvidia-smi shows what), then run this again")
    # start.cmd opens the window and returns at once; it won't open a second one. No handles
    # of ours go with it: the window would inherit our stdout and hold it open for as long
    # as the server runs, so whoever reads our output (a pipe, an agent) would never finish.
    subprocess.run(["cmd", "/c", str(REPO / "start.cmd"), "--no-browser"], check=False,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return None


def strip_png_text(data: bytes) -> bytes:
    """Drop text chunks, so the prompt does not travel with the file."""
    if data[:8] != PNG_SIGNATURE:
        return data
    out, i = bytearray(data[:8]), 8
    while i + 8 <= len(data):
        length = int.from_bytes(data[i:i + 4], "big")
        end = i + 12 + length
        if data[i + 4:i + 8] not in TEXT_CHUNKS:
            out += data[i:end]
        i = end
    return bytes(out)


def fetch(img: dict, out_dir: Path, keep_metadata: bool) -> Path:
    """Copy one result out of the server's output dir."""
    query = urllib.parse.urlencode({"filename": img["filename"],
                                    "subfolder": img.get("subfolder", ""),
                                    "type": img.get("type", "output")})
    data = urllib.request.urlopen(f"{SERVER}/view?{query}", timeout=HTTP_TIMEOUT).read()
    if not keep_metadata:
        data = strip_png_text(data)
    out_dir.mkdir(parents=True, exist_ok=True)
    # ComfyUI restarts its numbering once its output dir is emptied, so a name
    # can come round again: never overwrite an earlier keeper.
    name = Path(img["filename"]).name
    dest, n = out_dir / name, 1
    while dest.exists():
        dest = out_dir / f"{Path(name).stem}_{n}{Path(name).suffix}"
        n += 1
    dest.write_bytes(data)
    return dest.resolve()


REPO = Path(__file__).resolve().parent.parent
# The ComfyUI install, for starting the server and for cutout.py's Python. start.cmd and
# stop.cmd read the same variable; install.ps1 -ComfyUI puts it elsewhere.
COMFYUI = Path(os.environ.get("LOCAL_IMAGE_COMFYUI") or REPO / "ComfyUI")

# What --cutout adds to the prompt. The model's VAE is RGBA and it draws real alpha for
# this phrasing (16 of 16 seeds in testing; plain "on a transparent background" was
# ignored). Positive phrasing only: there is no negative prompt.
CUTOUT_PROMPTS = {
    "silhouette": "{}. Shown as one solid, pure black silhouette with no inner detail, centred with "
                  "clear empty margin on every side, isolated on a fully transparent background, "
                  "PNG with alpha channel.",
    "object": "{}. One single object, centred with clear empty margin on every side, isolated on a "
              "fully transparent background, PNG with alpha channel.",
}


def run_cutout(images: list[Path], out_dir: Path) -> bool:
    """scripts/cutout.py needs numpy, scipy and Pillow: ComfyUI's own Python has them."""
    venv = COMFYUI / ".venv" / "Scripts" / "python.exe"
    python = str(venv) if venv.is_file() else sys.executable
    print("cutout:", flush=True)  # or a piped stdout prints the child's lines first
    r = subprocess.run([python, str(REPO / "scripts" / "cutout.py"), *map(str, images), "--out", str(out_dir)])
    return r.returncode == 0


def write_compare(args) -> None:
    """compare.html in --out, with the edited or enhanced image first as the original."""
    import compare  # scripts/compare.py
    source = args.edit[0] if args.edit else args.enhance
    dropped = bool(source) and compare.private_link(Path(source), args.out)
    if dropped:
        # The page may end up in a project or be shared: no link that shows the user's folders.
        print("compare.html: the source image is left off the page (linking it would show your folders)")
        source = None
    try:
        page = compare.write(args.out, Path(source) if source else None, min_images=2,
                             keep_previous=not dropped)  # not an earlier edit's source
    except OSError as exc:  # a page is a convenience; never fail a finished render over it
        print(f"compare.html not written: {exc}")
        return
    if page:
        print(f"compare: {page}")


def parse_size(text: str) -> tuple[int, int]:
    w, h = (int(v) for v in text.lower().split("x"))
    if w <= 0 or h <= 0:
        raise ValueError(text)
    return w, h


def fit_render_size(w: int, h: int) -> tuple[int, int]:
    """The render size for a --fit target: its aspect, rounded up to multiples of 16."""
    scale = min(max(1.0, (FIT_MIN_PIXELS / (w * h)) ** 0.5), (FIT_MAX_PIXELS / (w * h)) ** 0.5)
    return -(-round(w * scale) // 16) * 16, -(-round(h * scale) // 16) * 16


def build(args, refs: list[str], enhance_file: str | None):
    w, h = args.width, args.height
    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": args.model, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": args.encoder, "type": "qwen_image"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "TextEncodeQwenImage21", "inputs": {
            "clip": ["2", 0], "prompt": args.prompt, "negative_prompt": "",
            "resolution": args.scale if refs else 1024}},
        "6": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["4", 0], "negative": ["4", 1], "latent_image": None,
            "seed": args.seed, "steps": args.steps, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": "qwen21"}},
    }

    if enhance_file:
        wf["20"] = {"class_type": "LoadImage", "inputs": {"image": enhance_file}}
        wf["21"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["20", 0], "vae": ["3", 0]}}
        wf["6"]["inputs"]["denoise"] = args.denoise
        wf["8"]["inputs"]["filename_prefix"] = "qwen21_enhanced"
        wf["6"]["inputs"]["latent_image"] = ["21", 0]
    elif refs:
        wf["4"]["inputs"]["vae"] = ["3", 0]
        for i, ref in enumerate(refs):
            nid = str(100 + i)
            wf[nid] = {"class_type": "LoadImage", "inputs": {"image": ref}}
            # autogrow slots are namespaced in the API format
            wf["4"]["inputs"][f"images.image_{i + 1}"] = [nid, 0]
        wf["8"]["inputs"]["filename_prefix"] = "qwen21_edit"
        if args.count > 1:
            wf["9"] = {"class_type": "RepeatLatentBatch", "inputs": {"samples": ["4", 2], "amount": args.count}}
            wf["6"]["inputs"]["latent_image"] = ["9", 0]
        else:
            wf["6"]["inputs"]["latent_image"] = ["4", 2]
    else:
        wf["5"] = {"class_type": "EmptyQwenImage21Latent",
                   "inputs": {"width": w, "height": h, "batch_size": args.count}}
        wf["6"]["inputs"]["latent_image"] = ["5", 0]

    # Delivery steps between the decode (7) and the save (8), ids 30-39.
    if args.fit:
        # ImageScale with crop=center scales to cover and trims the overflow evenly.
        wf["30"] = {"class_type": "ImageScale", "inputs": {
            "image": wf["8"]["inputs"]["images"], "upscale_method": "lanczos",
            "width": args.fit[0], "height": args.fit[1], "crop": "center"}}
        wf["8"]["inputs"]["images"] = ["30", 0]
    if args.rgb:
        # The VAE decodes RGBA, and the alpha of an "opaque" render dips to ~230 in
        # places, which shows as faint see-through specks once composited.
        wf["31"] = {"class_type": "SplitImageWithAlpha", "inputs": {"image": wf["8"]["inputs"]["images"]}}
        wf["8"]["inputs"]["images"] = ["31", 0]
    return wf


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt", help="what to generate, or how to change the reference")
    ap.add_argument("--size", default=None, help="WxH, multiples of 16 (default 1328x1328)")
    ap.add_argument("--fit", metavar="WxH",
                    help="deliver exactly WxH (e.g. 1920x1080): render near it, then scale and centre-crop; implies --rgb")
    # Two flags rather than an optional value, which would swallow a prompt written after it.
    ap.add_argument("--cutout", action="store_const", const="silhouette",
                    help="one object as a black silhouette on a transparent background, then cut out "
                         "with scripts/cutout.py; needs --out")
    ap.add_argument("--cutout-object", dest="cutout", action="store_const", const="object",
                    help="like --cutout, but the object keeps its own colours")
    ap.add_argument("--rgb", action="store_true",
                    help="save plain RGB, dropping the model's near-opaque alpha channel")
    ap.add_argument("--seed", type=int, default=None, help="default random; reuse to reproduce")
    ap.add_argument("--count", type=int, default=1, help="how many images")
    ap.add_argument("--preview", action="store_true", help=f"{PREVIEW_STEPS} steps instead of {FULL_STEPS}")
    ap.add_argument("--steps", type=int, default=None, help="explicit step count")
    ap.add_argument("--edit", action="append", default=[], metavar="IMG",
                    help="reference image to edit; repeat for up to 10")
    ap.add_argument("--enhance", metavar="IMG", help="refine this image's pixels instead of generating")
    ap.add_argument("--denoise", type=float, default=ENHANCE_DENOISE, help="enhance strength (0-1)")
    ap.add_argument("--scale", type=int, default=1328, help="output scale when editing")
    ap.add_argument("--model", default=DIFFUSION)
    ap.add_argument("--encoder", default=ENCODER)
    ap.add_argument("--wait", type=float, default=0, metavar="SECONDS",
                    help="wait this long for a server that is already starting (default 0)")
    ap.add_argument("--no-start", action="store_true",
                    help="fail if the server isn't running, rather than starting it in its window")
    ap.add_argument("--timeout", type=float, default=900, metavar="SECONDS",
                    help="give up waiting for the result after this long (default 900)")
    ap.add_argument("--out", type=Path, metavar="DIR",
                    help="copy the results here, prompt metadata stripped")
    ap.add_argument("--keep-metadata", action="store_true",
                    help="with --out, keep the embedded prompt, seed and workflow")
    ap.add_argument("--no-compare", action="store_true",
                    help="with --out, don't write compare.html (written once the folder has 2+ images)")
    args = ap.parse_args()

    if args.fit:
        try:
            args.fit = parse_size(args.fit)
        except ValueError:
            print(f"--fit must look like 1920x1080, got {args.fit!r}")
            return 2
        args.rgb = True
    try:
        if args.size:
            args.width, args.height = parse_size(args.size)
        elif args.fit:
            args.width, args.height = fit_render_size(*args.fit)
        else:
            args.width, args.height = 1328, 1328
    except ValueError:
        print(f"--size must look like 1328x1328, got {args.size!r}")
        return 2
    if args.width % 16 or args.height % 16:
        print("--size values must be multiples of 16")
        return 2

    if args.keep_metadata and not args.out:
        print("--keep-metadata only applies with --out")
        return 2
    if args.no_compare and not args.out:
        print("--no-compare only applies with --out")
        return 2
    if args.cutout:
        if not args.out:
            print("--cutout needs --out: the cut-outs are written next to the images")
            return 2
        if args.enhance:
            print("--cutout doesn't apply to --enhance; run scripts/cutout.py on the result instead")
            return 2
        args.prompt = CUTOUT_PROMPTS[args.cutout].format(args.prompt.strip().rstrip("."))
        args.rgb = False  # the alpha is the point, even with --fit
    missing = [p for p in args.edit + ([args.enhance] if args.enhance else []) if not Path(p).is_file()]
    if missing:
        print("No such image: " + ", ".join(missing))
        return 2

    args.steps = args.steps or (PREVIEW_STEPS if args.preview else FULL_STEPS)
    if args.seed is None:
        args.seed = random.randrange(2**32)

    if not wait_for_server(args.wait):
        if args.no_start:
            print(f"No server at {SERVER}. Start it with start.cmd first.")
            return 1
        why = start_server()
        if why:
            print(f"No server at {SERVER}, and not starting one: {why}.")
            return 1
        print("Started the server in its own window (\"local-image ComfyUI server\"). Close that "
              "window, or run stop.cmd, to stop it and free the GPU.", flush=True)
        if not wait_for_server(START_WAIT):
            print(f"No answer at {SERVER} within {START_WAIT}s. If a server from this install is running "
                  "on another port, set LOCAL_IMAGE_PORT to match; otherwise the end of "
                  "logs/server.log says why.")
            return 1

    try:
        refs = [upload(Path(p)) for p in args.edit]
        enhance_file = upload(Path(args.enhance)) if args.enhance else None

        what = "enhance" if enhance_file else ("edit" if refs else "generate")
        print(f"{what}: seed {args.seed}, {args.steps} steps"
              + ("" if refs or enhance_file else f", {args.width}x{args.height}")
              + (f", fit to {args.fit[0]}x{args.fit[1]}" if args.fit else ""))

        t0 = time.time()
        pid = api("/prompt", {"prompt": build(args, refs, enhance_file), "client_id": "cli"})["prompt_id"]
    except urllib.error.HTTPError as exc:
        # /prompt answers 400 with a JSON explanation when the graph is rejected
        detail = exc.read().decode("utf-8", "replace")
        try:
            detail = json.dumps(json.loads(detail).get("error", detail), indent=2)
        except ValueError:
            pass
        print(f"Rejected by the server (HTTP {exc.code}):\n{detail[:2000]}")
        return 1
    except SERVER_ERRORS as exc:
        print(f"Lost the server while submitting: {exc}")
        return 1
    try:
        return wait_for_result(args, pid, t0)
    except SERVER_ERRORS as exc:
        print(f"Lost the server while waiting for job {pid}: {exc}")
        return 1


def wait_for_result(args, pid: str, t0: float) -> int:
    while True:
        if time.time() - t0 > args.timeout:
            print(f"Timed out after {args.timeout:.0f}s. The job ({pid}) is still queued or running "
                  "on the server, and its result will land in ComfyUI/output.")
            return 1
        hist = api(f"/history/{pid}")
        if pid in hist:
            entry = hist[pid]
            status = entry.get("status", {})
            if not status.get("completed"):
                note = next((m[1] for m in status.get("messages", []) if m[0] == "execution_error"), None)
                print("FAILED:", note.get("exception_message", note) if note else json.dumps(status)[:400])
                return 1
            fetched = []
            for node in entry.get("outputs", {}).values():
                for img in node.get("images", []):
                    if args.out:
                        fetched.append(fetch(img, args.out, args.keep_metadata))
                        print(f"  {fetched[-1]}")
                    else:
                        print(f"  {img['filename']}")
            print(f"{time.time() - t0:.1f}s")
            if args.cutout and not run_cutout(fetched, args.out):
                return 1
            if args.out and not args.no_compare:
                write_compare(args)
            return 0
        time.sleep(0.5)


if __name__ == "__main__":
    sys.exit(main())
