# Model licensing — read before using output commercially

**This repository contains no model weights.** `install.ps1` downloads them from
HuggingFace at install time. They are covered by their own licence, which is *not* the
MIT licence that covers the code here.

## Qwen-Image-2.1

Released by Alibaba's Qwen team under the **Qwen Research License Agreement**, not Apache
or MIT. The research licence restricts commercial use. If you intend to use generated
images in a product, in client work, or anywhere revenue-generating, read the licence on
the model card first and seek your own advice:

- <https://huggingface.co/Qwen/Qwen-Image-2.1>
- <https://github.com/QwenLM/Qwen-Image-2.1>

The quantized builds this repo downloads come from
<https://huggingface.co/Comfy-Org/Qwen-Image-2.1> and inherit the same terms.

This is a repackaging of the upstream licence, not legal advice, and it can go stale —
check the model card for the current terms.

## ComfyUI

Cloned at install time, not vendored here. Licensed **GPL-3.0**.

The node in `custom_nodes/` is written against ComfyUI's public extension API and is
distributed separately from ComfyUI itself. If you redistribute a bundle that includes
ComfyUI, GPL-3.0 obligations apply to that bundle.

## PyTorch and other dependencies

Installed from PyPI and the PyTorch wheel index under their own licences (mostly BSD/MIT).
None are redistributed here.

## Your generated images

Whatever the model licence permits. Note that saved PNGs embed the prompt, seed and parent
image by default — useful for reproducing your own work, worth knowing before sharing
files publicly. See PRIVACY.md for how to turn that off.
