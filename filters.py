"""
filters.py — All photo filter effects for the photobooth app.

Each apply_* function takes a single PIL Image (one photo) and
returns the processed PIL Image. All original comments from
main.py's process_background() have been retained as-is.
"""

import numpy as np
from PIL import (
    Image,
    ImageOps,
    ImageEnhance,
    ImageFilter,
    ImageDraw,
)


def add_grain(img, intensity=10):
    """Add visual noise to mimic film grain."""
    np_img = np.array(img).astype(np.float32)
    noise = np.random.normal(
        0, intensity, np_img.shape
    )
    np_img = np.clip(
        np_img + noise, 0, 255
    ).astype(np.uint8)
    return Image.fromarray(np_img)


def apply_bw(work):
    """Black & white / red-brown tint filter."""
    work = ImageOps.grayscale(
        work
    ).convert("RGB")

    # Increase Sharpness
    # 1.0 = original, 2.5 = high sharpness
    sharpener = ImageEnhance.Sharpness(work)
    work = sharpener.enhance(2.5)

    # High Contrast
    work = ImageEnhance.Contrast(
        work
    ).enhance(1)

    # Red-Brown Tint Matrix
    rb_matrix = (
        1.15, 0, 0, 0,
        0, 0.95, 0, 0,
        0, 0, 0.85, 0,
    )
    work = work.convert("RGB", rb_matrix)

    # Add Grain (intensity 5 = subtle)
    work = add_grain(
        work, intensity=5
    )

    return work


def apply_fuji(work):
    """Fuji-style filter."""
    # 1. Pink Tint Matrix:
    # Red boosted (1.10), Green lowered (0.9)
    # Creates a subtle pink/warm hue.
    # Blue lowered (0.91) adds yellow warmth.
    pink_tint_matrix = (
        1.10, 0.0,  0.0,  0,  # Red (Boosted)
        0.0,  0.9,  0.0,  0,  # Green (Lowered)
        0.0,  0.0,  0.91, 0,  # Blue (Neutral)
    )
    work = work.convert(
        "RGB", pink_tint_matrix
    )

    # --- ADD HAZE EFFECT ---
    # Lift shadows to make them milky/gray.
    # 5 = less haze, 15 = more haze
    np_work = np.array(work).astype(
        np.float32
    )
    np_work = np_work + 5
    work = Image.fromarray(
        np.clip(
            np_work, 0, 255
        ).astype(np.uint8)
    )

    # Overlay a soft warm white haze layer
    haze_overlay = Image.new(
        "RGB", work.size, (255, 252, 240)
    )
    # 12% haze intensity
    work = Image.blend(
        work, haze_overlay, alpha=0.12
    )

    # Softer Tone: Matte, airy feel
    # Brightness shifted from 1.1 to 0.9
    work = ImageEnhance.Brightness(
        work
    ).enhance(0.9)
    work = ImageEnhance.Contrast(
        work
    ).enhance(0.8)

    # Soft Glow: Misty bloom effect
    bloom = work.filter(
        ImageFilter.GaussianBlur(radius=10)
    )
    work = Image.blend(
        work, bloom, alpha=0.25
    )

    # Final Color: keep saturation at 1.0
    # so the pink tint doesn't wash out
    work = ImageEnhance.Color(
        work
    ).enhance(1.0)

    return work


def apply_sepia(work):
    """Sepia filter."""
    # --- STAGE 1: HIGHLIGHT RECOVERY ---
    # Convert to float for precise math
    np_work = np.array(work).astype(
        np.float32
    )

    # MATTE LIFT: keeps shadows soft,
    # prevents true blacks
    np_work = np_work + 30

    # HIGHLIGHT RECOVERY:
    # Drops ceiling from 210 to 185 to
    # kill harsh ring-light hot spots
    np_work = np_work * (185.0 / 255.0)

    # Clamp and rebuild PIL Image
    np_work = np.clip(
        np_work, 0, 255
    ).astype(np.uint8)
    work = Image.fromarray(np_work)

    # --- STAGE 2: SEPIA CONVERSION ---
    sepia_matrix = np.array([
        [0.393, 0.769, 0.189],
        [0.349, 0.686, 0.168],
        [0.272, 0.534, 0.131],
    ])

    sepia_array = np.clip(
        np.array(work).dot(sepia_matrix.T),
        0,
        255,
    ).astype(np.uint8)

    # Force near-black pixels to pure black.
    # Prevents CMY composite ink from fading
    # to navy blue over time. Tune threshold.
    luminance = sepia_array.mean(axis=2)
    black_mask = luminance < 35
    sepia_array[black_mask] = [0, 0, 0]

    work = Image.fromarray(sepia_array)

    # --- STAGE 3: TONAL SMOOTHING ---
    # Uncomment to use:
    # work = ImageEnhance.Brightness(
    #     work
    # ).enhance(0.85)
    # work = ImageEnhance.Contrast(
    #     work
    # ).enhance(0.80)

    # --- STAGE 4: OVAL VIGNETTE ---
    width, height = work.size
    # Uncomment to use:
    # vignette = Image.new(
    #     'RGBA', work.size, (0, 0, 0, 0)
    # )
    # draw = ImageDraw.Draw(vignette)
    # draw.ellipse(
    #     [
    #         -width * 0.2,
    #         -height * 0.2,
    #         width * 1.2,
    #         height * 1.2,
    #     ],
    #     fill=(0, 0, 0, 100),
    # )
    # vignette = vignette.filter(
    #     ImageFilter.GaussianBlur(radius=40)
    # )
    # work.paste(vignette, (0, 0), vignette)

    # --- STAGE 5: HORIZONTAL BARS ---
    bar_mask = Image.new(
        'L', work.size, 0
    )
    bar_draw = ImageDraw.Draw(bar_mask)

    # Slim 5% coverage bars top and bottom
    bar_thickness = int(height * 0.05)
    bar_draw.rectangle(
        [0, 0, width, bar_thickness],
        fill=240,
    )
    bar_draw.rectangle(
        [
            0,
            height - bar_thickness,
            width,
            height,
        ],
        fill=240,
    )

    bar_mask = bar_mask.filter(
        ImageFilter.GaussianBlur(radius=45)
    )

    # Light opacity 50 overlay
    bar_vignette = Image.new(
        'RGBA', work.size, (0, 0, 0, 50)
    )
    bar_vignette.putalpha(bar_mask)
    work.paste(
        bar_vignette, (0, 0), bar_vignette
    )

    return work


def apply_filter(work, mode):
    """Dispatch a single photo to the correct filter by mode name."""
    if mode == "bw":
        return apply_bw(work)
    elif mode == "fuji":
        return apply_fuji(work)
    elif mode == "sepia":
        return apply_sepia(work)
    # Unknown mode: return the photo unmodified.
    return work
