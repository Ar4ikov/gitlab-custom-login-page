#!/usr/bin/env python3
"""Turn generated backgrounds into blurred, grainy corner "blooms".

GitLab draws a 350x600 picture in the top-right corner of the signed-in UI.
This script builds replacements for it: each source frame (a ``*.raw.jpg``
written by ``generate_backgrounds.py``) is cropped to its colourful part,
blurred heavily, faded out towards the left and the bottom edges and dusted
with film grain. The results are written as ``side-1.webp``, ``side-2.webp``,
... in the order the sources are given.

The nginx config picks one of six files at random, so pass six sources (or
adjust the ``map`` block in ``docker/default.conf.template``).

Example::

    python make_blooms.py out/a-peach-nebula-s11.raw.jpg out/b-aurora-ribbons-s22.raw.jpg \\
        --out ../skin/bloom --sheet sheet.jpg
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

log = logging.getLogger("make_blooms")

SIZE = (350, 600)  # width, height of GitLab's bloom-side slot
CONTENT_THRESHOLD = 60  # 0-255: pixels brighter than this count as "content"
PAGE_COLOUR = (14, 13, 18)  # dark UI colour used for the contact sheet


def corner_mask(width: int, height: int, reach: float = 0.94) -> np.ndarray:
    """Opacity mask anchored in the top-right corner.

    A smoothstep falloff that reaches exactly zero before the left and the
    bottom edges, so the picture never ends with a visible border.
    """
    rows, cols = np.mgrid[0:height, 0:width].astype(np.float32)
    from_right = (width - cols) / width
    from_top = rows / height
    falloff = np.clip(1.0 - np.hypot(from_right, from_top) / reach, 0.0, 1.0)
    return falloff * falloff * (3.0 - 2.0 * falloff)


def crop_to_content(image: Image.Image, threshold: int = CONTENT_THRESHOLD) -> Image.Image:
    """Cut away the black margins around the bright part of the frame."""
    brightness = np.asarray(image.convert("RGB")).max(axis=2)
    rows, cols = np.where(brightness > threshold)
    if rows.size == 0:
        return image
    return image.crop((cols.min(), rows.min(), cols.max() + 1, rows.max() + 1))


def cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale and centre-crop the image so it fills ``size`` completely."""
    width, height = size
    scale = max(width / image.width, height / image.height)
    resized = image.resize((round(image.width * scale) + 1, round(image.height * scale) + 1), Image.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def brightest_under(colour: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Flip the picture so that its brightest area sits where the mask is strongest."""
    flips = (colour, colour[:, ::-1], colour[::-1], colour[::-1, ::-1])
    return max(flips, key=lambda candidate: float((candidate.max(axis=2) * mask).sum()))


def make_bloom(
    source: Image.Image,
    mask: np.ndarray,
    rng: np.random.Generator,
    blur: float = 36.0,
    grain: float = 0.05,
    opacity: float = 0.92,
) -> Image.Image:
    """Build one RGBA bloom of the same size as ``mask``."""
    height, width = mask.shape
    blurred = cover(crop_to_content(source), (width, height)).filter(ImageFilter.GaussianBlur(blur))

    colour = np.asarray(blurred.convert("RGB"), dtype=np.float32) / 255.0
    colour /= max(float(colour.max()), 1e-3)  # the heavy blur dims everything: stretch it back
    colour = brightest_under(colour, mask)

    alpha = mask * np.clip(0.3 + colour.max(axis=2), 0.0, 1.0) * opacity
    alpha *= 1.0 + rng.normal(0.0, 0.10, alpha.shape).astype(np.float32)
    # half a level of dither hides banding in the long transparent gradient
    alpha += (mask > 0) * rng.uniform(-0.5, 0.5, alpha.shape).astype(np.float32) / 255.0

    colour = colour + rng.normal(0.0, grain, (height, width, 1)).astype(np.float32)
    rgba = np.dstack([np.clip(colour, 0.0, 1.0), np.clip(alpha, 0.0, 1.0)])
    return Image.fromarray((rgba * 255).astype(np.uint8), "RGBA")


def contact_sheet(blooms: Sequence[Image.Image], background: tuple[int, int, int] = PAGE_COLOUR) -> Image.Image:
    """Lay the blooms side by side on the UI colour for a quick visual check."""
    width, height = blooms[0].size
    sheet = Image.new("RGB", (width * len(blooms), height), background)
    for index, bloom in enumerate(blooms):
        tile = Image.new("RGBA", bloom.size, (*background, 255))
        tile.alpha_composite(bloom)
        sheet.paste(tile.convert("RGB"), (index * width, 0))
    return sheet


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sources", type=Path, nargs="+", help="frames rendered on black (*.raw.jpg)")
    parser.add_argument("--out", type=Path, default=Path("bloom"), help="output directory (default: bloom)")
    parser.add_argument("--sheet", type=Path, help="also save a contact sheet to this file")
    parser.add_argument("--blur", type=float, default=36.0, help="Gaussian blur radius in pixels (default: 36)")
    parser.add_argument("--grain", type=float, default=0.05, help="film grain strength, 0..1 (default: 0.05)")
    parser.add_argument("--quality", type=int, default=70, help="WebP quality (default: 70)")
    parser.add_argument("--seed", type=int, default=7, help="seed of the grain, for reproducible files")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    rng = np.random.default_rng(args.seed)
    mask = corner_mask(*SIZE)
    args.out.mkdir(parents=True, exist_ok=True)

    blooms = []
    for index, source in enumerate(args.sources, start=1):
        with Image.open(source) as image:
            bloom = make_bloom(image.convert("RGB"), mask, rng, blur=args.blur, grain=args.grain)
        target = args.out / f"side-{index}.webp"
        bloom.save(target, quality=args.quality, alpha_quality=100, method=6)
        blooms.append(bloom)
        log.info("%s -> %s (%d kB)", source.name, target, target.stat().st_size // 1024)

    if args.sheet:
        contact_sheet(blooms).save(args.sheet, quality=85)
        log.info("contact sheet: %s", args.sheet)


if __name__ == "__main__":
    main()
