"""Color studio: encrypted texture/model downloads and the recolor engine.

Files come from ``GET /api/client/asset`` encrypted for this installation only
(AES-256-GCM; key = HKDF-SHA256 of this PC's device-key hash). They are
decrypted in memory, verified against their SHA-256, and kept on disk in the
encrypted cache (AES-256-GCM with a DPAPI-protected key). Each file is
downloaded once per version.
"""

from __future__ import annotations

import colorsys
import gzip
import hashlib
import io
import logging

import numpy as np
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .categories import StudioFile

logger = logging.getLogger(__name__)

_MAGIC = b'MVS1'


class StudioError(RuntimeError):
    """Raised when a studio file cannot be downloaded or verified."""


def decrypt_asset(blob: bytes, asset: StudioFile, device_key: str) -> bytes:
    """Decrypt a download made for this installation and verify its contents."""
    if len(blob) < 4 + 12 + 16 or not blob.startswith(_MAGIC):
        raise StudioError('The download is damaged')
    device_hash = hashlib.sha256(device_key.encode()).hexdigest()
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'mvsdsion-asset-v1',
        info=f'{asset.id}:{asset.sha256}'.encode(),
    ).derive(device_hash.encode())
    try:
        packed = AESGCM(key).decrypt(blob[4:16], blob[16:], asset.id.encode())
        data = gzip.decompress(packed)
    except (InvalidTag, OSError, EOFError) as exc:
        raise StudioError('The download could not be decrypted') from exc
    if hashlib.sha256(data).hexdigest() != asset.sha256:
        raise StudioError('The download does not match the expected file')
    return data


# Recoloring


def load_texture(png: bytes) -> np.ndarray:
    """PNG bytes to an RGBA float array (0..1)."""
    from PIL import Image

    with Image.open(io.BytesIO(png)) as image:
        return np.asarray(image.convert('RGBA'), dtype=np.float32) / 255.0


def to_png(rgba: np.ndarray) -> bytes:
    from PIL import Image

    image = Image.fromarray(np.clip(rgba * 255.0 + 0.5, 0, 255).astype(np.uint8), 'RGBA')
    output = io.BytesIO()
    image.save(output, format='PNG', optimize=False)
    return output.getvalue()


def _rgb_to_hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    maximum = np.max(rgb, axis=-1)
    minimum = np.min(rgb, axis=-1)
    delta = maximum - minimum
    hue = np.zeros_like(maximum)
    safe = np.where(delta == 0, 1, delta)
    hue = np.where(maximum == r, ((g - b) / safe) % 6, hue)
    hue = np.where(maximum == g, (b - r) / safe + 2, hue)
    hue = np.where(maximum == b, (r - g) / safe + 4, hue)
    hue = np.where(delta == 0, 0, hue) / 6.0
    saturation = np.where(maximum == 0, 0, delta / np.where(maximum == 0, 1, maximum))
    return hue, saturation, maximum


def _hsv_to_rgb(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    i = np.floor(h * 6.0)
    f = h * 6.0 - i
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))
    i = i.astype(np.int32) % 6
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], axis=-1)


def dominant_hue(rgba: np.ndarray) -> tuple[float, float, float]:
    """The texture's main color as (hue, mean saturation, mean value), weighted by saturation."""
    hue, saturation, value = _rgb_to_hsv(rgba[..., :3])
    weight = saturation * (rgba[..., 3] > 0.05)
    if weight.sum() < 1e-6:
        return 0.0, 0.0, float(value.mean())
    histogram, edges = np.histogram(hue, bins=72, range=(0, 1), weights=weight)
    # Smooth across the hue circle so a peak split over two bins still wins
    smooth = histogram + np.roll(histogram, 1) * 0.5 + np.roll(histogram, -1) * 0.5
    peak = int(np.argmax(smooth))
    main = (edges[peak] + edges[peak + 1]) / 2
    near = _hue_distance(hue, main) < 0.08
    w = weight * near
    total = max(float(w.sum()), 1e-6)
    return main, float((saturation * w).sum() / total), float((value * w).sum() / total)


def _hue_distance(hue: np.ndarray, target: float) -> np.ndarray:
    d = np.abs(hue - target)
    return np.minimum(d, 1 - d)


def _logit(p: float) -> float:
    return float(np.log(p / (1.0 - p)))


def recolor(
    rgba: np.ndarray,
    color: tuple[int, int, int],
    *,
    tolerance: float = 0.3,
    source: tuple[float, float, float] | None = None,
) -> np.ndarray:
    """Replace the texture's main color with ``color`` while keeping its shading.

    ``tolerance`` (0..1) is how much counts as the main color: up to 0.5 it is
    the hue range around the main color; above 0.5 every hue and, more and
    more, grey or dark parts (like a gun's drum) are colored too.

    Brightness is mapped in a curved (logit) space: the chosen brightness moves
    the middle, and the original light and shade stay visible even for very
    dark or very bright colors (no flat black or white).
    """
    src_hue, src_sat, src_val = source or dominant_hue(rgba)
    target_h, target_s, target_v = colorsys.rgb_to_hsv(*(c / 255.0 for c in color))
    hue, saturation, value = _rgb_to_hsv(rgba[..., :3])
    hue_range = min(tolerance, 0.5)
    distance = _hue_distance(hue, src_hue)
    # Soft edge so the change fades out instead of leaving hard borders
    colored = np.clip(saturation / 0.12, 0, 1)
    mask = np.clip((hue_range - distance) / max(hue_range * 0.35, 1e-3), 0, 1) * colored
    if tolerance > 0.5:
        # Wide range: all hues, then grey/dark parts as well
        extra = min((tolerance - 0.5) / 0.5, 1.0)
        mask = np.maximum(mask, colored * min(extra * 2, 1.0))
        mask = np.maximum(mask, (1 - colored) * extra)
    # Every pixel in range gets exactly the chosen hue; only light and shade are kept
    new_hue = np.full_like(hue, target_h)
    sat_scale = target_s / max(src_sat, 1e-3)
    tinted = np.clip(saturation * sat_scale, 0, 1) * 0.85 + target_s * 0.15
    # Grey parts take the chosen color's saturation, a bit softer
    new_sat = tinted * colored + target_s * 0.7 * (1 - colored)
    middle = float(np.clip(target_v, 0.08, 0.92))
    reference = float(np.clip(src_val, 0.06, 0.94))
    # Spread the shading around the new middle so it stays visible near black and white
    slope = 0.5 / (reference * (1 - reference)) + 0.5 / (middle * (1 - middle))
    shade = np.clip(value, 0.0, 1.0) - reference
    new_val = 1.0 / (1.0 + np.exp(-(_logit(middle) + shade * slope)))
    shifted = _hsv_to_rgb(new_hue, np.clip(new_sat, 0, 1), new_val.astype(np.float32))
    out = rgba.copy()
    out[..., :3] = rgba[..., :3] * (1 - mask[..., None]) + shifted * mask[..., None]
    return out


def downscale(rgba: np.ndarray, size: int) -> np.ndarray:
    """Smaller copy for fast live previews."""
    from PIL import Image

    height, width = rgba.shape[:2]
    if max(height, width) <= size:
        return rgba
    image = Image.fromarray(np.clip(rgba * 255, 0, 255).astype(np.uint8), 'RGBA')
    image.thumbnail((size, size))
    return np.asarray(image, dtype=np.float32) / 255.0
