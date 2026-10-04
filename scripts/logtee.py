"""Run a server, log all of its output, and show only what matters in its window.

    python logtee.py --log logs/server.log --show "PATTERN" [--show ...] -- <command...>

Everything the command prints (stdout and stderr) goes to the log, timestamped; the
previous run's log is kept as <name>.previous.log. The console shows only lines that
match a --show pattern, plus anything that looks like a problem (error, failed,
exception, traceback, with the traceback's following lines). Progress-bar redraws
collapse to their final state.

The command stays attached to this console, so closing the window stops it too.
Standard library only. Exit status: the command's.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")  # terminal colour codes: kept for the window, not the log
PROBLEM = re.compile(r"\b(error|errors|failed|failure|fatal|exception|traceback|out of memory|cannot|unable to|not found)\b", re.I)


class Filter:
    """Decides which lines reach the console."""

    def __init__(self, show: list[str]):
        self.show = [re.compile(p) for p in show]
        self.in_traceback = False

    def __call__(self, line: str) -> bool:
        if self.in_traceback:
            # A Python traceback: indented frames, then the exception line ends it.
            if line.startswith((" ", "\t")):
                return True
            self.in_traceback = False
            return True
        if line.startswith("Traceback (most recent call last)"):
            self.in_traceback = True
            return True
        return bool(PROBLEM.search(line)) or any(p.search(line) for p in self.show)


def open_log(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.replace(path.with_name(path.stem + ".previous" + path.suffix))
    log = open(path, "a", encoding="utf-8", errors="replace")
    log.write(f"=== started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    log.flush()
    return log


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", required=True, type=Path)
    ap.add_argument("--show", action="append", default=[], help="regex for lines to show in the window")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        ap.error("give the command to run after --")

    log = open_log(args.log)
    show = Filter(args.show)
    out = sys.stdout
    print(f"  full log: {args.log.resolve()}", flush=True)
    # stdin stays the console's (a server may ask a question); output comes to us.
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
    pending = b""
    try:
        while True:
            chunk = proc.stdout.read1(65536) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
            if not chunk:
                break
            pending += chunk
            while True:
                cut = [i for i in (pending.find(b"\n"), pending.find(b"\r")) if i != -1]
                if not cut:
                    break
                i = min(cut)
                raw, end, pending = pending[:i], pending[i:i + 1], pending[i + 1:]
                if end == b"\r" and not pending.startswith(b"\n"):
                    continue  # a progress-bar redraw: keep only its final state
                line = raw.decode("utf-8", "replace").rstrip()
                if not line.strip():
                    continue
                plain = ANSI.sub("", line)
                log.write(f"{time.strftime('%H:%M:%S')} {plain}\n")
                log.flush()
                if show(plain):
                    out.write(line + "\n")
                    out.flush()
    except KeyboardInterrupt:
        pass  # Ctrl+C reaches the server too; wait for it to exit below
    code = proc.wait()
    log.write(f"=== exited with code {code} at {time.strftime('%H:%M:%S')} ===\n")
    log.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
