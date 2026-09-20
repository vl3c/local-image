"""A one-page prompt box for Qwen-Image-2.1, served at http://127.0.0.1:8188/simple

Adds two things to ComfyUI:
  * EmptyQwenImage21Latent - a plain width/height empty latent for Qwen-Image 2.1
    (the built-in TextEncodeQwenImage21 only emits a square one), and
  * the /simple route below, which serves a single HTML page that builds the
    workflow in the browser and posts it to ComfyUI's own /prompt endpoint.

Same origin as ComfyUI, so there is no CORS setup and no second server to run.

The page supports plain text-to-image and reference-image editing. For editing it
feeds the VAE into TextEncodeQwenImage21 and takes that node's own latent output,
which is sized from the first reference - the node's docstring warns that any
other size shifts the edit. Reference slots are autogrow inputs, so in the API
format their keys are namespaced: "images.image_1", not "image_1".
"""

import torch

import comfy.model_management
import folder_paths
from aiohttp import web
from server import PromptServer


class EmptyQwenImage21Latent:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "width": ("INT", {"default": 1024, "min": 128, "max": 4096, "step": 16}),
            "height": ("INT", {"default": 1024, "min": 128, "max": 4096, "step": 16}),
            "batch_size": ("INT", {"default": 1, "min": 1, "max": 16}),
        }}

    RETURN_TYPES = ("LATENT",)
    FUNCTION = "generate"
    CATEGORY = "model/latent/qwen"

    def generate(self, width, height, batch_size=1):
        # 64 channels at a 16x spatial downscale, matching latent_formats.QwenImage21
        latent = torch.zeros([batch_size, 64, height // 16, width // 16],
                             device=comfy.model_management.intermediate_device())
        return ({"samples": latent},)


NODE_CLASS_MAPPINGS = {"EmptyQwenImage21Latent": EmptyQwenImage21Latent}
NODE_DISPLAY_NAME_MAPPINGS = {"EmptyQwenImage21Latent": "Empty Qwen Image 2.1 Latent"}


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Qwen Image</title>
<style>
  :root {
    --bg: #faf9f7; --panel: #ffffff; --ink: #1c1a17; --muted: #6b6560;
    --line: #e4e0da; --accent: #7c5cff; --accent-ink: #ffffff; --shadow: rgba(28,26,23,.08);
    --soft: #f2f0ec;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #17161a; --panel: #201f24; --ink: #ece9e4; --muted: #9a938c;
      --line: #322f38; --accent: #9a80ff; --accent-ink: #14121a; --shadow: rgba(0,0,0,.4);
      --soft: #191820;
    }
  }
  :root[data-theme="dark"] {
    --bg: #17161a; --panel: #201f24; --ink: #ece9e4; --muted: #9a938c;
    --line: #322f38; --accent: #9a80ff; --accent-ink: #14121a; --shadow: rgba(0,0,0,.4);
    --soft: #191820;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font: 15px/1.5 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  .wrap { max-width: 1080px; margin: 0 auto; padding: 32px 16px 80px; }
  h1 { font-size: 20px; margin: 0 0 2px; letter-spacing: -.01em; }
  .sub { color: var(--muted); font-size: 13px; margin: 0 0 24px; }
  .panel {
    background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
    padding: 18px; box-shadow: 0 1px 3px var(--shadow);
  }
  label { display: block; font-size: 12px; font-weight: 600; color: var(--muted);
          text-transform: uppercase; letter-spacing: .04em; margin-bottom: 6px; }
  textarea, input, select {
    width: 100%; background: var(--bg); color: var(--ink); font: inherit;
    border: 1px solid var(--line); border-radius: 9px; padding: 10px 12px;
  }
  textarea { min-height: 96px; resize: vertical; line-height: 1.45; }
  textarea:focus, input:focus, select:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
  .row { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-top: 14px; }
  .go {
    margin-top: 16px; width: 100%; padding: 13px; border: 0; border-radius: 10px;
    background: var(--accent); color: var(--accent-ink); font: 600 15px/1 inherit; cursor: pointer;
  }
  .go:disabled { opacity: .55; cursor: default; }
  details { margin-top: 14px; }
  summary { cursor: pointer; font-size: 13px; color: var(--muted); }
  details[open] summary { margin-bottom: 10px; }
  .status { margin-top: 16px; font-size: 13px; color: var(--muted); min-height: 20px; }
  .bar { height: 4px; background: var(--line); border-radius: 99px; overflow: hidden; margin-top: 8px; display: none; }
  .bar.on { display: block; }
  .bar i { display: block; height: 100%; width: 0; background: var(--accent); transition: width .15s; }

  /* reference strip */
  .refs { margin-top: 14px; }
  .drop {
    border: 1.5px dashed var(--line); border-radius: 11px; background: var(--soft);
    padding: 14px; text-align: center; color: var(--muted); font-size: 13px; cursor: pointer;
  }
  .drop:hover, .drop.over { border-color: var(--accent); color: var(--ink); }
  .drop b { color: var(--accent); font-weight: 600; }
  .thumbs { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
  .thumb { position: relative; width: 74px; height: 74px; border-radius: 9px; overflow: hidden;
           border: 1px solid var(--line); background: var(--soft); }
  .thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .thumb button {
    position: absolute; top: 3px; right: 3px; width: 19px; height: 19px; padding: 0;
    border: 0; border-radius: 50%; background: rgba(0,0,0,.66); color: #fff;
    font: 600 12px/19px sans-serif; cursor: pointer;
  }
  .mode { font-size: 12.5px; color: var(--muted); margin-top: 10px; }
  .mode b { color: var(--ink); font-weight: 600; }

  .shots { margin-top: 28px; display: grid; gap: 20px; }
  figure { margin: 0; background: var(--panel); border: 1px solid var(--line);
           border-radius: 14px; overflow: hidden; box-shadow: 0 1px 3px var(--shadow); }
  figure img { display: block; width: 100%; height: auto; background: var(--line); }
  figcaption { padding: 10px 14px; font-size: 12px; color: var(--muted);
               display: flex; justify-content: space-between; align-items: center; gap: 12px; }
  figcaption a { color: var(--accent); text-decoration: none; }
  .acts { display: flex; gap: 8px; align-items: center; }
  .acts button {
    border: 1px solid var(--line); background: var(--bg); color: var(--ink);
    border-radius: 7px; padding: 5px 10px; font: 600 12px/1 inherit; cursor: pointer;
  }
  .acts button:hover { border-color: var(--accent); color: var(--accent); }
  .err { color: #d1453b; white-space: pre-wrap; font-family: ui-monospace, monospace; font-size: 12px; }
  .hide { display: none; }
  @media (max-width: 600px) { .wrap { padding: 20px 16px 60px; } }
</style>
</head>
<body>
<div class="wrap">
  <h1>Qwen-Image-2.1</h1>
  <p class="sub">Type a prompt, press Generate. Add a reference image to edit instead.</p>

  <div class="panel">
    <label for="prompt">Prompt</label>
    <textarea id="prompt" placeholder="A neon shop sign that reads &quot;OPEN LATE&quot;, rainy night, reflections on wet pavement"></textarea>

    <div class="refs">
      <label>Reference images <span style="text-transform:none;font-weight:400">&mdash; optional, up to 10</span></label>
      <div class="drop" id="drop">
        <b>Choose files</b>, drag images here, or paste from the clipboard
      </div>
      <input type="file" id="file" accept="image/*" multiple class="hide">
      <div class="thumbs" id="thumbs"></div>
      <div class="mode" id="mode"></div>
    </div>

    <div class="row">
      <div id="sizeWrap">
        <label for="size">Size</label>
        <select id="size">
          <option value="1024x1024">Square &middot; 1024</option>
          <option value="1328x1328" selected>Square &middot; 1328</option>
          <option value="1664x928">Landscape 16:9 &middot; 1664</option>
          <option value="928x1664">Portrait 9:16 &middot; 1664</option>
          <option value="1472x1104">Landscape 4:3 &middot; 1472</option>
          <option value="1104x1472">Portrait 3:4 &middot; 1472</option>
          <option value="1584x1056">Landscape 3:2 &middot; 1584</option>
          <option value="2048x2048">Square &middot; 2048 (slow)</option>
        </select>
      </div>
      <div id="scaleWrap" class="hide">
        <label for="scale">Output scale</label>
        <select id="scale">
          <option value="1024">Standard &middot; 1024</option>
          <option value="1328" selected>Larger &middot; 1328</option>
          <option value="1664">Largest &middot; 1664 (slow)</option>
          <option value="0">Keep original size</option>
        </select>
      </div>
      <div>
        <label for="quality">Quality</label>
        <select id="quality">
          <option value="20">Preview &middot; fast</option>
          <option value="40" selected>Full &middot; best</option>
        </select>
      </div>
      <div>
        <label for="seed">Seed</label>
        <input id="seed" placeholder="random" inputmode="numeric">
      </div>
      <div>
        <label for="count">How many</label>
        <select id="count">
          <option>1</option><option>2</option><option>4</option>
        </select>
      </div>
    </div>

    <details>
      <summary>Advanced</summary>
      <div class="row" style="margin-top:0">
        <div>
          <label for="unet">Model</label>
          <select id="unet"></select>
        </div>
        <div>
          <label for="clip">Text encoder</label>
          <select id="clip"></select>
        </div>
      </div>
    </details>

    <button class="go" id="go">Generate</button>
    <div class="status" id="status"></div>
    <div class="bar" id="bar"><i></i></div>
  </div>

  <div class="shots" id="shots"></div>
</div>

<script>
const $ = id => document.getElementById(id);
const clientId = crypto.randomUUID();
const MAX_REFS = 10;
const FULL_STEPS = 40;
// how much of the image Enhance is allowed to redraw; below ~0.3 it barely bites,
// above ~0.6 it starts rearranging things instead of sharpening them
const ENHANCE_DENOISE = 0.45;
let refs = [];        // {ref: workflow string, url: thumbnail}
let pending = 0;

const viewUrl = (filename, subfolder, type) =>
  '/view?filename=' + encodeURIComponent(filename)
  + '&subfolder=' + encodeURIComponent(subfolder || '')
  + '&type=' + encodeURIComponent(type || 'output');

/* ---------- model pickers ---------- */

async function fillModels() {
  const pick = async (folder, sel, prefer) => {
    try {
      const names = await (await fetch('/models/' + folder)).json();
      sel.innerHTML = '';
      for (const n of names) {
        const o = document.createElement('option');
        o.value = o.textContent = n;
        if (n.includes(prefer)) o.selected = true;
        sel.appendChild(o);
      }
    } catch (e) { /* leave empty; generate will report it */ }
  };
  await Promise.all([
    pick('diffusion_models', $('unet'), 'qwen_image_2.1'),
    // int8_convrot over w4a8: measured the same speed once ck attention is on,
    // for +700MB VRAM and 8-bit rather than 4-bit weights
    pick('text_encoders', $('clip'), 'qwen3vl_8b_int8_convrot'),
  ]);
}

/* ---------- reference images ---------- */

function renderRefs() {
  $('thumbs').innerHTML = '';
  refs.forEach((r, i) => {
    const d = document.createElement('div');
    d.className = 'thumb';
    d.innerHTML = '<img src="' + r.url + '" alt=""><button title="Remove">&times;</button>';
    d.querySelector('button').onclick = () => { refs.splice(i, 1); renderRefs(); };
    $('thumbs').appendChild(d);
  });
  const editing = refs.length > 0;
  $('sizeWrap').classList.toggle('hide', editing);
  $('scaleWrap').classList.toggle('hide', !editing);
  $('go').textContent = editing ? 'Edit' : 'Generate';
  $('mode').innerHTML = editing
    ? '<b>Editing mode.</b> Describe the change you want. Output keeps the first reference’s shape.'
    : '';
}

async function addFiles(files) {
  for (const f of files) {
    if (!f.type.startsWith('image/')) continue;
    if (refs.length >= MAX_REFS) { $('status').textContent = 'Limit is ' + MAX_REFS + ' reference images.'; break; }
    const fd = new FormData();
    fd.append('image', f, f.name);
    fd.append('type', 'input');
    try {
      const r = await (await fetch('/upload/image', {method: 'POST', body: fd})).json();
      const name = (r.subfolder ? r.subfolder + '/' : '') + r.name;
      refs.push({ref: name, url: viewUrl(r.name, r.subfolder, 'input')});
      renderRefs();
    } catch (e) {
      $('status').innerHTML = '<span class="err">Upload failed: ' + e + '</span>';
    }
  }
}

const outputRef = img => (img.subfolder ? img.subfolder + '/' : '') + img.filename + ' [output]';

function addOutputAsRef(img) {
  // "Edit this" means edit THIS one: replace whatever was staged rather than adding to it
  refs = [{ref: outputRef(img), url: viewUrl(img.filename, img.subfolder, img.type || 'output')}];
  renderRefs();
  $('prompt').focus();
  window.scrollTo({top: 0, behavior: 'smooth'});
}

$('drop').onclick = () => $('file').click();
$('file').onchange = e => { addFiles(e.target.files); e.target.value = ''; };
['dragenter', 'dragover'].forEach(ev => $('drop').addEventListener(ev, e => {
  e.preventDefault(); $('drop').classList.add('over');
}));
['dragleave', 'drop'].forEach(ev => $('drop').addEventListener(ev, e => {
  e.preventDefault(); $('drop').classList.remove('over');
}));
$('drop').addEventListener('drop', e => addFiles(e.dataTransfer.files));
document.addEventListener('paste', e => {
  const files = [...(e.clipboardData?.files || [])];
  if (files.length) { e.preventDefault(); addFiles(files); }
});

/* ---------- workflow ---------- */

function buildWorkflow(o) {
  const wf = {
    "1": {class_type: "UNETLoader", inputs: {unet_name: o.unet, weight_dtype: "default"}},
    "2": {class_type: "CLIPLoader", inputs: {clip_name: o.clip, type: "qwen_image"}},
    "3": {class_type: "VAELoader", inputs: {vae_name: "qwen_image_2.1_vae_bf16.safetensors"}},
    // negative_prompt is a required input, but the sampler runs at cfg 1.0 and
    // comfy/samplers.py drops uncond entirely there - so it can only ever be empty
    "4": {class_type: "TextEncodeQwenImage21", inputs: {
            clip: ["2", 0], prompt: o.prompt, negative_prompt: "",
            resolution: o.refs.length ? o.scale : 1024}},
    "6": {class_type: "KSampler", inputs: {
            model: ["1", 0], positive: ["4", 0], negative: ["4", 1], latent_image: null,
            seed: o.seed, steps: o.steps, cfg: 1.0,
            sampler_name: "euler", scheduler: "simple", denoise: 1.0}},
    "7": {class_type: "VAEDecode", inputs: {samples: ["6", 0], vae: ["3", 0]}},
    "8": {class_type: "SaveImage", inputs: {images: ["7", 0], filename_prefix: o.refs.length ? "qwen21_edit" : "qwen21"}},
  };

  let latent;
  if (o.enhance) {
    // Refine the image we already have rather than re-deriving it: encode those exact
    // pixels and denoise only partway, so the composition cannot drift to a new one.
    wf["20"] = {class_type: "LoadImage", inputs: {image: o.enhance.file}};
    wf["21"] = {class_type: "VAEEncode", inputs: {pixels: ["20", 0], vae: ["3", 0]}};
    wf["6"].inputs.denoise = o.enhance.denoise;
    wf["8"].inputs.filename_prefix = "qwen21_enhanced";
    latent = ["21", 0];
  } else if (!o.refs.length) {
    wf["5"] = {class_type: "EmptyQwenImage21Latent",
               inputs: {width: o.w, height: o.h, batch_size: o.count}};
    latent = ["5", 0];
  } else {
    // editing: each reference gets a loader, and the VAE turns them into reference latents
    wf["4"].inputs.vae = ["3", 0];
    o.refs.forEach((r, i) => {
      const id = String(100 + i);
      wf[id] = {class_type: "LoadImage", inputs: {image: r.ref}};
      // autogrow slots are namespaced in the API format
      wf["4"].inputs["images.image_" + (i + 1)] = [id, 0];
    });
    // node 4's own latent is sized from the first reference; any other size shifts the edit
    if (o.count > 1) {
      wf["9"] = {class_type: "RepeatLatentBatch", inputs: {samples: ["4", 2], amount: o.count}};
      latent = ["9", 0];
    } else {
      latent = ["4", 2];
    }
  }

  // Redoing one image out of a batch: noise is drawn per batch slot from the seed, so
  // picking slot N back out with LatentFromBatch is what reproduces that exact image.
  if (o.pick != null && o.count > 1) {
    wf["10"] = {class_type: "LatentFromBatch",
                inputs: {samples: latent, batch_index: o.pick, length: 1}};
    latent = ["10", 0];
  }
  wf["6"].inputs.latent_image = latent;
  return wf;
}

/* ---------- results ---------- */

function show(img, meta, job) {
  const url = viewUrl(img.filename, img.subfolder, img.type);
  const fig = document.createElement('figure');
  const redo = job && job.steps < FULL_STEPS
    ? '<button type="button" data-act="full" title="Re-run this seed at full step count. Usually the same image with more detail, but it can occasionally land on a different composition.">Full quality</button>' : '';
  const enh = job
    ? '<button type="button" data-act="enhance" title="Refine these exact pixels. Cannot change the composition, but adds less new detail than a full re-run.">Enhance</button>' : '';
  fig.innerHTML = '<img src="' + url + '" alt="">'
    + '<figcaption><span>' + meta + '</span>'
    + '<span class="acts">' + redo + enh
    + '<button type="button" data-act="edit">Edit this</button>'
    + '<a href="' + url + '" download>Download</a></span></figcaption>';
  fig.querySelector('[data-act="edit"]').onclick = () => addOutputAsRef(img);
  const full = fig.querySelector('[data-act="full"]');
  if (full) full.onclick = () => {
    full.disabled = true;
    // same seed, prompt, size and references - only the step count changes
    runJob({...job, steps: FULL_STEPS, pick: job.batchIndex});
  };
  const enhance = fig.querySelector('[data-act="enhance"]');
  if (enhance) enhance.onclick = () => {
    enhance.disabled = true;
    // anchored to this image's pixels, so batch slot and references no longer apply
    runJob({...job, steps: FULL_STEPS, count: 1, pick: null, refs: [],
            enhance: {file: outputRef(img), denoise: ENHANCE_DENOISE}});
  };
  $('shots').prepend(fig);
}

/* ---------- progress ---------- */

const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://')
                         + location.host + '/ws?clientId=' + clientId);
ws.onmessage = ev => {
  if (typeof ev.data !== 'string') return;
  const m = JSON.parse(ev.data);
  if (m.type === 'progress' && pending) {
    const pct = Math.round(100 * m.data.value / m.data.max);
    $('bar').classList.add('on');
    $('bar').firstElementChild.style.width = pct + '%';
    $('status').textContent = 'Working… ' + pct + '%';
  }
};

/* ---------- run ---------- */

function generate() {
  const [w, h] = $('size').value.split('x').map(Number);
  const prompt = $('prompt').value.trim();
  if (!prompt) { $('prompt').focus(); return; }
  const seedIn = $('seed').value.trim();
  return runJob({
    unet: $('unet').value, clip: $('clip').value, prompt, w, h,
    scale: Number($('scale').value),
    seed: seedIn === '' ? Math.floor(Math.random() * 2 ** 32) : Number(seedIn),
    count: Number($('count').value),
    steps: Number($('quality').value) || FULL_STEPS,
    refs: refs.slice(),   // frozen, so a later "Edit this" cannot rewrite this job
  });
}

async function runJob(p) {
  const {w, h, seed, steps, count} = p;
  const editing = p.refs.length > 0;

  $('go').disabled = true;
  $('status').textContent = 'Queued…';
  $('bar').classList.add('on');
  $('bar').firstElementChild.style.width = '0%';
  const t0 = performance.now();
  pending++;

  try {
    const res = await fetch('/prompt', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        client_id: clientId,
        prompt: buildWorkflow(p),
      }),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(JSON.stringify(body.error || body, null, 2));
    const id = body.prompt_id;

    // /prompt returns as soon as the job is queued; poll history for the result
    for (;;) {
      await new Promise(r => setTimeout(r, 700));
      const hist = await (await fetch('/history/' + id)).json();
      const entry = hist[id];
      if (!entry) continue;
      const st = entry.status || {};
      if (st.status_str === 'error') {
        const note = (st.messages || []).find(m => m[0] === 'execution_error');
        throw new Error(note ? (note[1].exception_message || JSON.stringify(note[1], null, 2))
                             : 'execution failed');
      }
      if (st.completed) {
        const secs = ((performance.now() - t0) / 1000).toFixed(1);
        let n = 0;
        for (const node of Object.values(entry.outputs || {}))
          for (const img of node.images || []) {
            const label = p.enhance
              ? 'enhanced'
              : (editing ? 'edit' : w + '×' + h)
                + ' · ' + (steps >= FULL_STEPS ? 'full' : 'preview');
            // when a whole batch comes back, each image keeps the slot it was drawn in
            const slot = p.pick != null ? p.pick : n;
            show(img, label + ' · seed ' + seed + ' · ' + secs + 's',
                 {...p, batchIndex: slot});
            n++;
          }
        $('status').textContent = n ? 'Done in ' + secs + 's' : 'Finished, but produced no image.';
        break;
      }
    }
  } catch (e) {
    $('status').innerHTML = '<span class="err">' + String(e.message || e) + '</span>';
  } finally {
    pending--;
    $('go').disabled = false;
    $('bar').classList.remove('on');
  }
}

$('go').onclick = generate;
$('prompt').addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') generate();
});
fillModels();
renderRefs();
</script>
</body>
</html>
"""


@PromptServer.instance.routes.get("/simple")
async def simple_ui(request):
    return web.Response(text=PAGE, content_type="text/html")
