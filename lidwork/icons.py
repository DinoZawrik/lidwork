"""Generated tray icons."""

from __future__ import annotations

from PIL import Image, ImageDraw


def build_icon(active: bool) -> Image.Image:
    """Build a tray icon for the active state."""
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    shell_color = (28, 140, 85, 255) if active else (117, 117, 117, 255)
    accent_color = (194, 240, 210, 255) if active else (220, 220, 220, 255)
    outline = (13, 43, 31, 255) if active else (66, 66, 66, 255)

    draw.rounded_rectangle((10, 18, 54, 34), radius=5, outline=outline, fill=shell_color, width=3)
    draw.line((20, 40, 32, 46, 44, 40), fill=outline, width=4)
    if active:
        draw.ellipse((22, 20, 42, 30), fill=accent_color)
    else:
        draw.ellipse((22, 20, 42, 30), outline=accent_color, width=3)
    return image

