"""compare.html: a page to flip between results (and the image they were edited from).

    python scripts/compare.py DIR [--original IMG]

Every image in DIR is shown at the same size and in the same place; the number keys 1, 2, 3 ...
(or the buttons) switch between them, holding the photo shows the original, Space switches to it
(a tap) or shows it while held, Z zooms to full size. The page links the images by relative path,
so it works opened straight from disk, and loads nothing from the network. generate.py writes it
into --out after every run that leaves two or more images there (--no-compare skips it).
Standard library only.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote, unquote
from urllib.request import url2pathname

PAGE = "compare.html"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".jfif", ".webp", ".bmp", ".gif", ".avif"}  # what browsers show
# cutout.py's by-products: the same shape again, not a different result to compare
SKIP_SUFFIXES = ("_mask", "_cutout")
KEYS = list("1234567890") + list("qwertyuiop")


def _natural(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def collect(d: Path) -> list[Path]:
    """The results in `d`, in name order (ComfyUI numbers them in the order they were made)."""
    if not d.is_dir():
        return []
    return sorted((p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS
                   and not p.stem.lower().endswith(SKIP_SUFFIXES)), key=lambda p: _natural(p.name))


def label(p: Path) -> str:
    """"qwen21_00018_" -> "00018", "qwen21_edit_00003__1" -> "edit 00003 1", anything else as named."""
    s = re.sub(r"^qwen21_", "", p.stem)
    s = re.sub(r"_+", " ", s).strip() or p.stem
    return s[:1].upper() + s[1:]


def _src(p: Path, d: Path) -> str:
    try:
        return quote(Path(os.path.relpath(p, d)).as_posix())
    except ValueError:  # another drive: no relative path exists
        return p.resolve().as_uri()


def private_link(p: Path, d: Path) -> bool:
    """True when the page's link from `d` to `p` would show where the user keeps their files: an
    absolute file: URL (another drive), or a relative one that climbs through their home folder."""
    src = _src(Path(p).resolve(), Path(d).resolve())
    return src.startswith("file:") or Path.home().name.lower() in (s.lower() for s in unquote(src).split("/"))


def _previous_original(d: Path) -> Path | None:
    """The original an earlier compare.html in `d` showed, so a later run keeps it."""
    try:
        items = json.loads(re.search(r"var ITEMS = (\[.*?\]);", (d / PAGE).read_text(encoding="utf-8")).group(1))
    except (OSError, AttributeError, ValueError):
        return None
    for it in items:
        if it.get("original"):
            src = it.get("src", "")
            p = Path(url2pathname(src[len("file:"):])) if src.startswith("file:") else d / unquote(src)
            return p.resolve() if p.is_file() else None
    return None


def write(d: Path, original: Path | None = None, title: str | None = None, min_images: int = 1) -> Path | None:
    """Write `d`/compare.html for the images in `d`, with `original` (the image they were edited
    from; by default the one an earlier page here showed) first. Returns None, writing nothing,
    when the page would show fewer than `min_images` images."""
    d = Path(d).resolve()
    original = Path(original).resolve() if original else _previous_original(d)
    if original and original.suffix.lower() not in IMAGE_EXTS:
        original = None  # a browser can't show it
    items = [p for p in collect(d) if p != original]
    if len(items) + bool(original) < max(1, min_images):
        return None
    data = ([{"src": _src(original, d), "label": "Original", "file": original.name, "original": True}] if original else [])
    data += [{"src": _src(p, d), "label": label(p), "file": p.name, "original": False} for p in items]
    for i, it in enumerate(data):
        it["key"] = KEYS[i] if i < len(KEYS) else ""
    fill = {"TITLE": html.escape(title or d.name), "DATA": json.dumps(data).replace("<", "\\u003c")}
    page = re.sub(r"\{(TITLE|DATA)\}", lambda m: fill[m.group(1)], TEMPLATE)
    out = d / PAGE
    out.write_text(page, encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", type=Path, help="a folder of results (an --out folder)")
    ap.add_argument("--original", type=Path, help="the image they were edited from, shown first")
    ap.add_argument("--title", help="page title (default: the folder's name)")
    a = ap.parse_args()
    if a.original and not a.original.is_file():
        print(f"No such image: {a.original}")
        return 2
    out = write(a.dir, a.original, a.title)
    if not out:
        print(f"No images in {a.dir}")
        return 1
    print(out)
    return 0


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{TITLE}: compare</title>
<style>
:root{--bg:#121116;--surface:#1d1b22;--fg:#ece9f1;--muted:#9a95a5;--line:#34313d;
  --accent:#f0679a;--accent-ink:#1a0f14;color-scheme:dark}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--fg);font:15px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;
  display:flex;flex-direction:column;overflow:hidden}
header{display:flex;flex-direction:column;gap:8px;padding:8px 16px 10px}
.top{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 14px}
h1{font-size:16px;font-weight:600;margin:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:40ch}
.tabs{display:flex;flex-wrap:wrap;justify-content:center;gap:8px}
.tabs button{font:600 19.5px system-ui,sans-serif;border:1px solid var(--line);background:var(--surface);color:var(--fg);
  border-radius:999px;padding:6px 18px 6px 8px;cursor:pointer;display:flex;align-items:center;gap:10px}
.tabs button kbd{font:600 18px ui-monospace,Consolas,monospace;min-width:30px;height:30px;display:grid;place-items:center;
  border-radius:999px;background:var(--line);color:var(--fg)}
.tabs button.peek{border-color:var(--accent)}
.tabs button[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.tabs button[aria-pressed="true"] kbd{background:var(--accent-ink);color:var(--accent)}
.tabs button:focus-visible{outline:2px solid var(--fg);outline-offset:2px}
.hint{color:var(--muted);font-size:12.5px;margin-left:auto}
.stage{flex:1;min-height:0;overflow:hidden;display:grid;place-items:center;padding:0 16px 12px}
.stage.zoom{overflow:auto;place-items:start;padding:0}
.viewer{position:relative;user-select:none;-webkit-user-select:none;touch-action:manipulation;cursor:zoom-in}
.zoom .viewer{cursor:grab;margin:auto}
.viewer img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;visibility:hidden;pointer-events:none}
.viewer img.on{visibility:visible}
.tag{position:fixed;left:24px;bottom:22px;background:rgba(0,0,0,.65);color:#fff;font:600 13px system-ui,sans-serif;
  padding:4px 10px;border-radius:999px;pointer-events:none}
</style>
</head>
<body>
<header>
  <div class="top">
    <h1>{TITLE}</h1>
    <span class="hint">1, 2, 3&hellip; or &larr; &rarr; switch<span id="holdhint"> &middot; Space: original (tap to switch, hold to peek) &middot; hold the photo: original</span> &middot; Z or double-click: full size</span>
  </div>
  <div class="tabs" id="tabs" role="group" aria-label="Choose image"></div>
</header>
<div class="stage" id="stage"><div class="viewer" id="viewer"></div></div>
<span class="tag" id="tag"></span>
<script>
(function(){
  var ITEMS = {DATA};
  var tabs = document.getElementById('tabs'), viewer = document.getElementById('viewer');
  var stage = document.getElementById('stage'), tag = document.getElementById('tag');
  var imgs = [], btns = [], cur = 0, shown = 0, zoom = false, peek = false, peekAt = 0;
  var orig = ITEMS.findIndex(function(it){ return it.original; });
  if (orig < 0) document.getElementById('holdhint').hidden = true;  // nothing to hold for
  ITEMS.forEach(function(it, i){
    var im = new Image(); im.src = it.src; im.alt = it.label; im.decoding = 'sync';
    im.addEventListener('load', layout);
    viewer.appendChild(im); imgs.push(im);
    var b = document.createElement('button');
    b.type = 'button'; b.title = it.file;
    if (it.key) { var k = document.createElement('kbd'); k.textContent = it.key.toUpperCase(); b.appendChild(k); }
    b.appendChild(document.createTextNode(it.label));
    b.addEventListener('click', function(){ pick(i); b.blur(); });
    tabs.appendChild(b); btns.push(b);
  });
  var bw = Math.max.apply(null, btns.map(function(b){ return b.offsetWidth; }));
  btns.forEach(function(b){ b.style.minWidth = bw + 'px'; b.style.justifyContent = 'center'; });
  function show(i){
    shown = i;
    btns.forEach(function(b, k){ b.classList.toggle('peek', k === i && k !== cur); });
    imgs.forEach(function(im, k){ im.classList.toggle('on', k === i); });
    var im = imgs[i];
    tag.textContent = ITEMS[i].label + (im.naturalWidth ? '  ' + im.naturalWidth + ' \\u00d7 ' + im.naturalHeight : '');
  }
  function pick(i){
    cur = i; peek = false;
    btns.forEach(function(b, k){ b.setAttribute('aria-pressed', k === i ? 'true' : 'false'); });
    show(i);
    try { history.replaceState(null, '', '#' + (i + 1)); } catch (e) {}
  }
  function ratio(){  // the original's proportions, else the first image that has loaded
    var order = (orig < 0 ? [] : [orig]).concat(imgs.map(function(_, k){ return k; }));
    for (var j = 0; j < order.length; j++) { var im = imgs[order[j]]; if (im.naturalWidth) return im.naturalWidth / im.naturalHeight; }
    return 0;
  }
  function layout(){
    var r = ratio(); if (!r) return;
    var w, h;
    if (zoom) {  // every image at the size of the largest, so they still line up
      w = Math.max.apply(null, imgs.map(function(im){ return im.naturalWidth || 0; })); h = w / r;
    } else {
      var aw = stage.clientWidth - 32, ah = stage.clientHeight - 12;
      w = Math.min(aw, ah * r); h = w / r;
    }
    viewer.style.width = Math.round(w) + 'px'; viewer.style.height = Math.round(h) + 'px';
    show(shown);
  }
  function setZoom(on, e){
    var fx = .5, fy = .5;
    if (e) { var b = viewer.getBoundingClientRect(); fx = (e.clientX - b.left) / b.width; fy = (e.clientY - b.top) / b.height; }
    zoom = on; stage.classList.toggle('zoom', on); layout();
    if (on) {
      stage.scrollLeft = fx * viewer.offsetWidth - stage.clientWidth / 2;
      stage.scrollTop = fy * viewer.offsetHeight - stage.clientHeight / 2;
    }
  }
  // Hold the photo: the original. In full size, dragging pans instead.
  var down = null;
  viewer.addEventListener('pointerdown', function(e){
    if (e.button !== 0) return;
    down = {x: e.clientX, y: e.clientY, sl: stage.scrollLeft, st: stage.scrollTop, pan: false};
    viewer.setPointerCapture(e.pointerId); if (orig >= 0) show(orig);
  });
  viewer.addEventListener('pointermove', function(e){
    if (!down || !zoom) return;
    var dx = e.clientX - down.x, dy = e.clientY - down.y;
    if (!down.pan && Math.abs(dx) + Math.abs(dy) > 4) { down.pan = true; show(cur); }
    if (down.pan) { stage.scrollLeft = down.sl - dx; stage.scrollTop = down.st - dy; }
  });
  ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(function(t){
    viewer.addEventListener(t, function(){ if (down) { down = null; peek = false; show(cur); } });
  });
  viewer.addEventListener('dblclick', function(e){ setZoom(!zoom, e); });
  viewer.addEventListener('contextmenu', function(e){ e.preventDefault(); });
  document.addEventListener('keydown', function(e){
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    var k = e.key.toLowerCase(), n = ITEMS.length;
    var i = ITEMS.findIndex(function(it){ return it.key === k; });
    if (i >= 0) pick(i);
    else if (k === 'arrowright') pick((cur + 1) % n);
    else if (k === 'arrowleft') pick((cur + n - 1) % n);
    else if (k === ' ') {  // a tap switches to the original and back; a hold shows it until released
      if (!e.repeat && orig >= 0) { peek = !peek; peekAt = Date.now(); show(peek ? orig : cur); }
    }
    else if (k === 'z') setZoom(!zoom);
    else if (k === 'escape' && zoom) setZoom(false);
    else return;
    e.preventDefault();
  });
  document.addEventListener('keyup', function(e){
    if (e.key === ' ' && peek && Date.now() - peekAt > 300) { peek = false; show(cur); }
  });
  window.addEventListener('blur', function(){ peek = false; show(cur); });
  window.addEventListener('resize', layout);
  var start = parseInt((location.hash || '').slice(1), 10) - 1;
  pick(start >= 0 && start < ITEMS.length ? start : Math.min(1, ITEMS.length - 1));
  layout();
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
