#!/usr/bin/env python3
"""Generate the abstract login-page backgrounds with Z-Image-Turbo.

The model is squeezed onto two small GPUs (about 3 GB of free VRAM on each):

* the 4-bit text encoder runs first on the auxiliary GPU and is unloaded as soon
  as every prompt is encoded;
* the GGUF-quantised transformer is then split block-wise between both GPUs;
* the VAE decodes on the auxiliary GPU with tiling enabled.

Every image is rendered on a black background and saved twice: the raw frame
(``<name>-s<seed>.raw.jpg``, input for ``make_blooms.py``) and a transparent
version (``<name>-s<seed>.webp``) where black became alpha.

Example::

    python generate_backgrounds.py prompts.json --out out \\
        --base models/base --gguf models/z-image-turbo-Q4_K_M.gguf
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from diffusers import (
    AutoencoderKL,
    FlowMatchEulerDiscreteScheduler,
    GGUFQuantizationConfig,
    ZImagePipeline,
    ZImageTransformer2DModel,
)
from diffusers.image_processor import VaeImageProcessor
from PIL import Image
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

log = logging.getLogger("generate_backgrounds")

PROMPT_SUFFIX = (
    ", isolated on a pure solid black background, deep black empty space around, "
    "abstract, no text, no letters, no logo, no watermark, no people"
)
INFERENCE_STEPS = 9  # Z-Image-Turbo is distilled for 8-9 steps without guidance
VAE_SCALE_FACTOR = 16
DTYPE = torch.bfloat16

PromptEmbeds = list[torch.Tensor]


@dataclass(frozen=True)
class Job:
    """One prompt rendered with one or more seeds."""

    name: str
    width: int
    height: int
    prompt: str
    seeds: tuple[int, ...] = (1,)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Job:
        return cls(
            name=raw["name"],
            width=int(raw["width"]),
            height=int(raw["height"]),
            prompt=raw["prompt"],
            seeds=tuple(int(seed) for seed in raw.get("seeds", (1,))),
        )


def load_jobs(path: Path) -> list[Job]:
    """Read the list of jobs from a JSON file."""
    with path.open(encoding="utf-8") as file:
        return [Job.from_dict(item) for item in json.load(file)]


def encode_prompts(base: Path, jobs: Sequence[Job], device: str, target: str) -> dict[str, PromptEmbeds]:
    """Encode every prompt with the 4-bit text encoder, then free the encoder.

    The embeddings are moved to ``target`` (the device of the first transformer
    block) so the encoder's VRAM can be reused for the transformer.
    """
    tokenizer = AutoTokenizer.from_pretrained(base, subfolder="tokenizer")
    text_encoder = AutoModelForCausalLM.from_pretrained(
        base,
        subfolder="text_encoder",
        device_map={"": device},
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=DTYPE,
        ),
    )
    scheduler = FlowMatchEulerDiscreteScheduler.from_pretrained(base, subfolder="scheduler")
    pipeline = ZImagePipeline(
        scheduler=scheduler, vae=None, text_encoder=text_encoder, tokenizer=tokenizer, transformer=None
    )

    embeddings: dict[str, PromptEmbeds] = {}
    with torch.no_grad():
        for job in jobs:
            embeds, _ = pipeline.encode_prompt(
                job.prompt + PROMPT_SUFFIX, device=device, do_classifier_free_guidance=False
            )
            embeddings[job.name] = [embed.to(target) for embed in embeds]

    del pipeline, text_encoder
    gc.collect()
    torch.cuda.empty_cache()
    return embeddings


def _move_inputs_to(device: str) -> Callable[..., tuple[tuple[Any, ...], dict[str, Any]]]:
    """Build a forward pre-hook that moves every tensor argument to ``device``."""

    def move(value: Any) -> Any:
        if torch.is_tensor(value):
            return value.to(device)
        if isinstance(value, (list, tuple)):
            return type(value)(move(item) for item in value)
        return value

    def hook(
        _module: torch.nn.Module, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        return tuple(move(arg) for arg in args), {key: move(val) for key, val in kwargs.items()}

    return hook


def load_split_transformer(
    gguf: Path, base: Path, main_device: str, aux_device: str, split: tuple[int, int]
) -> ZImageTransformer2DModel:
    """Load the GGUF transformer and spread its blocks over two GPUs.

    Blocks ``split[0] <= i < split[1]`` live on ``aux_device``; everything else,
    including the first and the last blocks, stays on ``main_device`` so the
    model's inputs and outputs are on one device. ``accelerate.dispatch_model``
    cannot move GGUF parameters, hence the manual placement and the hooks.
    """
    transformer = ZImageTransformer2DModel.from_single_file(
        str(gguf),
        config=str(base),
        subfolder="transformer",
        torch_dtype=DTYPE,
        quantization_config=GGUFQuantizationConfig(compute_dtype=DTYPE),
    )
    first, last = split
    for name, child in transformer.named_children():
        if name != "layers":
            child.to(main_device)
            continue
        for index, layer in enumerate(child):
            device = aux_device if first <= index < last else main_device
            layer.to(device)
            layer.register_forward_pre_hook(_move_inputs_to(device), with_kwargs=True)
    for _, parameter in transformer.named_parameters(recurse=False):
        parameter.data = parameter.data.to(main_device)

    log.info("transformer: %d blocks, %d..%d on %s", len(transformer.layers), first, last - 1, aux_device)
    return transformer


def load_vae(base: Path, device: str) -> AutoencoderKL:
    """Load the VAE with tiling so decoding fits into a couple of gigabytes."""
    vae = AutoencoderKL.from_pretrained(base, subfolder="vae", torch_dtype=DTYPE).to(device)
    vae.enable_tiling()
    vae.tile_latent_min_size = 48
    vae.tile_sample_min_size = 384
    return vae


def black_to_alpha(image: Image.Image, low: float = 0.035, high: float = 0.55, gamma: float = 0.8) -> Image.Image:
    """Turn a picture rendered on black into an un-premultiplied RGBA image.

    Brightness becomes opacity: everything darker than ``low`` is transparent
    (this drops the noise of the "black" background), everything brighter than
    ``high`` is opaque.
    """
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    brightness = rgb.max(axis=2)
    alpha = np.clip((brightness - low) / (high - low), 0.0, 1.0) ** gamma
    scale = np.maximum(brightness, alpha) / np.maximum(brightness, 1e-3)
    colour = np.clip(rgb * scale[..., None], 0.0, 1.0)
    rgba = np.dstack([colour, alpha])
    return Image.fromarray((rgba * 255).astype(np.uint8), "RGBA")


def render(
    jobs: Sequence[Job],
    embeddings: dict[str, PromptEmbeds],
    transformer: ZImageTransformer2DModel,
    vae: AutoencoderKL,
    base: Path,
    out_dir: Path,
    main_device: str,
    aux_device: str,
) -> None:
    """Denoise on the split transformer, decode on the VAE and save both files."""
    scheduler = FlowMatchEulerDiscreteScheduler.from_pretrained(base, subfolder="scheduler")
    pipeline = ZImagePipeline(scheduler=scheduler, vae=None, text_encoder=None, tokenizer=None, transformer=transformer)
    pipeline.set_progress_bar_config(disable=True)
    processor = VaeImageProcessor(vae_scale_factor=VAE_SCALE_FACTOR)
    out_dir.mkdir(parents=True, exist_ok=True)

    with torch.no_grad():
        for job in jobs:
            for seed in job.seeds:
                started = time.perf_counter()
                latents = pipeline(
                    prompt_embeds=embeddings[job.name],
                    height=job.height,
                    width=job.width,
                    num_inference_steps=INFERENCE_STEPS,
                    guidance_scale=0.0,
                    output_type="latent",
                    generator=torch.Generator(main_device).manual_seed(seed),
                ).images
                torch.cuda.empty_cache()

                latents = latents.to(aux_device, vae.dtype) / vae.config.scaling_factor + vae.config.shift_factor
                decoded = vae.decode(latents, return_dict=False)[0].float()
                image = processor.postprocess(decoded, output_type="pil")[0]

                stem = out_dir / f"{job.name}-s{seed}"
                image.save(f"{stem}.raw.jpg", quality=88)
                black_to_alpha(image).save(f"{stem}.webp", quality=88, method=6)
                log.info("%s seed %d: %.1fs", job.name, seed, time.perf_counter() - started)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("jobs", type=Path, help="JSON file with prompts (see prompts.json)")
    parser.add_argument("--out", type=Path, default=Path("out"), help="output directory (default: out)")
    parser.add_argument(
        "--base",
        type=Path,
        default=Path("models/base"),
        help="Tongyi-MAI/Z-Image-Turbo checkout: text_encoder, tokenizer, vae, scheduler, transformer/config.json",
    )
    parser.add_argument(
        "--gguf",
        type=Path,
        default=Path("models/z-image-turbo-Q4_K_M.gguf"),
        help="quantised transformer, e.g. from unsloth/Z-Image-Turbo-GGUF",
    )
    parser.add_argument("--main-device", default="cuda:0", help="most transformer blocks (default: cuda:0)")
    parser.add_argument("--aux-device", default="cuda:1", help="text encoder, VAE and the middle blocks")
    parser.add_argument(
        "--split",
        type=int,
        nargs=2,
        default=(8, 22),
        metavar=("FIRST", "LAST"),
        help="transformer blocks FIRST..LAST-1 go to the auxiliary device (default: 8 22)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    jobs = load_jobs(args.jobs)
    log.info("%d prompts, %d images", len(jobs), sum(len(job.seeds) for job in jobs))

    embeddings = encode_prompts(args.base, jobs, device=args.aux_device, target=args.main_device)
    vae = load_vae(args.base, args.aux_device)
    transformer = load_split_transformer(args.gguf, args.base, args.main_device, args.aux_device, tuple(args.split))
    render(jobs, embeddings, transformer, vae, args.base, args.out, args.main_device, args.aux_device)

    peaks = {device: torch.cuda.max_memory_allocated(device) / 2**30 for device in (args.main_device, args.aux_device)}
    log.info("peak VRAM: %s", ", ".join(f"{device} {gib:.2f} GiB" for device, gib in peaks.items()))


if __name__ == "__main__":
    main()
