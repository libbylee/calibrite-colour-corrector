"""
measure_shells.py -- run locally (VS Code terminal) on one photo that contains
BOTH the Calibrite ColorChecker and the mussel shell.

Basic use:
    python3 measure_shells.py IMG_9563.jpg --sample Mussel_1

Options:
    --debug            save (and show) a picture of exactly which part of each
                       checker patch was sampled, measured vs reference colour
    --size 150         shell regions are a fixed 150 x 150 pixel square: you
                       CLICK to place it instead of dragging a box (same area
                       size every time)
    --regions FILE     re-use the boxes saved by an earlier run (FILE is the
                       outputs/<photo>_regions.json it wrote) -- no drawing, so
                       the exact same pixels are measured again

What it walks you through:
  1. Drag a box around the 24 colour patches only (tight, no border), press Enter.
  2. The script finds the right orientation and works out the correction.
  3. Select shell regions (drag a box + Enter, or click with --size), type a label.
Outputs (in ./outputs): results CSV, correction CSV, a selection overlay, the
saved regions file, and lossless PNG crops of the checker and every region.

Requires: pip install opencv-python numpy pandas
(use opencv-python, NOT opencv-python-headless, or the windows won't open)
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from colour_utils import (
    PATCH_MARGIN, calculate_correction, draw_checker_debug, orient_checker,
    region_lab, save_correction,
)
from references.reference_values import colour_checker_lab_reference


def file_sha256(path):
    """Fingerprint of the photo file, so a saved-regions file can tell if you
    point it at a different photo."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_name(label):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_") or "region"


def make_view(img, max_dim):
    """Shrunken copy for big photos (so the window fits the screen) + scale."""
    h, w = img.shape[:2]
    scale = min(1.0, max_dim / max(h, w))
    if scale < 1:
        return cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA), scale
    return img, 1.0


def select_box(title, img, max_dim=1400):
    """Drag a rectangle. Returns (x, y, w, h) in ORIGINAL pixel coordinates,
    or None if cancelled."""
    view, scale = make_view(img, max_dim)
    x, y, bw, bh = cv2.selectROI(title, view, showCrosshair=False)
    cv2.destroyWindow(title)
    cv2.waitKey(1)
    if bw == 0 or bh == 0:
        return None
    return tuple(int(round(v / scale)) for v in (x, y, bw, bh))


def select_square(title, img, size, max_dim=1400):
    """Click to place a fixed size x size square (centred on the click).
    Click again to move it, Enter/Space to accept, Esc to cancel.
    Returns (x, y, size, size) in ORIGINAL pixel coordinates, or None."""
    h, w = img.shape[:2]
    size = int(min(size, h, w))
    view, scale = make_view(img, max_dim)
    click = {}

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            click["pt"] = (x, y)

    cv2.namedWindow(title)
    cv2.setMouseCallback(title, on_mouse)
    result = None
    while True:
        frame = view.copy()
        if "pt" in click:
            half = size * scale / 2.0
            x, y = click["pt"]
            cv2.rectangle(frame, (int(x - half), int(y - half)),
                          (int(x + half), int(y + half)), (0, 0, 255), 2)
        cv2.imshow(title, frame)
        key = cv2.waitKey(20) & 0xFF
        if key in (13, 10, 32) and "pt" in click:      # Enter / Space = accept
            cx, cy = click["pt"][0] / scale, click["pt"][1] / scale
            x0 = int(round(cx - size / 2.0))
            y0 = int(round(cy - size / 2.0))
            x0 = max(0, min(x0, w - size))
            y0 = max(0, min(y0, h - size))
            result = (x0, y0, size, size)
            break
        if key in (27, ord("c")):                       # Esc / c = cancel
            break
    cv2.destroyWindow(title)
    cv2.waitKey(1)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo", help="photo containing the checker and the shell")
    ap.add_argument("--sample", help="shell ID for the output (default: photo file name)")
    ap.add_argument("--out", default="outputs", help="output folder")
    ap.add_argument("--debug", action="store_true",
                    help="save and show where each checker patch was sampled")
    ap.add_argument("--size", type=int,
                    help="fixed N x N pixel square for shell regions; click to place")
    ap.add_argument("--regions",
                    help="re-use boxes saved by an earlier run (a *_regions.json file)")
    args = ap.parse_args()

    img = cv2.imread(args.photo)
    if img is None:
        sys.exit(f"Could not load image: {args.photo}")
    photo_hash = file_sha256(args.photo)
    ih, iw = img.shape[:2]

    stem = Path(args.photo).stem
    sample = args.sample or stem
    out = Path(args.out)
    out.mkdir(exist_ok=True)

    # --- 1. checker box ---------------------------------------------------
    saved_regions = None
    if args.regions:
        saved = json.loads(Path(args.regions).read_text())
        if saved.get("image_sha256") != photo_hash:
            print("WARNING: this photo is not byte-identical to the one the saved "
                  "regions were made on. The boxes may not land on the same things.")
        if saved.get("patch_margin", PATCH_MARGIN) != PATCH_MARGIN:
            print("WARNING: the saved regions used a different patch margin.")
        checker_box = tuple(saved["checker_box"])
        saved_regions = [(r["label"], tuple(r["box"])) for r in saved["regions"]]
        print(f"Using the saved boxes from {args.regions} (no drawing needed).")
    else:
        checker_box = select_box("1) Select the checker (24 patches only) - Enter to confirm", img)
        if checker_box is None:
            sys.exit("No checker selected.")
    cx, cy, cw, ch = checker_box
    checker = img[cy:cy + ch, cx:cx + cw]
    cv2.imwrite(str(out / f"{stem}_checker_crop.png"), checker)

    # --- 2. orientation + correction -------------------------------------
    oriented, turns, err, measured = orient_checker(checker, colour_checker_lab_reference)
    print(f"\nChecker rotated by {turns * 90} degrees to match the reference.")
    print(f"Mean patch error vs reference (before correction): {err:.1f}")
    if err > 20:
        print("  WARNING: large error. Check the crop is tight on the patches, the "
              "lighting, and that the reference illuminant matches (D50 vs D65).")

    offset, before, after = calculate_correction(measured, colour_checker_lab_reference)
    print(f"Correction to add:  dL*={offset[0]:+.2f}  da*={offset[1]:+.2f}  db*={offset[2]:+.2f}")
    print(f"Per-patch error (delta E76): mean {before.mean():.1f} -> {after.mean():.1f} after correction, "
          f"worst patch {after.max():.1f}")
    if after.mean() > 3:
        print("  NOTE: a single constant offset leaves a fairly large error here. "
              "Treat corrected values with caution (a per-channel or matrix fit would do better).")
    save_correction(offset, out / f"{stem}_correction.csv")

    if args.debug:
        dbg = draw_checker_debug(oriented, measured, colour_checker_lab_reference)
        dbg_path = out / f"{stem}_checker_debug.png"
        cv2.imwrite(str(dbg_path), dbg)
        print(f"Debug picture of the checker sampling saved to {dbg_path}")
        view, _ = make_view(dbg, 1600)
        title = "Checker debug - press any key to continue"
        cv2.imshow(title, view)
        cv2.waitKey(0)
        cv2.destroyWindow(title)
        cv2.waitKey(1)

    # --- 3. shell regions: loaded or selected -----------------------------
    if saved_regions is not None:
        regions = saved_regions
    else:
        regions = []
        n = 0
        while True:
            if args.size:
                box = select_square(
                    f"2) Click to place a {args.size}px square - Enter to accept, Esc to finish",
                    img, args.size)
            else:
                box = select_box("2) Select a shell region - Enter to confirm, c to cancel", img)
            if box is None:
                if not regions:
                    print("No shell region selected.")
                break
            n += 1
            label = input(f"Label for this region [ROI{n}]: ").strip() or f"ROI{n}"
            regions.append((label, box))
            if input("Another region on this photo? [y/N]: ").strip().lower() != "y":
                break

    # --- 4. measure --------------------------------------------------------
    overlay = img.copy()
    t = max(2, int(max(ih, iw) / 400))
    cv2.rectangle(overlay, (cx, cy), (cx + cw, cy + ch), (0, 255, 0), t)

    rows = []
    for label, (x, y, w, h) in regions:
        if x < 0 or y < 0 or x + w > iw or y + h > ih:
            print(f"  Skipping {label}: its box is outside this photo.")
            continue
        crop = img[y:y + h, x:x + w]
        cv2.imwrite(str(out / f"{stem}_{safe_name(label)}_crop.png"), crop)

        lab = region_lab(crop)
        corr = lab + offset
        rows.append({
            "Photo": Path(args.photo).name, "Sample": sample, "Region": label,
            "L*": lab[0], "a*": lab[1], "b*": lab[2],
            "L_corrected": corr[0], "a_corrected": corr[1], "b_corrected": corr[2],
            "Pixels": w * h, "Box_x": x, "Box_y": y, "Box_w": w, "Box_h": h,
            "Boxes": "saved" if saved_regions is not None else "drawn",
        })
        print(f"  {label}: raw L*={lab[0]:.1f} a*={lab[1]:.1f} b*={lab[2]:.1f}  ->  "
              f"corrected L*={corr[0]:.1f} a*={corr[1]:.1f} b*={corr[2]:.1f}")

        cv2.rectangle(overlay, (x, y), (x + w, y + h), (0, 0, 255), t)
        cv2.putText(overlay, label, (x, max(y - 8, 20)), cv2.FONT_HERSHEY_SIMPLEX,
                    t / 2, (0, 0, 255), t)

    # --- 5. save ----------------------------------------------------------
    cv2.imwrite(str(out / f"{stem}_selection.png"), overlay)

    if saved_regions is None and regions:
        regions_path = out / f"{stem}_regions.json"
        regions_path.write_text(json.dumps({
            "photo": Path(args.photo).name,
            "image_sha256": photo_hash,
            "patch_margin": PATCH_MARGIN,
            "checker_box": [int(v) for v in checker_box],
            "regions": [{"label": lbl, "box": [int(v) for v in b]} for lbl, b in regions],
        }, indent=2))
        print(f"\nBoxes saved to {regions_path} -- re-run with  --regions {regions_path}  "
              f"to measure the exact same pixels again.")

    if rows:
        df = pd.DataFrame(rows)
        df.to_csv(out / f"{stem}_results.csv", index=False)
        master = out / "all_results.csv"
        if master.exists():
            df = pd.concat([pd.read_csv(master), df], ignore_index=True)
        df.to_csv(master, index=False)
        print(f"Saved {len(rows)} region(s) to {out / f'{stem}_results.csv'} "
              f"and appended to {master}")
    print(f"Selection overlay saved to {out / f'{stem}_selection.png'} -- open it to check your boxes.")


if __name__ == "__main__":
    main()