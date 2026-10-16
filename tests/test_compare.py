"""Tests for scripts/compare.py and generate.py's use of it: which images the page lists, in what
order, under which labels and keys. Standard library only.

    python -m unittest discover tests
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import compare  # noqa: E402
import generate  # noqa: E402


def touch(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def items(page: Path) -> list[dict]:
    return json.loads(re.search(r"var ITEMS = (\[.*?\]);", page.read_text(encoding="utf-8")).group(1))


class Page(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def test_order_labels_keys_and_cutout_by_products(self):
        d = self.tmp / "drafts"
        for name in ("qwen21_00010_.png", "qwen21_00009_.png", "qwen21_edit_00002__1.png",
                     "qwen21_00009__mask.png", "qwen21_00009__cutout.png", "notes.txt"):
            touch(d / name)
        got = items(compare.write(d))
        self.assertEqual([i["label"] for i in got], ["00009", "00010", "Edit 00002 1"])
        self.assertEqual([i["key"] for i in got], ["1", "2", "3"])
        self.assertFalse(any(i["original"] for i in got))

    def test_original_first_kept_by_later_runs_and_never_listed_twice(self):
        d = self.tmp / "my edits"
        photo = touch(self.tmp / "photos" / "fată 1.jpg")
        touch(d / "qwen21_edit_00001_.png")
        got = items(compare.write(d, photo))
        self.assertEqual(got[0], {"src": "../photos/fat%C4%83%201.jpg", "label": "Original",
                                  "file": "fată 1.jpg", "original": True, "key": "1"})
        touch(d / "qwen21_edit_00002_.png")
        got = items(compare.write(d))                     # a later run without --edit keeps it
        self.assertEqual([i["label"] for i in got], ["Original", "Edit 00001", "Edit 00002"])
        inside = touch(d / "base.png")                    # the original inside the folder itself
        self.assertEqual([i["file"] for i in items(compare.write(d, inside))],
                         ["base.png", "qwen21_edit_00001_.png", "qwen21_edit_00002_.png"])

    def test_offline_escaped_and_needs_enough_images(self):
        d = self.tmp / "set"
        touch(d / "qwen21_00001_.png")
        self.assertIsNone(compare.write(d, min_images=2))
        self.assertFalse((d / "compare.html").exists())
        text = compare.write(d, title="a<b> {DATA}").read_text(encoding="utf-8")
        self.assertIn("<title>a&lt;b&gt; {DATA}: compare</title>", text)
        self.assertIsNone(re.search(r"(src|href)=[\"']?(https?:)?//|@import|url\(", text))
        many = self.tmp / "many"
        for n in range(25):
            touch(many / f"x_{n:02d}.png")
        keys = [i["key"] for i in items(compare.write(many))]
        self.assertEqual(keys[:10] + keys[10:20], list("1234567890") + list("qwertyuiop"))
        self.assertEqual(keys[20:], [""] * 5)


class FromGenerate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def run_it(self, **kw):
        args = SimpleNamespace(out=self.tmp / "out", edit=[], enhance=None, **kw)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            generate.write_compare(args)
        return out.getvalue()

    def test_two_results_get_a_page_one_does_not(self):
        touch(self.tmp / "out" / "qwen21_00001_.png")
        self.assertEqual(self.run_it(), "")
        touch(self.tmp / "out" / "qwen21_00002_.png")
        self.assertIn("compare: ", self.run_it())
        self.assertTrue((self.tmp / "out" / "compare.html").exists())

    def test_one_edit_and_its_source_get_a_page(self):
        touch(self.tmp / "out" / "qwen21_edit_00001_.png")
        src = touch(self.tmp / "photo.png")
        args = SimpleNamespace(out=self.tmp / "out", edit=[str(src)], enhance=None)
        with contextlib.redirect_stdout(io.StringIO()):
            generate.write_compare(args)
        self.assertEqual(items(self.tmp / "out" / "compare.html")[0]["src"], "../photo.png")

    def test_no_compare_needs_out(self):
        out = io.StringIO()
        with unittest.mock.patch.object(sys, "argv", ["generate.py", "x", "--no-compare"]), \
                contextlib.redirect_stdout(out):
            self.assertEqual(generate.main(), 2)
        self.assertIn("--no-compare only applies with --out", out.getvalue())


if __name__ == "__main__":
    unittest.main()
