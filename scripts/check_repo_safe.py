"""Pre-publish safety check: refuse to ship anything large, private or machine-specific.

Run this before every push, and certainly before making the repo public:

    python scripts/check_repo_safe.py

It inspects the files git would actually track (so .gitignore is respected) and
fails on: oversized files, weights, images, absolute local paths, email
addresses, and anything that looks like a credential.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

MAX_BYTES = 1 * 1024 * 1024  # nothing first-party here should approach 1 MB

BANNED_SUFFIXES = {
    ".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".onnx",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".gif", ".mp4", ".webm",
    ".db", ".sqlite", ".sqlite3", ".log", ".env", ".key", ".pem", ".pfx", ".p12",
}

# Patterns that must not appear in tracked text. Each entry is (label, regex).
PATTERNS = [
    ("Windows user path", re.compile(r"[A-Za-z]:\\+Users\\+[^\\\s\"']+", re.I)),
    ("Unix home path", re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+/")),
    ("email address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("AWS key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer/api token", re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]")),
    ("HuggingFace token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("Windows SID", re.compile(r"\bS-1-5-21(?:-\d+){3,}\b")),
]

# Placeholders that are meant to appear in docs and are not real values.
ALLOWED = {
    "you@example.com",
    "C:\\Users\\<you>",
    "C:\\Users\\you",
}


def normalize(s: str) -> str:
    """Collapse escaped backslash runs so a source literal matches its parsed form."""
    return re.sub(r"\\+", "\\\\", s.lower())


ALLOWED_NORM = {normalize(a) for a in ALLOWED}


def tracked_files(repo: Path) -> list[Path]:
    """Files git tracks or would track, honouring .gitignore."""
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.split("\n")
    return [repo / line for line in out if line.strip()]


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    problems: list[str] = []
    checked = 0

    for path in tracked_files(repo):
        if not path.is_file():
            continue
        rel = path.relative_to(repo).as_posix()
        checked += 1

        size = path.stat().st_size
        if size > MAX_BYTES:
            problems.append(f"{rel}: {size/1024/1024:.1f} MB exceeds the {MAX_BYTES//1024//1024} MB limit")
        if path.suffix.lower() in BANNED_SUFFIXES:
            problems.append(f"{rel}: '{path.suffix}' must never be tracked")

        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            problems.append(f"{rel}: not valid UTF-8 text - is this a binary that slipped through?")
            continue

        for label, rx in PATTERNS:
            for m in rx.finditer(text):
                hit = normalize(m.group(0))
                if any(a in hit for a in ALLOWED_NORM):
                    continue
                hit = m.group(0)
                line = text[:m.start()].count("\n") + 1
                problems.append(f"{rel}:{line}: {label}: {hit}")

    print(f"checked {checked} tracked file(s)\n")
    if problems:
        print("NOT SAFE TO PUBLISH:\n")
        for p in problems:
            print(f"  {p}")
        print(f"\n{len(problems)} problem(s). Fix these before pushing.")
        return 1

    print("Clean: no large files, no weights, no images, no local paths, no secrets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
