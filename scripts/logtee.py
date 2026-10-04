"""Run a server, log all of its output, and show only what matters in its window.

    python logtee.py --log logs/server.log --show "PATTERN" [--show ...] -- <command...>

Everything the command prints (stdout and stderr) goes to the log, timestamped; the
previous run's log is kept as <name>.previous.log. The console shows only lines that
match a --show pattern, plus anything that looks like a problem (error, failed,
exception, traceback, with the traceback's following lines), plus a question left
waiting without a newline ("Press any key to continue . . .", "(Y/N)?"). Progress-bar
redraws collapse to their final state.

The command stays attached to this console, so closing the window stops it too.
Standard library only. Exit status: the command's.
"""

from __future__ import annotations

import argparse
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")  # terminal colour codes: kept for the window, not the log
PROBLEM = re.compile(r"\b(error|errors|failed|failure|fatal|exception|traceback|out of memory|cannot|unable to|not found)\b", re.I)
PROMPT = re.compile(r"(\?|:|\. \. \.)\s*$")  # how a question waiting for an answer ends


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
    try:
        if path.exists():
            path.replace(path.with_name(path.stem + ".previous" + path.suffix))
    except OSError:
        pass  # another run still has it open: append to it instead
    log = open(path, "a", encoding="utf-8", errors="replace")
    log.write(f"=== started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    log.flush()
    return log


def pump(stream, chunks: queue.Queue) -> None:
    """Read the command's output on a thread, so a half-written line can be noticed."""
    while True:
        chunk = stream.read1(65536) if hasattr(stream, "read1") else stream.read(4096)
        chunks.put(chunk)
        if not chunk:
            return


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", required=True, type=Path)
    ap.add_argument("--show", action="append", default=[], help="regex for lines to show in the window")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        ap.error("give the command to run after --")

    try:
        sys.stdout.reconfigure(errors="replace")  # a piped stdout is cp1252: don't die on other characters
    except (AttributeError, ValueError):
        pass
    log = open_log(args.log)
    show = Filter(args.show)
    out = sys.stdout

    def emit(raw: bytes, prompt: bool = False) -> None:
        line = raw.decode("utf-8", "replace").rstrip()
        if not line.strip():
            return
        plain = ANSI.sub("", line)
        log.write(f"{time.strftime('%H:%M:%S')} {plain}\n")
        log.flush()
        if prompt or show(plain):
            out.write(line + "\n")
            out.flush()

    def lines(pending: bytes) -> bytes:
        """Emit every complete line in pending; return what's left."""
        while True:
            cut = [i for i in (pending.find(b"\n"), pending.find(b"\r")) if i != -1]
            if not cut:
                return pending
            i = min(cut)
            if pending[i:i + 1] == b"\r" and i + 1 == len(pending):
                return pending  # the read ended on \r: wait to see whether \n follows
            raw, end, pending = pending[:i], pending[i:i + 1], pending[i + 1:]
            if end == b"\r" and not pending.startswith(b"\n"):
                continue  # a progress-bar redraw: keep only its final state
            emit(raw)

    print(f"  full log: {args.log.resolve()}", flush=True)
    # Python children write UTF-8, unbuffered, so the log reads right and lines arrive at once.
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    # stdin stays the console's (a server may ask a question); output comes to us.
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0, env=env)
    # Ctrl+C reaches the command from the console too: let it decide, and keep reading until it exits.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    chunks: queue.Queue = queue.Queue()
    threading.Thread(target=pump, args=(proc.stdout, chunks), daemon=True).start()
    pending = b""
    while True:
        try:
            chunk = chunks.get(timeout=0.5)
        except queue.Empty:
            # Quiet for half a second on a half-written line that ends like a question: the
            # command is waiting for an answer (pause, "Terminate batch job (Y/N)?"), so show it.
            if PROMPT.search(pending.decode("utf-8", "replace")):
                emit(pending, prompt=True)
                pending = b""
            continue
        if not chunk:
            break
        pending = lines(pending + chunk)
    emit(pending)  # a last line without a newline
    code = proc.wait()
    log.write(f"=== exited with code {code} at {time.strftime('%H:%M:%S')} ===\n")
    log.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
