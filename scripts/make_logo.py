"""Generate simple profile logos for @fc.core accounts — black bg + thin white text."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import subprocess

OUT = Path(__file__).parent.parent / "data" / "branding"
OUT.mkdir(parents=True, exist_ok=True)


def find_font():
    """Find a light/thin sans-serif font."""
    candidates = [
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def make_logo(text: str, output: Path, size: int = 1024, font_size_ratio: float = 0.18):
    img = Image.new("RGB", (size, size), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_path = find_font()
    font_size = int(size * font_size_ratio)
    try:
        font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    # Measure text
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x = (size - text_w) // 2 - bbox[0]
    y = (size - text_h) // 2 - bbox[1]

    draw.text((x, y), text, font=font, fill=(255, 255, 255))

    img.save(output, "PNG", quality=95)
    print(f"  {output.name} ({size}x{size})")


if __name__ == "__main__":
    print("Generating logos for @fc.core...")
    make_logo("fc.core.", OUT / "logo_1024.png", size=1024)
    make_logo("fc.core.", OUT / "logo_512.png", size=512)
    make_logo("fc.core.", OUT / "logo_256.png", size=256)
    print(f"\nLogos saved to: {OUT}/")
    print("Use logo_1024.png for highest quality (Instagram resizes automatically).")
