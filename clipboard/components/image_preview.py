import re
from typing import Optional, Tuple
from gi.repository import GdkPixbuf


def is_image_data(content: str) -> bool:
    if not content:
        return False
    text = content.strip()
    low = text.lower()
    short_labels = {"[image]", "[imagem]", "[img]", "[imagem]"}
    if low in short_labels:
        return True
    return (
        content.startswith("data:image/")
        or content.startswith("\x89PNG")
        or content.startswith("GIF8")
        or content.startswith("\xff\xd8\xff")
        or re.match(r"^\s*<img\s+", content) is not None
        or ("binary" in low and any(ext in low for ext in ["jpg", "jpeg", "png", "bmp", "gif"]))
    )


def decode_and_scale(raw: bytes, item_width: int, item_height: int, padding: int = 16) -> Optional[GdkPixbuf.Pixbuf]:
    """Decode raw bytes into a scaled GdkPixbuf.Pixbuf or None on failure."""
    if not raw:
        return None
    try:
        loader = GdkPixbuf.PixbufLoader()
        if isinstance(raw, str):
            raw = raw.encode("utf-8", errors="ignore")
        loader.write(raw)
        loader.close()
        pixbuf = loader.get_pixbuf()
        if not pixbuf:
            return None
        # limit preview
        max_w = max(1, item_width - padding)
        max_h = max(1, item_height - 48)
        w, h = pixbuf.get_width(), pixbuf.get_height()
        scale = min(max_w / w, max_h / h, 1.0)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        return pixbuf.scale_simple(nw, nh, GdkPixbuf.InterpType.BILINEAR)
    except Exception:
        return None
