# Model licensing — read this before relying on anything you generate

**This repository contains no model weights.** `install.ps1` downloads them from
HuggingFace at install time. They carry their own licence, which is *not* the MIT licence
that covers the code here, and it is considerably more restrictive than "MIT with a
commercial-use footnote".

## Qwen-Image-2.1 — Qwen Research License Agreement

Released by Hangzhou Tongyi Laboratory Technology Co., Ltd. The grant is **not** "you may
do anything except sell it". It is narrower. Quoting the agreement (release date
2026-09-20):

> **1.i** "Non-Commercial" shall mean for research or evaluation purposes only.

> **2.a** You are granted a non-exclusive, worldwide, non-transferable and royalty-free
> limited license […] to use, reproduce, distribute, copy, create derivative works of,
> and make modifications to the Materials **FOR NON-COMMERCIAL PURPOSES ONLY.**

> **2.b** You shall not use the Materials for any commercial purpose without obtaining a
> separate commercial license from us. If you wish to use the Materials commercially, you
> shall request a license from us at model-business@notice.qwencloud.com.

Read those two definitions together and the permitted scope is *research or evaluation*.
That is a narrower category than "personal, non-paid use" — which means the obvious hobby
use case for this repo, editing your own photos for fun, is not clearly inside the grant.
Nobody is likely to come after you for it, but do not mistake "non-commercial" here for
the broader thing that phrase usually means.

Other obligations worth knowing:

- **§4.b** If you use the Materials or their outputs to train, fine-tune or improve an AI
  model that you then distribute, you must prominently display "Built with Qwen" or
  "Improved using Qwen".
- **§4.c** You may not use "Qwen" as the primary name of a derivative work or product.
  Descriptive use ("fine-tuned from Qwen Image") is fine.
- **§3** If you redistribute the weights, you must pass on a copy of the agreement, mark
  modified files, and include the required attribution notice. This repo does not
  redistribute them, so that does not apply to you as a user of it.
- **§8** Governed by the laws of China, exclusive jurisdiction in Hangzhou.

Current text: <https://huggingface.co/Qwen/Qwen-Image-2.1> (the `LICENSE` file in that
repo). The agreement was published the same week this repo was written, so check the
model card for the current version rather than trusting this summary.

**This is a summary for orientation, not legal advice.** If money is involved anywhere
near your use of this, read the agreement yourself and take proper advice.

## ComfyUI — GPL-3.0

Cloned at install time, not vendored here. GPL-3.0 (not "or later").

`custom_nodes/qwen_simple_ui.py` is original work, MIT-licensed, that references ComfyUI
only through its public extension API. The combination happens on your machine at install
time and is never redistributed, so no GPL distribution obligation is triggered for you or
for this repo. MIT is GPL-compatible, so anyone who *does* choose to redistribute a bundle
containing both simply applies GPL-3.0 to that bundle — the MIT grant permits exactly
that. This is the same arrangement the wider ComfyUI custom-node ecosystem uses.

To remove even a purist objection: the author additionally offers
`custom_nodes/qwen_simple_ui.py` under **GPL-3.0 at your option**, so you may treat it as
GPL if that simplifies redistribution for you.

## PyTorch and other dependencies

Installed from PyPI and the PyTorch wheel index under their own licences (mostly BSD/MIT).
None are redistributed here.

## Your generated images

Governed by the Qwen agreement above, not by this repo's MIT licence.

Note also that saved PNGs embed the prompt, seed and parent image by default. Useful for
reproducing your own work; worth knowing before you share the files. See PRIVACY.md for
how to turn that off.
