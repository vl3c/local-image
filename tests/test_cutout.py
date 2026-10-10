"""Tests for scripts/cutout.py on synthetic images. Needs numpy, scipy and Pillow:

    ComfyUI/.venv/Scripts/python.exe -m unittest discover tests
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import cutout  # noqa: E402

W = H = 400


def disc_scene(bg=(255, 255, 255), fg=(15, 15, 15)) -> Image.Image:
    """A disc (r=120 at 200,200) with a big hole (r=40) and a pinhole, a stray speck,
    a thin rod sticking out to the right, and a soft grey shadow below."""
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    shade = tuple(int(b * 0.85 + f * 0.15) for b, f in zip(bg, fg))
    d.ellipse((90, 330, 310, 370), fill=shade)          # shadow: faint, must stay background
    d.ellipse((80, 80, 320, 320), fill=fg)               # the object
    d.ellipse((160, 160, 240, 240), fill=bg)             # a real hole, 40 px radius
    d.ellipse((259, 199, 262, 202), fill=bg)             # a pinhole
    d.rectangle((320, 197, 390, 202), fill=fg)           # a 6 px rod
    d.ellipse((20, 20, 26, 26), fill=fg)                 # a speck
    return im


def args(**kw):
    base = dict(keep=0, min_part=0.01, open=0, close=0, fill_holes=0.002, smooth=1.0, simplify=0.3, hard=False)
    base.update(kw)
    return type("Args", (), base)()


def run(im: Image.Image, **kw):
    notes: list[str] = []
    mask, how = cutout.raw_mask(im, notes)
    mask = cutout.clean(mask, args(**kw), notes)
    return mask, how, notes


class Mask(unittest.TestCase):
    def test_shadow_and_speck_are_dropped_hole_kept_pinhole_filled(self):
        mask, how, _ = run(disc_scene())
        self.assertEqual(how["source"], "colour")
        self.assertEqual(how["background"], [255, 255, 255])
        self.assertFalse(mask[350, 200], "the faint shadow was taken as object")
        self.assertFalse(mask[23, 23], "the speck survived")
        self.assertFalse(mask[200, 200], "the big hole was filled")
        self.assertTrue(mask[200, 260], "the pinhole was not filled")
        self.assertTrue(mask[200, 360], "without --open the rod should stay")

    def test_open_removes_the_rod(self):
        mask, _, _ = run(disc_scene(), open=5)
        self.assertFalse(mask[200, 360])
        self.assertTrue(mask[200, 100])

    def test_fill_all_holes(self):
        mask, _, _ = run(disc_scene(), fill_holes=1)
        self.assertTrue(mask[200, 200])

    def test_light_object_on_dark_coloured_background(self):
        mask, how, _ = run(disc_scene(bg=(20, 40, 90), fg=(240, 230, 200)))
        self.assertEqual(how["background"], [20, 40, 90])
        self.assertTrue(mask[200, 100])
        self.assertFalse(mask[200, 200])

    def test_keep_two_and_the_warning_for_a_dropped_large_part(self):
        im = Image.new("RGB", (W, H), "white")
        d = ImageDraw.Draw(im)
        d.rectangle((40, 40, 180, 360), fill="black")
        d.rectangle((220, 40, 360, 300), fill="black")
        mask, _, notes = run(im)
        self.assertTrue(mask[100, 300], "by default a sizeable second part stays")
        mask, _, notes = run(im, keep=1)
        self.assertFalse(mask[100, 300])
        self.assertTrue(any("--keep 2" in n for n in notes))
        mask, _, notes = run(im, keep=2)
        self.assertTrue(mask[100, 300])
        self.assertFalse(notes)

    def test_real_transparency_is_used_as_is(self):
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse((100, 100, 300, 300), fill=(250, 250, 250, 255))
        mask, how, _ = run(im)
        self.assertEqual(how["source"], "alpha")
        self.assertTrue(mask[200, 200])
        self.assertFalse(mask[50, 50])

    def test_near_opaque_render_alpha_is_ignored(self):
        im = disc_scene().convert("RGBA")
        a = np.asarray(im).copy()
        a[..., 3] = 240  # what the VAE gives an "opaque" render
        _, how, _ = run(Image.fromarray(a))
        self.assertEqual(how["source"], "colour")

    def test_busy_background_warns(self):
        rng = np.random.default_rng(0)
        im = Image.fromarray(rng.integers(0, 255, (H, W, 3), dtype=np.uint8))
        _, _, notes = run(im)
        self.assertTrue(any("isn't plain" in n for n in notes))


class Contour(unittest.TestCase):
    def test_square_lands_on_pixel_edges(self):
        field = np.zeros((10, 10), np.float32)
        field[2:6, 3:8] = 1  # rows 2-5, columns 3-7
        (loop,) = cutout.march(field)
        self.assertAlmostEqual(loop[:, 0].min(), 3.0)
        self.assertAlmostEqual(loop[:, 0].max(), 8.0)
        self.assertAlmostEqual(loop[:, 1].min(), 2.0)
        self.assertAlmostEqual(loop[:, 1].max(), 6.0)

    def test_object_touching_the_frame_still_closes(self):
        field = np.zeros((10, 10), np.float32)
        field[:, :4] = 1
        loops = cutout.march(field)
        self.assertEqual(len(loops), 1)
        self.assertAlmostEqual(abs(cutout.signed_area(loops[0])), 4 * 10, delta=2)

    def test_saddle_cells_make_two_loops(self):
        field = np.zeros((6, 6), np.float32)
        field[1:3, 1:3] = 1
        field[3:5, 3:5] = 1  # touching only at a corner
        self.assertEqual(len(cutout.march(field)), 2)

    def test_disc_with_hole_outline_and_orientation(self):
        mask, _, _ = run(disc_scene(), open=5)
        from scipy import ndimage
        loops = cutout.contours(ndimage.gaussian_filter(mask.astype(np.float32), 1.0), 0.3)
        self.assertEqual([c["kind"] for c in loops], ["outer", "hole"])
        outer, hole = loops
        self.assertAlmostEqual(outer["area"], math.pi * 120 ** 2, delta=0.02 * math.pi * 120 ** 2)
        self.assertAlmostEqual(hole["area"], math.pi * 40 ** 2, delta=0.05 * math.pi * 40 ** 2)
        # outer clockwise on screen (positive shoelace with y down), hole the other way
        self.assertGreater(cutout.signed_area(np.array(outer["points"])), 0)
        self.assertLess(cutout.signed_area(np.array(hole["points"])), 0)
        # simplification should leave far fewer points than the raw trace
        self.assertLess(len(outer["points"]), 2 * math.pi * 120)


class CommandLine(unittest.TestCase):
    def test_writes_all_five_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "disc.png"
            disc_scene().save(src)
            out = Path(tmp) / "out"
            r = subprocess.run([sys.executable, str(SCRIPTS / "cutout.py"), str(src), "--out", str(out)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            for suffix in ("cutout.png", "mask.png", "contour.svg", "contour.json", "check.png"):
                self.assertTrue((out / f"disc_{suffix}").is_file(), suffix)
            cut = Image.open(out / "disc_cutout.png")
            self.assertEqual(cut.mode, "RGBA")
            self.assertEqual(cut.getpixel((5, 5))[3], 0)
            self.assertEqual(cut.getpixel((100, 200))[3], 255)
            data = json.loads((out / "disc_contour.json").read_text())
            self.assertEqual((data["width"], data["height"]), (W, H))
            self.assertIn('fill-rule="evenodd"', (out / "disc_contour.svg").read_text())

    def test_blank_image_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "blank.png"
            Image.new("RGB", (64, 64), "white").save(src)
            r = subprocess.run([sys.executable, str(SCRIPTS / "cutout.py"), str(src), "--out", tmp],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("no object", r.stdout)


if __name__ == "__main__":
    unittest.main()
