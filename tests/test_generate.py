"""Tests for scripts/generate.py that need no server and no GPU: the graph it builds, its
argument checks, and when it starts the server. Standard library only.

    python -m unittest discover tests
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import generate  # noqa: E402


def run_main(*argv: str):
    """main() with these arguments; returns (exit status, printed text)."""
    out = io.StringIO()
    with mock.patch.object(sys, "argv", ["generate.py", *argv]), contextlib.redirect_stdout(out):
        code = generate.main()
    return code, out.getvalue()


class FitSize(unittest.TestCase):
    def test_render_sizes(self):
        cases = {
            (1920, 1080): (1920, 1088),   # 16:9 HD: only 8 rows to crop
            (1080, 1920): (1088, 1920),
            (1280, 720): (1376, 768),     # small target: rendered up to ~1 MP, then scaled down
            (3840, 2160): (2048, 1152),   # 4K: capped at ~2.4 MP, then scaled up
            (64, 64): (1024, 1024),
            (1664, 928): (1664, 928),     # already a native size
        }
        for target, want in cases.items():
            got = generate.fit_render_size(*target)
            self.assertEqual(got, want, target)
            self.assertEqual((got[0] % 16, got[1] % 16), (0, 0))
            # the target's shape within rounding, so the cover-crop takes off very little
            self.assertAlmostEqual(got[0] / got[1], target[0] / target[1], delta=0.02 * target[0] / target[1])

    def test_parse_size(self):
        self.assertEqual(generate.parse_size("1920X1080"), (1920, 1080))
        for bad in ("19x", "0x10", "-5x10", "abc"):
            with self.assertRaises(ValueError):
                generate.parse_size(bad)


class Graph(unittest.TestCase):
    def args(self, **kw):
        base = dict(width=1024, height=1024, model=generate.DIFFUSION, encoder=generate.ENCODER,
                    prompt="p", scale=1328, seed=1, steps=20, count=1, denoise=0.45,
                    fit=None, rgb=False)
        base.update(kw)
        return SimpleNamespace(**base)

    def test_plain_graph_saves_the_decode(self):
        wf = generate.build(self.args(), [], None)
        self.assertEqual(wf["8"]["inputs"]["images"], ["7", 0])
        self.assertNotIn("30", wf)
        self.assertNotIn("31", wf)

    def test_fit_scales_then_drops_alpha(self):
        wf = generate.build(self.args(fit=(1920, 1080), rgb=True), [], None)
        self.assertEqual(wf["30"]["class_type"], "ImageScale")
        self.assertEqual(wf["30"]["inputs"]["image"], ["7", 0])
        self.assertEqual((wf["30"]["inputs"]["width"], wf["30"]["inputs"]["height"]), (1920, 1080))
        self.assertEqual(wf["30"]["inputs"]["crop"], "center")
        self.assertEqual(wf["31"]["class_type"], "SplitImageWithAlpha")
        self.assertEqual(wf["31"]["inputs"]["image"], ["30", 0])
        self.assertEqual(wf["8"]["inputs"]["images"], ["31", 0])

    def test_fit_keeping_alpha_and_after_an_edit(self):
        wf = generate.build(self.args(fit=(800, 600)), ["ref.png"], None)
        self.assertEqual(wf["8"]["inputs"]["images"], ["30", 0])
        self.assertNotIn("31", wf)
        self.assertEqual(wf["4"]["inputs"]["images.image_1"], ["100", 0])


class Arguments(unittest.TestCase):
    def test_bad_arguments_exit_2_before_any_server(self):
        with mock.patch.object(generate, "wait_for_server") as wait:
            for argv in (["x", "--fit", "19x"], ["x", "--size", "1000x1000"], ["x", "--cutout"],
                         ["x", "--cutout", "--enhance", __file__, "--out", "d"],
                         ["x", "--keep-metadata"], ["x", "--edit", "no-such.png"]):
                code, _ = run_main(*argv)
                self.assertEqual(code, 2, argv)
            wait.assert_not_called()

    def submitted(self, *argv):
        """The graph main() would submit for these arguments."""
        sent = {}

        def api(path, payload=None):
            sent["graph"] = payload["prompt"]
            return {"prompt_id": "id"}

        with mock.patch.object(generate, "wait_for_server", return_value=True), \
                mock.patch.object(generate, "api", side_effect=api), \
                mock.patch.object(generate, "wait_for_result", return_value=0):
            code, _ = run_main(*argv)
        self.assertEqual(code, 0)
        return sent["graph"]

    def test_fit_renders_near_and_flattens(self):
        wf = self.submitted("a city", "--fit", "1920x1080")
        self.assertEqual((wf["5"]["inputs"]["width"], wf["5"]["inputs"]["height"]), (1920, 1088))
        self.assertIn("31", wf)

    def test_explicit_size_wins_over_fit(self):
        wf = self.submitted("a city", "--fit", "1920x1080", "--size", "1664x928")
        self.assertEqual((wf["5"]["inputs"]["width"], wf["5"]["inputs"]["height"]), (1664, 928))

    def test_cutout_asks_for_alpha_and_keeps_it_even_with_fit(self):
        wf = self.submitted("a raised fist.", "--cutout", "--fit", "1920x1080", "--out", "d")
        prompt = wf["4"]["inputs"]["prompt"]
        self.assertTrue(prompt.startswith("a raised fist. Shown as one solid, pure black silhouette"))
        self.assertIn("fully transparent background, PNG with alpha channel", prompt)
        self.assertIn("30", wf)
        self.assertNotIn("31", wf, "--cutout must not drop the alpha")

    def test_cutout_object_mode(self):
        wf = self.submitted("a teacup", "--cutout", "object", "--out", "d")
        self.assertIn("One single object", wf["4"]["inputs"]["prompt"])


class Starting(unittest.TestCase):
    def test_no_start_fails_without_starting(self):
        with mock.patch.object(generate, "wait_for_server", return_value=False), \
                mock.patch.object(generate, "start_server") as start:
            code, text = run_main("x", "--no-start")
        self.assertEqual(code, 1)
        self.assertIn("Start it with start.cmd", text)
        start.assert_not_called()

    def test_starts_the_server_window_then_waits(self):
        with mock.patch.object(generate, "wait_for_server", side_effect=[False, True]) as wait, \
                mock.patch.object(generate, "start_server", return_value=None), \
                mock.patch.object(generate, "api", return_value={"prompt_id": "id"}), \
                mock.patch.object(generate, "wait_for_result", return_value=0):
            code, text = run_main("x")
        self.assertEqual(code, 0)
        self.assertIn("in its own window", text)
        self.assertEqual(wait.call_args_list[1].args, (generate.START_WAIT,))

    def test_reports_why_it_did_not_start(self):
        with mock.patch.object(generate, "wait_for_server", return_value=False), \
                mock.patch.object(generate, "start_server", return_value="the GPU is busy"):
            code, text = run_main("x")
        self.assertEqual(code, 1)
        self.assertIn("not starting one: the GPU is busy", text)

    def gpu(self, used_mb):
        return subprocess.CompletedProcess([], 0, stdout=f"{used_mb}\n", stderr="")

    def test_busy_gpu_means_no_start(self):
        with mock.patch.object(generate.Path, "is_file", return_value=True), \
                mock.patch.object(generate.subprocess, "run", return_value=self.gpu(10400)) as run:
            why = generate.start_server()
        self.assertIn("10.2 GB", why)
        self.assertEqual(run.call_count, 1, "only nvidia-smi should have run, not start.cmd")

    def test_free_gpu_runs_start_cmd(self):
        with mock.patch.object(generate.Path, "is_file", return_value=True), \
                mock.patch.object(generate.subprocess, "run", return_value=self.gpu(1700)) as run:
            self.assertIsNone(generate.start_server())
        cmd = run.call_args_list[-1].args[0]
        self.assertEqual(cmd[:2], ["cmd", "/c"])
        self.assertTrue(cmd[2].endswith("start.cmd"))
        self.assertEqual(cmd[3:], ["--no-browser"])

    def test_no_install_means_no_start(self):
        with mock.patch.object(generate.Path, "is_file", return_value=False), \
                mock.patch.object(generate.subprocess, "run") as run:
            self.assertIn("install.ps1", generate.start_server())
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
