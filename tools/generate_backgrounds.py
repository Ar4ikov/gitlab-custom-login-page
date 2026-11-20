"""Generate the abstract backgrounds with Z-Image-Turbo (GGUF Q4) on two small GPUs (~3 GB VRAM each).

    python generate_backgrounds.py prompts.json

The transformer blocks are split between cuda:0 and cuda:1, the 4-bit text encoder is unloaded after
the prompts are encoded. Images are rendered on black and converted to transparency (*.webp).
Needs: torch, diffusers, transformers, accelerate, bitsandbytes, gguf, pillow, numpy.
"""
import os, sys, json, time, torch, numpy as np
from PIL import Image
from diffusers import (AutoencoderKL, FlowMatchEulerDiscreteScheduler, GGUFQuantizationConfig,
                       ZImagePipeline, ZImageTransformer2DModel)
from diffusers.image_processor import VaeImageProcessor
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

BASE = os.environ.get("ZIMAGE_BASE", "models/base")          # Tongyi-MAI/Z-Image-Turbo (text_encoder, vae, ...)
GGUF = os.environ.get("ZIMAGE_GGUF", "models/z-image-turbo-Q4_K_M.gguf")   # unsloth/Z-Image-Turbo-GGUF
OUT = os.environ.get("OUT", "out")
D_TR, D_AUX = "cuda:0", "cuda:1"
JOBS = json.load(open(sys.argv[1]))   # [{name,w,h,prompt,seeds:[..]}]
SUFFIX = ", isolated on a pure solid black background, deep black empty space around, abstract, no text, no letters, no logo, no watermark, no people"

import gc
# phase 1: text encoder (bnb 4bit) on cuda:1 -> embeddings, then free it
tok = AutoTokenizer.from_pretrained(BASE, subfolder="tokenizer")
te = AutoModelForCausalLM.from_pretrained(
    BASE, subfolder="text_encoder", device_map={"": D_AUX},
    quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                           bnb_4bit_compute_dtype=torch.bfloat16))
sched = FlowMatchEulerDiscreteScheduler.from_pretrained(BASE, subfolder="scheduler")
enc = ZImagePipeline(scheduler=sched, vae=None, text_encoder=te, tokenizer=tok, transformer=None)
EMB = {}
with torch.no_grad():
    for j in JOBS:
        emb, _ = enc.encode_prompt(j["prompt"] + SUFFIX, device=D_AUX, do_classifier_free_guidance=False)
        EMB[j["name"]] = [e.to(D_TR) for e in emb]
del enc, te; gc.collect(); torch.cuda.empty_cache()
# phase 2: GGUF transformer split over both GPUs (middle blocks on cuda:1), VAE on cuda:1
vae = AutoencoderKL.from_pretrained(BASE, subfolder="vae", torch_dtype=torch.bfloat16).to(D_AUX)
vae.enable_tiling()
vae.tile_latent_min_size, vae.tile_sample_min_size = 48, 384
tr = ZImageTransformer2DModel.from_single_file(
    GGUF, config=BASE, subfolder="transformer", torch_dtype=torch.bfloat16,
    quantization_config=GGUFQuantizationConfig(compute_dtype=torch.bfloat16))
n = len(tr.layers); lo, hi = int(os.environ.get("SPLIT_LO", 8)), int(os.environ.get("SPLIT_HI", 22))
def _mv(dev):
    def hook(mod, args, kwargs):
        f = lambda x: x.to(dev) if torch.is_tensor(x) else ([f(y) for y in x] if isinstance(x, (list, tuple)) else x)
        return tuple(f(x) for x in args), {k: f(v) for k, v in kwargs.items()}
    return hook
for name, child in tr.named_children():
    if name == "layers":
        for i, layer in enumerate(child):
            dev = D_AUX if lo <= i < hi else D_TR
            layer.to(dev)
            layer.register_forward_pre_hook(_mv(dev), with_kwargs=True)
    else:
        child.to(D_TR)
for name, p in tr.named_parameters(recurse=False):
    p.data = p.data.to(D_TR)
print("layers", n, "on cuda:1:", lo, "..", hi - 1, flush=True)
gen = ZImagePipeline(scheduler=sched, vae=None, text_encoder=None, tokenizer=None, transformer=tr)
gen.set_progress_bar_config(disable=True)
proc = VaeImageProcessor(vae_scale_factor=16)


def to_alpha(img):
    """black background -> transparency (un-premultiplied), soft knee so dark noise is dropped"""
    a = np.asarray(img.convert("RGB")).astype(np.float32) / 255.0
    m = a.max(axis=2)
    lo, hi = 0.035, 0.55
    al = np.clip((m - lo) / (hi - lo), 0, 1) ** 0.8
    rgb = np.clip(a / np.maximum(m, 1e-3)[..., None] * np.maximum(m, al)[..., None], 0, 1)
    out = np.dstack([rgb, al])
    return Image.fromarray((out * 255).astype(np.uint8), "RGBA")


with torch.no_grad():
    for j in JOBS:
        emb = EMB[j["name"]]
        for s in j.get("seeds", [1]):
            t = time.time()
            lat = gen(prompt_embeds=emb, height=j["h"], width=j["w"],
                      num_inference_steps=9, guidance_scale=0.0, output_type="latent",
                      generator=torch.Generator(D_TR).manual_seed(s)).images
            torch.cuda.empty_cache()
            lat = lat.to(D_AUX, vae.dtype) / vae.config.scaling_factor + vae.config.shift_factor
            img = proc.postprocess(vae.decode(lat, return_dict=False)[0].float(), output_type="pil")[0]
            p = f"{OUT}/{j['name']}-s{s}"
            os.makedirs(os.path.dirname(p), exist_ok=True)
            img.save(p + ".raw.jpg", quality=88)
            to_alpha(img).save(p + ".webp", quality=88, method=6)
            print(j["name"], s, f"{time.time() - t:.1f}s", flush=True)
print("peak GB", [round(torch.cuda.max_memory_allocated(i)/2**30,2) for i in (0,1)])
print("DONE")
