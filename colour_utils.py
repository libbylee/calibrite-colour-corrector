"""
Shared helpers for the ColorChecker correction workflow.

Everything (checker patches AND shell regions) goes through bgr_to_lab(),
so the two can never use different colour conversions.
"""

import cv2
import numpy as np
import pandas as pd

COLOR_NAMES = [
    "Dark skin", "Light skin", "Blue sky", "Foliage", "Blue flower", "Bluish green",
    "Orange", "Purplish blue", "Moderate red", "Purple", "Yellow green", "Orange yellow",
    "Blue", "Green", "Red", "Yellow", "Magenta", "Cyan",
    "White", "Neutral 8", "Neutral 6.5", "Neutral 5", "Neutral 3.5", "Black",
]
PATCH_LABELS = [f"{col}{row}" for row in range(1, 5) for col in "ABCDEF"]

COLS, ROWS = 6, 4

# Fraction of each patch skipped at every edge when sampling, so the sample
# stays well inside the patch (0.25 -> the middle 50% of each side is used).
PATCH_MARGIN = 0.25


def bgr_to_lab(bgr_pixels):
    """N x 3 (or single) BGR 0-255 pixels -> N x 3 standard CIE L*a*b*.

    NOTE: OpenCV assumes sRGB with a D65 white point. Check that your
    reference values use the same illuminant (Calibrite's published
    values are normally D50).
    """
    px = np.clip(np.round(np.asarray(bgr_pixels, dtype=float)), 0, 255)
    px = px.astype(np.uint8).reshape(-1, 1, 3)
    lab = cv2.cvtColor(px, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(float)
    lab[:, 0] *= 100.0 / 255.0   # OpenCV 8-bit L is 0-255
    lab[:, 1:] -= 128.0          # OpenCV 8-bit a, b are offset by 128
    return lab


def lab_to_bgr(lab_values):
    """N x 3 standard L*a*b* -> N x 3 BGR 0-255 (for drawing swatches only)."""
    lab = np.asarray(lab_values, dtype=float).reshape(-1, 3)
    px = np.empty((len(lab), 1, 3), np.uint8)
    px[:, 0, 0] = np.clip(np.round(lab[:, 0] * 255.0 / 100.0), 0, 255)
    px[:, 0, 1] = np.clip(np.round(lab[:, 1] + 128.0), 0, 255)
    px[:, 0, 2] = np.clip(np.round(lab[:, 2] + 128.0), 0, 255)
    return cv2.cvtColor(px, cv2.COLOR_LAB2BGR).reshape(-1, 3)


def checker_sample_boxes(shape, margin=PATCH_MARGIN):
    """The 24 sampling rectangles (x0, y0, x1, y1) inside each patch,
    in A1, B1 ... F1, A2 ... F4 order, for a checker image of this shape."""
    h, w = shape[:2]
    sw, sh = w // COLS, h // ROWS
    mx, my = int(sw * margin), int(sh * margin)
    boxes = []
    for row in range(ROWS):
        for col in range(COLS):
            boxes.append((col * sw + mx, row * sh + my,
                          (col + 1) * sw - mx, (row + 1) * sh - my))
    return boxes


def extract_checker_lab(checker_bgr, margin=PATCH_MARGIN):
    """Median L*a*b* of the middle of each of the 24 patches.

    checker_bgr must be cropped tight to the 6x4 patches (no border), with
    A1 (Dark skin) top-left.
    Returns a 24 x 3 array in A1, B1 ... F1, A2 ... F4 order.
    """
    lab = []
    for x0, y0, x1, y1 in checker_sample_boxes(checker_bgr.shape, margin):
        patch = checker_bgr[y0:y1, x0:x1].reshape(-1, 3)
        lab.append(bgr_to_lab(np.median(patch, axis=0))[0])
    return np.array(lab)


def orient_checker(checker_bgr, reference_lab):
    """Try every rotation that gives a wide (6 cols x 4 rows) grid and keep
    the one whose patches best match the reference values.

    Returns (rotated_image, quarter_turns, mean_error, measured_lab).
    A large mean_error even after orienting means the problem is not
    rotation (crop, lighting or illuminant mismatch).
    """
    ref = np.asarray(reference_lab, dtype=float)
    best = None
    for k in range(4):
        rotated = np.ascontiguousarray(np.rot90(checker_bgr, k))
        if rotated.shape[1] <= rotated.shape[0]:
            continue
        lab = extract_checker_lab(rotated)
        err = np.linalg.norm(lab - ref, axis=1).mean()
        if best is None or err < best[2]:
            best = (rotated, k, err, lab)
    if best is None:
        raise ValueError("Checker box must be wider than it is tall.")
    return best


def draw_checker_debug(checker_bgr, measured_lab, reference_lab, margin=PATCH_MARGIN):
    """Debug picture showing exactly what was sampled from the checker.

    LEFT : the (oriented) checker crop with a green box + label (A1...F4)
           over the part of every patch that was actually sampled.
    RIGHT: one cell per patch; top half = the colour measured there,
           bottom half = the reference colour for that patch (approximate:
           reference Lab is drawn with OpenCV's D65 conversion).
    If the two halves of a cell look clearly different, that patch is where
    the correction is coming from.
    """
    h, w = checker_bgr.shape[:2]
    sw, sh = w // COLS, h // ROWS
    scale = max(0.5, sh / 220.0)
    thick = max(1, int(round(scale * 2)))

    sampled = checker_bgr.copy()
    for i, (x0, y0, x1, y1) in enumerate(checker_sample_boxes(checker_bgr.shape, margin)):
        cv2.rectangle(sampled, (x0, y0), (x1, y1), (0, 255, 0), thick)
        row, col = divmod(i, COLS)
        pos = (col * sw + 6, row * sh + int(28 * scale))
        cv2.putText(sampled, PATCH_LABELS[i], pos, cv2.FONT_HERSHEY_SIMPLEX,
                    scale, (0, 0, 0), thick + 3)
        cv2.putText(sampled, PATCH_LABELS[i], pos, cv2.FONT_HERSHEY_SIMPLEX,
                    scale, (255, 255, 255), thick)

    measured_bgr = lab_to_bgr(measured_lab)
    reference_bgr = lab_to_bgr(reference_lab)
    panel = np.full_like(sampled, 255)
    for i in range(COLS * ROWS):
        row, col = divmod(i, COLS)
        y0, x0 = row * sh, col * sw
        panel[y0:y0 + sh // 2, x0:x0 + sw] = measured_bgr[i]
        panel[y0 + sh // 2:y0 + sh, x0:x0 + sw] = reference_bgr[i]
        cv2.putText(panel, PATCH_LABELS[i], (x0 + 6, y0 + int(28 * scale)),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 3)
        cv2.putText(panel, PATCH_LABELS[i], (x0 + 6, y0 + int(28 * scale)),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thick)

    combined = np.hstack([sampled, panel])
    cap_h = int(70 * scale)
    caption = np.full((cap_h, combined.shape[1], 3), 255, np.uint8)
    fs = max(0.6, combined.shape[1] / 3000.0)
    cv2.putText(caption, "LEFT: green boxes = pixels sampled for each patch.   "
                "RIGHT: top half = measured colour, bottom half = reference (approx.)",
                (10, int(cap_h * 0.65)), cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 0),
                max(1, int(fs * 2)))
    return np.vstack([caption, combined])


def calculate_correction(measured_lab, reference_lab):
    """Average (reference - measured) offset, plus per-patch errors.

    Returns (offset[3], error_before[24], error_after[24]) where errors are
    straight-line L*a*b* distances (CIE76 delta E) per patch.
    """
    diff = np.asarray(reference_lab, dtype=float) - np.asarray(measured_lab, dtype=float)
    offset = diff.mean(axis=0)
    before = np.linalg.norm(diff, axis=1)
    after = np.linalg.norm(diff - offset, axis=1)
    return offset, before, after


def region_lab(bgr_region):
    """Median L*a*b* over every pixel in a region (shrugs off glare)."""
    return np.median(bgr_to_lab(bgr_region.reshape(-1, 3)), axis=0)


def save_correction(offset, filename):
    pd.DataFrame({"Parameter": ["L*", "a*", "b*"], "Correction": offset}).to_csv(
        filename, index=False
    )


def load_correction(filename):
    return pd.read_csv(filename)["Correction"].values