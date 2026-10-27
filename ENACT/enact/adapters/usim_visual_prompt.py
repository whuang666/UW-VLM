"""Make upstream visual-prompt labels render with a real font on Windows.

``ForwardWorldModelingGenerator._add_text_to_image`` hardcodes Linux font paths
(``/usr/share/fonts/...``).  On Windows both lookups fail and Pillow falls back to
``ImageFont.load_default()``, which draws a ~10 px bitmap font inside a 320x240
frame -- the "Next State 2" label becomes unreadable, and the whole forward task
depends on that label.  This module re-binds the method with a font resolved from
the system, keeping the upstream styling (red text, white outline, top-left).

Usage:
    generator = ForwardWorldModelingGenerator(step_length=3)
    apply_local_font(generator)
"""

from __future__ import annotations

import shutil
import types
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

CANDIDATE_FONTS = (
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def resolve_font_path() -> Optional[str]:
    for candidate in CANDIDATE_FONTS:
        if Path(candidate).exists():
            return candidate
    return None


def render_label(image_path: str, text: str, output_path: str) -> None:
    """Draw a top-left red/white label on an image and save it."""
    try:
        img = Image.open(image_path)
        draw = ImageDraw.Draw(img)
        font_size = max(18, img.height // 10)
        font_path = resolve_font_path()
        try:
            font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
        except OSError:
            font = ImageFont.load_default()

        text_color = (255, 20, 20)
        outline_color = (255, 255, 255)
        outline_width = 2
        x, y = 8, 6
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx or dy:
                    draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        draw.text((x, y), text, font=font, fill=text_color)
        img.save(output_path)
    except Exception as error:  # pragma: no cover - mirrors upstream fallback
        print(f"Error processing image {image_path}: {error}")
        shutil.copy2(image_path, output_path)


def _add_text_to_image(self, image_path: str, text: str, output_path: str) -> None:
    render_label(image_path, text, output_path)


def apply_local_font(generator) -> None:
    """Bind the font-safe label renderer onto a generator instance."""
    generator._add_text_to_image = types.MethodType(_add_text_to_image, generator)
