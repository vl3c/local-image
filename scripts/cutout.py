"""Cut one object out of a plain background: a clean mask, a transparent PNG and its contour.

Made for silhouette work: get a mask you can trace without hand cleanup. An image with
real transparency is cut along its alpha (Qwen-Image-2.1 draws one when the prompt asks for
"a fully transparent background, PNG with alpha channel", which generate.py --cutout does).
Otherwise any plain background works, light or dark or coloured.

    python scripts/cutout.py fist.png --out cut/
    python scripts/cutout.py fist.png --out cut/ --open 17         # shave off a rod up to ~32 px wide
    python scripts/cutout.py rifle.png --out cut/ --fill-holes 0   # keep every hole, however small
    python scripts/cutout.py drum.png --out cut/ --keep 1          # only the biggest part, no sticks

Needs numpy, scipy and Pillow, which ComfyUI's own environment already has, so run it
with that Python: ComfyUI/.venv/Scripts/python.exe. generate.py --cutout does this for you.

For each image, NAME.png, it writes into --out:

    NAME_cutout.png    the image with the background made transparent (soft edge)
    NAME_mask.png      the mask: white object, black background, hard edge
    NAME_contour.svg   the outline as one even-odd path, same pixel grid as the PNG
    NAME_contour.json  the same outline as point lists, outer loops and holes marked
    NAME_check.png     the cut-out over a checkerboard with the outline in red:
                       look at this one to judge the result

How it works: with real transparency, alpha >= 50% is the object. Otherwise the background
colour is the median of the image border, and every pixel's colour distance from it is
thresholded automatically (Otsu), so faint shadows and noise stay background. Then the cleanup: opening and closing if asked, keep the largest part,
drop specks (parts under 1% of the largest), fill pinholes, a light blur that rounds off
the pixel stairs. Separate parts that are big enough all stay: an antenna the model drew
with a gap is still part of the object, and the check image shows it. The contour is traced
on that blurred mask, so its points are sub-pixel and smooth.

Exit status: 0 done (warnings are printed but don't fail), 1 an image had no object or
couldn't be read, 2 bad arguments.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw
    from scipy import ndimage
except ImportError as exc:  # run with a Python that lacks them
    sys.exit(f"cutout.py needs numpy, scipy and Pillow ({exc.name} is missing).\n"
             "Run it with ComfyUI's Python: ComfyUI/.venv/Scripts/python.exe scripts/cutout.py ...")


# --- the mask ---------------------------------------------------------------

def border_pixels(rgb: np.ndarray) -> np.ndarray:
    """The outer frame of the image, a few pixels deep, as an (N, 3) array."""
    h, w = rgb.shape[:2]
    b = max(2, min(h, w) // 100)
    return np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3),
                           rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])


def otsu(values: np.ndarray) -> float:
    """The threshold that best splits values into two groups."""
    hist, edges = np.histogram(values, bins=256)
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    s0 = np.cumsum(hist * centers)
    m0 = s0 / np.maximum(w0, 1)
    m1 = (s0[-1] - s0) / np.maximum(w1, 1)
    between = w0 * w1 * (m0 - m1) ** 2
    return float(centers[int(np.argmax(between))])


def disk(radius: int) -> np.ndarray:
    y, x = np.ogrid[-radius:radius + 1, -radius:radius + 1]
    return x * x + y * y <= radius * radius


def native_alpha(img: Image.Image) -> np.ndarray | None:
    """The image's own alpha, 0-1, if it has real transparency.

    Not the near-opaque alpha every render carries: that dips to ~230 in places but
    never makes a background."""
    if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
        alpha = np.asarray(img.convert("RGBA"))[..., 3]
        if (alpha < 128).mean() > 0.01:
            return alpha.astype(np.float32) / 255
    return None


def raw_mask(img: Image.Image, notes: list[str]) -> tuple[np.ndarray, dict]:
    """Object pixels before any cleanup, and how they were found."""
    alpha = native_alpha(img)
    if alpha is not None:
        return alpha >= 0.5, {"source": "alpha"}

    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    border = border_pixels(rgb)
    bg = np.median(border, axis=0)
    dist = np.sqrt(((rgb - bg) ** 2).sum(axis=-1))
    border_dist = np.sqrt(((border - bg) ** 2).sum(axis=-1))
    # How much the background itself varies. A low percentile, because an object that
    # runs off the frame (a wrist, a sleeve) fills part of the border.
    noise = float(np.percentile(border_dist, 60))

    t = otsu(dist)
    # Never cut into the background's own grain, whatever Otsu says.
    t = max(t, 2 * noise + 8)
    if noise > 30:
        notes.append(f"the background isn't plain (its colour varies by {noise:.0f}/441 along the border); "
                     "the cut may follow shading or texture")
    return dist > t, {"source": "colour", "background": [round(float(v)) for v in bg],
                      "threshold": round(t, 1)}


def clean(mask: np.ndarray, args, notes: list[str]) -> np.ndarray:
    if args.open:
        mask = ndimage.binary_opening(mask, structure=disk(args.open))
    if args.close:
        # Pad first, or closing pulls an object that touches the frame away from it.
        r = args.close
        mask = ndimage.binary_closing(np.pad(mask, r, mode="edge"), structure=disk(r))[r:-r, r:-r]

    labels, n = ndimage.label(mask, structure=np.ones((3, 3)))
    if not n:
        return mask
    areas = ndimage.sum_labels(mask, labels, index=np.arange(1, n + 1))
    order = np.argsort(areas)[::-1]
    largest = areas[order[0]]
    keep = [i for i in order if areas[i] >= args.min_part * largest]
    if args.keep:
        dropped = keep[args.keep:]
        keep = keep[:args.keep]
        if dropped and areas[dropped[0]] >= 0.25 * largest:
            notes.append(f"dropped a second large part ({int(areas[dropped[0]])} px, "
                         f"{areas[dropped[0]] / largest:.0%} of the largest); "
                         f"use --keep {args.keep + 1} if it belongs")
    mask = np.isin(labels, np.array(keep) + 1)

    if args.fill_holes > 0:
        holes, n = ndimage.label(~mask)
        if n:
            hole_areas = ndimage.sum_labels(~mask, holes, index=np.arange(1, n + 1))
            edge = np.unique(np.concatenate([holes[0], holes[-1], holes[:, 0], holes[:, -1]]))
            limit = args.fill_holes * mask.sum()
            fill = [i + 1 for i in range(n) if i + 1 not in edge and hole_areas[i] <= limit]
            mask = mask | np.isin(holes, fill)
    return mask


# --- the contour -------------------------------------------------------------

def march(field: np.ndarray, level: float = 0.5) -> list[np.ndarray]:
    """Closed iso-lines of field at level, as (N, 2) arrays of x, y in pixel units.

    Marching squares on pixel centres, so a sample at row r, column c sits at
    (c + 0.5, r + 0.5) and the outline lines up with the image it came from.
    """
    f = np.pad(field, 1)  # zero all round, so every loop closes
    inside = f > level
    tl, tr = inside[:-1, :-1], inside[:-1, 1:]
    bl, br = inside[1:, :-1], inside[1:, 1:]
    case = tl * 8 + tr * 4 + br * 2 + bl * 1
    rows, cols = np.nonzero((case != 0) & (case != 15))

    def point(edge):
        kind, r, c = edge
        if kind == "h":  # between (r, c) and (r, c + 1)
            a, b = f[r, c], f[r, c + 1]
            return c + (level - a) / (b - a) - 0.5, r - 0.5
        a, b = f[r, c], f[r + 1, c]  # "v": between (r, c) and (r + 1, c)
        return c - 0.5, r + (level - a) / (b - a) - 0.5

    # Each crossed cell edge is a node; each cell adds one or two segments.
    links: dict[tuple, list[tuple]] = {}

    def link(a, b):
        links.setdefault(a, []).append(b)
        links.setdefault(b, []).append(a)

    for r, c in zip(rows.tolist(), cols.tolist()):
        k = int(case[r, c])
        T, R, B, L = ("h", r, c), ("v", r, c + 1), ("h", r + 1, c), ("v", r, c)
        if k in (5, 10):  # saddle: the centre decides which corners join
            centre = (f[r, c] + f[r, c + 1] + f[r + 1, c] + f[r + 1, c + 1]) / 4 > level
            # 5 is tr+bl inside, 10 is tl+br: cut off the two inside corners when the
            # centre is outside, the two outside corners when it is inside.
            if (k == 10) == centre:
                link(T, R); link(B, L)
            else:
                link(T, L); link(B, R)
            continue
        ends = [e for e, crossed in ((T, tl[r, c] != tr[r, c]), (R, tr[r, c] != br[r, c]),
                                     (B, bl[r, c] != br[r, c]), (L, tl[r, c] != bl[r, c])) if crossed]
        link(*ends)

    loops, seen = [], set()
    for start in links:
        if start in seen:
            continue
        loop, prev, cur = [], None, start
        while cur not in seen:
            seen.add(cur)
            loop.append(point(cur))
            nxt = [n for n in links[cur] if n != prev]
            # A node joined twice to the same neighbour only happens in 2-node loops.
            prev, cur = cur, (nxt[0] if nxt else links[cur][0])
        if len(loop) >= 3:
            loops.append(np.array(loop))
    return loops


def signed_area(p: np.ndarray) -> float:
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def inside_polygon(pt, poly: np.ndarray) -> bool:
    x, y = pt
    xs, ys = poly[:, 0], poly[:, 1]
    xs2, ys2 = np.roll(xs, -1), np.roll(ys, -1)
    crosses = ((ys > y) != (ys2 > y)) & (x < (xs2 - xs) * (y - ys) / np.where(ys2 == ys, 1, ys2 - ys) + xs)
    return bool(crosses.sum() % 2)


def simplify(p: np.ndarray, tol: float) -> np.ndarray:
    """Ramer-Douglas-Peucker on a closed loop: drop points within tol of the line."""
    if tol <= 0 or len(p) < 8:
        return p
    # Split the loop at its two most distant points and simplify each half.
    far = int(np.argmax(((p - p[0]) ** 2).sum(axis=1)))
    halves = [np.vstack([p[:far + 1]]), np.vstack([p[far:], p[:1]])]
    out = []
    for h in halves:
        keep = np.zeros(len(h), bool)
        keep[[0, -1]] = True
        stack = [(0, len(h) - 1)]
        while stack:
            a, b = stack.pop()
            if b - a < 2:
                continue
            seg = h[b] - h[a]
            n = np.hypot(*seg) or 1.0
            d = np.abs(seg[0] * (h[a + 1:b, 1] - h[a, 1]) - seg[1] * (h[a + 1:b, 0] - h[a, 0])) / n
            i = int(np.argmax(d))
            if d[i] > tol:
                keep[a + 1 + i] = True
                stack += [(a, a + 1 + i), (a + 1 + i, b)]
        out.append(h[keep][:-1])
    return np.vstack(out)


def contours(field: np.ndarray, tol: float) -> list[dict]:
    # The blur can pinch a hair-thin neck into a separate crumb of a few px²: not a part.
    loops = [p for p in march(field) if abs(signed_area(p)) >= 10]
    result = []
    for i, p in enumerate(loops):
        depth = sum(inside_polygon(p[0], q) for j, q in enumerate(loops) if j != i)
        hole = depth % 2 == 1
        p = simplify(p, tol)
        # Outer loops clockwise on screen (y down), holes counter-clockwise.
        if (signed_area(p) > 0) == hole:
            p = p[::-1]
        result.append({"kind": "hole" if hole else "outer", "area": round(abs(signed_area(p)), 1),
                       "points": [[round(float(x), 2), round(float(y), 2)] for x, y in p]})
    result.sort(key=lambda c: (c["kind"] != "outer", -c["area"]))
    return result


# --- output -------------------------------------------------------------------

def svg(loops: list[dict], w: int, h: int) -> str:
    d = " ".join("M" + " L".join(f"{x:g},{y:g}" for x, y in c["points"]) + " Z" for c in loops)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">\n'
            f'  <path fill="#000" fill-rule="evenodd" d="{d}"/>\n</svg>\n')


def check_image(rgb: Image.Image, alpha: np.ndarray, loops: list[dict]) -> Image.Image:
    w, h = rgb.size
    yy, xx = np.mgrid[0:h, 0:w]
    checker = np.where(((xx // 16 + yy // 16) % 2)[..., None] == 0, 205, 245).astype(np.uint8)
    board = Image.fromarray(np.repeat(checker, 3, axis=2))
    board.paste(rgb, (0, 0), Image.fromarray((alpha * 255).astype(np.uint8)))
    draw = ImageDraw.Draw(board)
    for c in loops:
        pts = [tuple(p) for p in c["points"]]
        draw.line(pts + pts[:1], fill=(230, 30, 30) if c["kind"] == "outer" else (30, 90, 230),
                  width=max(2, min(w, h) // 400))
    return board


def process(path: Path, args) -> bool:
    notes: list[str] = []
    try:
        img = Image.open(path)
        img.load()
    except OSError as exc:
        print(f"{path}: can't read it ({exc})")
        return False

    mask, how = raw_mask(img, notes)
    mask = clean(mask, args, notes)
    if not mask.any():
        print(f"{path}: no object found against the background")
        return False

    field = ndimage.gaussian_filter(mask.astype(np.float32), args.smooth) if args.smooth else mask.astype(np.float32)
    hard = field > 0.5
    h, w = mask.shape
    share = hard.mean()
    if hard[0].any() or hard[-1].any() or hard[:, 0].any() or hard[:, -1].any():
        notes.append("the object touches the frame edge, so it's probably cropped")
    if share < 0.005:
        notes.append(f"the object covers only {share:.1%} of the image")
    elif share > 0.85:
        notes.append(f"the object covers {share:.0%} of the image: is the background really plain?")

    loops = contours(field, args.simplify)
    alpha = np.clip(field, 0, 1) if not args.hard else hard.astype(np.float32)
    native = native_alpha(img)
    if native is not None and not args.hard:
        # Keep the model's own soft edge where the cleanup kept the object, and the
        # cleaned mask's inside (filled pinholes, joined gaps) fully opaque.
        near = ndimage.binary_dilation(mask, iterations=2)
        alpha = np.maximum(native * near, ndimage.binary_erosion(mask).astype(np.float32))

    # Give fully transparent pixels the colour of the nearest solid one. Under a
    # transparent background a render holds junk colour (often magenta) that bleeds into
    # the edge as soon as anything resizes or filters the image without premultiplying.
    rgb_arr = np.asarray(img.convert("RGB")).copy()
    solid = alpha >= 0.5
    _, (iy, ix) = ndimage.distance_transform_edt(~solid, return_indices=True)
    clear = alpha < 1 / 255
    rgb_arr[clear] = rgb_arr[iy[clear], ix[clear]]
    rgb = Image.fromarray(rgb_arr)

    out, stem = args.out, path.stem.rstrip("_") or path.stem  # ComfyUI names end in "_"
    out.mkdir(parents=True, exist_ok=True)
    cut = rgb.copy()
    cut.putalpha(Image.fromarray((alpha * 255).round().astype(np.uint8)))
    cut.save(out / f"{stem}_cutout.png")
    Image.fromarray(hard.astype(np.uint8) * 255).save(out / f"{stem}_mask.png")
    (out / f"{stem}_contour.svg").write_text(svg(loops, w, h), encoding="utf-8")
    (out / f"{stem}_contour.json").write_text(json.dumps(
        {"width": w, "height": h, **how, "contours": loops}, separators=(",", ":")), encoding="utf-8")
    check_image(rgb, alpha, loops).save(out / f"{stem}_check.png")

    outer = sum(c["kind"] == "outer" for c in loops)
    holes = len(loops) - outer
    print(f"{path.name}: {outer} outline{'s' * (outer != 1)}, {holes} hole{'s' * (holes != 1)}, "
          f"{sum(len(c['points']) for c in loops)} points, object {share:.0%} of the frame -> "
          f"{(out / f'{stem}_check.png').resolve()}")
    for n in notes:
        print(f"  warning: {n}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", type=Path, metavar="IMG")
    ap.add_argument("--out", type=Path, required=True, metavar="DIR", help="where the results go")
    ap.add_argument("--keep", type=int, default=0, metavar="N",
                    help="keep only the N largest parts (default 0: every part above --min-part)")
    ap.add_argument("--min-part", type=float, default=0.01, metavar="F",
                    help="drop parts smaller than this fraction of the largest (default 0.01)")
    ap.add_argument("--open", type=int, default=0, metavar="R",
                    help="remove bits thinner than about 2R px: rods, wires, stray hairs")
    ap.add_argument("--close", type=int, default=0, metavar="R",
                    help="bridge gaps narrower than about 2R px")
    ap.add_argument("--fill-holes", type=float, default=0.002, metavar="F",
                    help="fill holes up to this fraction of the object's area (default 0.002, "
                         "pinholes only); 0 keeps every hole, 1 fills them all")
    ap.add_argument("--smooth", type=float, default=1.0, metavar="S",
                    help="blur radius that rounds off pixel steps (default 1.0; 0 for none)")
    ap.add_argument("--simplify", type=float, default=0.3, metavar="PX",
                    help="drop contour points within PX of the line (default 0.3; 0 keeps all)")
    ap.add_argument("--hard", action="store_true", help="hard-edged alpha in the cut-out PNG")
    args = ap.parse_args()

    if args.keep < 0 or args.open < 0 or args.close < 0 or args.smooth < 0 or args.simplify < 0 \
            or not 0 <= args.fill_holes <= 1 or not 0 <= args.min_part <= 1:
        print("--keep, --open, --close, --smooth and --simplify can't be negative; "
              "--fill-holes and --min-part go from 0 to 1")
        return 2
    missing = [str(p) for p in args.images if not p.is_file()]
    if missing:
        print("No such image: " + ", ".join(missing))
        return 2

    ok = [process(p, args) for p in args.images]
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
