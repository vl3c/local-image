"""Command-line front end for the same pipeline the web page drives.

The server must already be running (start.cmd). Everything stays on localhost.

    python scripts/generate.py "a lighthouse at dawn"
    python scripts/generate.py "neon sign reading OPEN LATE" --size 1664x928 --seed 42
    python scripts/generate.py "make the sky stormy" --edit photo.png
    python scripts/generate.py "" --enhance output/qwen21_00003_.png
    python scripts/generate.py "a lighthouse" --wait 120 --out some/dir

Sizes must be multiples of 16. Editing takes its output shape from the first
reference image, so --size is ignored there; use --scale instead.

--out copies the results into a folder of your choosing, with the embedded
prompt, seed and workflow stripped (the originals in ComfyUI/output keep them).

Exit status: 0 done, 1 failed or no server, 2 bad arguments.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# PNG text chunks: where ComfyUI embeds the prompt and the whole workflow.
PNG_SIGNATURE = bytes.fromhex("89504e470d0a1a0a")
TEXT_CHUNKS = {b"tEXt", b"iTXt", b"zTXt"}

SERVER = "http://127.0.0.1:8188"
FULL_STEPS = 40
PREVIEW_STEPS = 20
ENHANCE_DENOISE = 0.45

DIFFUSION = "qwen_image_2.1_int8_convrot.safetensors"
ENCODER = "qwen3vl_8b_int8_convrot.safetensors"
VAE = "qwen_image_2.1_vae_bf16.safetensors"


def api(path: str, payload=None):
    url = SERVER + path
    if payload is None:
        return json.load(urllib.request.urlopen(url))
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))


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
    r = json.load(urllib.request.urlopen(req))
    return (r["subfolder"] + "/" if r.get("subfolder") else "") + r["name"]


def wait_for_server(seconds: float) -> bool:
    """True once the server answers; a cold start takes a few seconds to bind."""
    deadline = time.time() + seconds
    while True:
        try:
            api("/system_stats")
            return True
        except OSError:  # URLError, refused, reset while starting up
            if time.time() >= deadline:
                return False
            time.sleep(2)


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
    data = urllib.request.urlopen(f"{SERVER}/view?{query}").read()
    if not keep_metadata:
        data = strip_png_text(data)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / img["filename"]
    dest.write_bytes(data)
    return dest.resolve()


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
    return wf


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt", help="what to generate, or how to change the reference")
    ap.add_argument("--size", default="1328x1328", help="WxH, multiples of 16 (default 1328x1328)")
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
                    help="wait this long for the server to come up (default: fail at once)")
    ap.add_argument("--timeout", type=float, default=900, metavar="SECONDS",
                    help="give up waiting for the result after this long (default 900)")
    ap.add_argument("--out", type=Path, metavar="DIR",
                    help="copy the results here, prompt metadata stripped")
    ap.add_argument("--keep-metadata", action="store_true",
                    help="with --out, keep the embedded prompt, seed and workflow")
    args = ap.parse_args()

    try:
        args.width, args.height = (int(v) for v in args.size.lower().split("x"))
    except ValueError:
        print(f"--size must look like 1328x1328, got {args.size!r}")
        return 2
    if args.width % 16 or args.height % 16:
        print("--size values must be multiples of 16")
        return 2

    args.steps = args.steps or (PREVIEW_STEPS if args.preview else FULL_STEPS)
    if args.seed is None:
        args.seed = random.randrange(2**32)

    if not wait_for_server(args.wait):
        print(f"No server at {SERVER}. Start it with start.cmd first.")
        return 1

    refs = [upload(Path(p)) for p in args.edit]
    enhance_file = upload(Path(args.enhance)) if args.enhance else None

    what = "enhance" if enhance_file else ("edit" if refs else "generate")
    print(f"{what}: seed {args.seed}, {args.steps} steps"
          + ("" if refs or enhance_file else f", {args.width}x{args.height}"))

    t0 = time.time()
    try:
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
    while True:
        if time.time() - t0 > args.timeout:
            print(f"Timed out after {args.timeout:.0f}s. The job ({pid}) is still queued on the "
                  "server and its result will land in ComfyUI/output.")
            return 1
        hist = api(f"/history/{pid}")
        if pid in hist:
            entry = hist[pid]
            status = entry.get("status", {})
            if not status.get("completed"):
                note = next((m[1] for m in status.get("messages", []) if m[0] == "execution_error"), None)
                print("FAILED:", note.get("exception_message", note) if note else json.dumps(status)[:400])
                return 1
            for node in entry.get("outputs", {}).values():
                for img in node.get("images", []):
                    if args.out:
                        print(f"  {fetch(img, args.out, args.keep_metadata)}")
                    else:
                        print(f"  {img['filename']}")
            print(f"{time.time() - t0:.1f}s")
            return 0
        time.sleep(0.5)


if __name__ == "__main__":
    sys.exit(main())
