"""Fetch the Qwen-Image-2.1 weights listed in models.json, verifying every file.

Resumable: a partial file is continued with an HTTP Range request, and anything
whose SHA256 already matches is skipped. Nothing here is committed to the repo -
the weights land in <comfyui>/models/ and are covered by the Qwen Research License.

    python scripts/download_models.py --comfyui ./ComfyUI
    python scripts/download_models.py --comfyui ./ComfyUI --all      # optional files too
    python scripts/download_models.py --comfyui ./ComfyUI --verify   # check, download nothing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CHUNK = 1 << 20  # 1 MiB


def sha256(path: Path, progress: bool = True) -> str:
    h = hashlib.sha256()
    total = path.stat().st_size
    seen = 0
    last = 0.0
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
            seen += len(chunk)
            if progress and total and time.time() - last > 0.5:
                pct = 100 * seen / total
                print(f"\r    hashing {pct:5.1f}%", end="", flush=True)
                last = time.time()
    if progress:
        print("\r" + " " * 24 + "\r", end="")
    return h.hexdigest()


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def download(url: str, dest: Path, expect_sha: str) -> bool:
    """Download `url` to `dest`, resuming if a partial file exists. Returns True on success."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    have = dest.stat().st_size if dest.exists() else 0

    req = urllib.request.Request(url, headers={"User-Agent": "local-image/1.0"})
    if have:
        req.add_header("Range", f"bytes={have}-")
        print(f"    resuming at {human(have)}")

    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code == 416:  # range not satisfiable: the file is already complete
            resp = None
        else:
            print(f"    HTTP {exc.code}: {exc.reason}")
            return False
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # no network, DNS failure, TLS problem, HF unreachable
        print(f"    network error: {exc}")
        print("    Check your connection and re-run; the partial file is kept and will resume.")
        return False

    if resp is not None:
        # A 200 to a Range request means the server ignored it; restart from scratch.
        mode = "ab" if (have and resp.status == 206) else "wb"
        if mode == "wb":
            have = 0
        total = int(resp.headers.get("Content-Length", 0)) + have
        seen = have
        last = 0.0
        with dest.open(mode) as fh:
            while chunk := resp.read(CHUNK):
                fh.write(chunk)
                seen += len(chunk)
                if time.time() - last > 0.5:
                    pct = f"{100 * seen / total:5.1f}%" if total else "  ?  "
                    print(f"\r    {pct}  {human(seen)}", end="", flush=True)
                    last = time.time()
        print(f"\r    {human(seen)} downloaded" + " " * 12)

    actual = sha256(dest)
    if actual != expect_sha:
        print(f"    CHECKSUM MISMATCH\n      expected {expect_sha}\n      got      {actual}")
        # Remove it rather than leaving a bad file that a later resume would
        # append to, turning one bad download into a permanently stuck one.
        dest.unlink(missing_ok=True)
        print("    Discarded. Re-run to download it again.")
        return False
    print("    checksum OK")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comfyui", default="./ComfyUI", help="ComfyUI checkout to install weights into")
    ap.add_argument("--manifest", default=None, help="path to models.json")
    ap.add_argument("--all", action="store_true", help="also fetch files marked optional")
    ap.add_argument("--verify", action="store_true", help="verify existing files, download nothing")
    args = ap.parse_args()

    repo = Path(__file__).resolve().parent.parent
    manifest = Path(args.manifest) if args.manifest else repo / "models.json"
    spec = json.loads(manifest.read_text(encoding="utf-8"))
    root = Path(args.comfyui).resolve()

    if not root.exists():
        print(f"ComfyUI not found at {root}\nRun install.ps1 first, or pass --comfyui <path>.")
        return 1

    wanted = [f for f in spec["files"] if f.get("required", True) or args.all]
    total = sum(f["bytes"] for f in wanted)
    print(f"{len(wanted)} file(s), about {human(total)}\ninto {root}\n")

    failed = []
    for f in wanted:
        dest = root / f["dest"] / Path(f["path"]).name
        label = f"{Path(f['path']).name}  ({human(f['bytes'])})"
        print(f"  {label}")
        if f.get("note"):
            print(f"    {f['note']}")

        if dest.exists() and dest.stat().st_size == f["bytes"]:
            if sha256(dest) == f["sha256"]:
                print("    already present, checksum OK")
                continue
            print("    present but checksum does NOT match")
            if args.verify:
                failed.append(label)
                continue
            print("    re-downloading")
            dest.unlink()
        elif args.verify:
            print("    missing")
            failed.append(label)
            continue

        url = f"{spec['base_url']}/{f['path']}"
        if not download(url, dest, f["sha256"]):
            failed.append(label)
        print()

    if failed:
        print("FAILED:")
        for f in failed:
            print(f"  - {f}")
        return 1

    print("All weights present and verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
