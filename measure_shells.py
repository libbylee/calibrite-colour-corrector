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
    PATCH_MARGIN, calculate_correction, draw_checker_debug, is_raw_file, load_image, orient_checker,
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


def make_view(img, max_dim, allow_upscale=False, max_zoom=8.0):
    """Copy of the photo sized to fit the window + the scale used.
    Big photos are shrunk. With allow_upscale (used by --zoom) small crops are
    enlarged (up to max_zoom times, nearest-neighbour so you see real pixels)."""
    h, w = img.shape[:2]
    scale = max_dim / max(h, w)
    scale = min(scale, max_zoom) if allow_upscale else min(1.0, scale)
    if scale < 1:
        return cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA), scale
    if scale > 1:
        return cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST), scale
    return img, 1.0


def select_box(title, img, max_dim=1400, allow_upscale=False):
    """Drag a rectangle. Returns (x, y, w, h) in ORIGINAL pixel coordinates,
    or None if cancelled."""
    view, scale = make_view(img, max_dim, allow_upscale)
    x, y, bw, bh = cv2.selectROI(title, view, showCrosshair=False)
    cv2.destroyWindow(title)
    cv2.waitKey(1)
    if bw == 0 or bh == 0:
        return None
    return tuple(int(round(v / scale)) for v in (x, y, bw, bh))

def select_square(title, img, size, max_dim=1400, allow_upscale=False):
    """Click to place a fixed size x size square (centred on the click).
    Click again to move it, Enter/Space to accept, Esc to cancel.
    Returns (x, y, size, size) in ORIGINAL pixel coordinates, or None."""
    h, w = img.shape[:2]
    size = int(min(size, h, w))
    view, scale = make_view(img, max_dim, allow_upscale)
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

def draw_label(img, text, box, placed, scale, obstacles=()):
    """Write text next to a box on the overlay picture: white text with a dark
    outline, put in the first spot (above, below, inside) that does not overlap a
    label already drawn or any OTHER box. `placed` is the list of label rectangles
    drawn so far; `obstacles` is a list of (x0, y0, x1, y1) of the other boxes."""
    x, y, w, h = box
    font = cv2.FONT_HERSHEY_SIMPLEX
    th = max(1, int(round(scale * 2)))
    (tw, tht), base = cv2.getTextSize(text, font, scale, th)
    pad = max(2, int(scale * 4))
    ih, iw = img.shape[:2]

    def rect(p):
        px, py = p
        return (px - pad, py - tht - pad, px + tw + pad, py + base + pad)

    def overlaps(a, b):
        return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])

    def fits(r):
        return r[0] >= 0 and r[1] >= 0 and r[2] <= iw and r[3] <= ih

    step = tht + 2 * pad
    candidates = [
        (x, y - pad),                        # above, left-aligned
        (x, y + h + tht + pad),              # below, left-aligned
        (x + w - tw, y - pad),               # above, right-aligned
        (x + w - tw, y + h + tht + pad),     # below, right-aligned
        (x + pad, y + tht + pad),            # inside, top-left
        (x + pad, y + h - pad),              # inside, bottom-left
    ]
    # fall back to stacking further above / below the box
    candidates += [(x, y - pad - k * step) for k in range(1, 15)]
    candidates += [(x, y + h + tht + pad + k * step) for k in range(1, 15)]

    chosen = None
    for p in candidates:
        r = rect(p)
        if fits(r) and not any(overlaps(r, q) for q in placed) \
                and not any(overlaps(r, o) for o in obstacles):
            chosen = p
            break
    if chosen is None:                       # nowhere free: put it inside its own box
        chosen = (x + pad, y + tht + pad)
    px = int(min(max(chosen[0], pad), max(pad, iw - tw - pad)))
    py = int(min(max(chosen[1], tht + pad), max(tht + pad, ih - base - pad)))
    placed.append(rect((px, py)))
    cv2.putText(img, text, (px, py), font, scale, (0, 0, 0), th + 2, cv2.LINE_AA)
    cv2.putText(img, text, (px, py), font, scale, (255, 255, 255), th, cv2.LINE_AA)
def pick_region(kind, title, img, zoom, size=None):
    """Select an area. kind='box' -> drag a rectangle; kind='square' -> click a
    fixed size x size square. Returns (x, y, w, h) in ORIGINAL photo pixels, or
    None if cancelled.

    With zoom=True it is a two-step pick: (1) drag a rough box around the area on
    the whole photo, (2) pick precisely on an enlarged view of just that area.
    The result is converted back to full-resolution photo coordinates, so the
    measured pixels (and the fixed square size) are exactly as without --zoom."""
    def select(t, im, up=False):
        if kind == "square":
            return select_square(t, im, size, allow_upscale=up)
        return select_box(t, im, allow_upscale=up)

    if not zoom:
        return select(title, img)

    rough = select_box("ZOOM STEP 1 of 2: drag a rough box around the area, Enter "
                       "to continue (c = cancel)", img)
    if rough is None:
        return None
    rx, ry, rw, rh = rough
    ih, iw = img.shape[:2]
    w, h = rw, rh
    if kind == "square":     # the crop must hold the whole square with room to move it
        need = int(size * 1.5)
        w, h = max(w, need), max(h, need)
    w, h = min(w, iw), min(h, ih)
    x0 = max(0, min(int(round(rx + rw / 2.0 - w / 2.0)), iw - w))
    y0 = max(0, min(int(round(ry + rh / 2.0 - h / 2.0)), ih - h))
    sub = img[y0:y0 + h, x0:x0 + w]

    fine = select("ZOOM STEP 2 of 2: " + title, sub, up=True)
    if fine is None:
        return None
    fx, fy, fw, fh = fine
    return (fx + x0, fy + y0, fw, fh)

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
    ap.add_argument("--zoom", action="store_true",
                    help="two-step selection: rough box first, then pick precisely "
                         "on an enlarged view of that area")
    ap.add_argument("--label-scale", type=float, default=1.0,
                    help="size of the labels on the selection picture "
                         "(1 = default, 0.5 = half size)")
    ap.add_argument("--wb", choices=["daylight", "camera"], default="daylight",
                    help="raw files only: fixed daylight white balance (default) "
                         "or the as-shot camera white balance")
    args = ap.parse_args()

    try:
        img, load_info = load_image(args.photo, wb=args.wb)
    except Exception as e:
        sys.exit(f"Could not load {args.photo}: {e}")
    photo_hash = file_sha256(args.photo)


    ih, iw = img.shape[:2]

    stem = Path(args.photo).stem
    sample = args.sample or stem
    out = Path(args.out)
    out.mkdir(exist_ok=True)


    if is_raw_file(args.photo):
        print(f"Raw file developed with fixed settings: white balance = {args.wb}, "
              f"no auto-brightness, sRGB, 8-bit.")
        converted = out / f"{stem}_converted.png"
        cv2.imwrite(str(converted), img)
        print(f"Developed image saved to {converted}")

    # --- 1. checker box ---------------------------------------------------
    saved_regions = None
    if args.regions:
        saved = json.loads(Path(args.regions).read_text())
        if saved.get("image_sha256") != photo_hash:
            print("WARNING: this photo is not byte-identical to the one the saved "
                  "regions were made on. The boxes may not land on the same things.")
        if saved.get("patch_margin", PATCH_MARGIN) != PATCH_MARGIN:
            print("WARNING: the saved regions used a different patch margin.")

        old_load = saved.get("image_loading")
        if old_load is not None and old_load != load_info:
            print("WARNING: the photo was loaded/developed differently from when the "
                  f"regions were saved.\n  then: {old_load}\n  now:  {load_info}")
            
        checker_box = tuple(saved["checker_box"])
        saved_regions = [(r["label"], tuple(r["box"])) for r in saved["regions"]]
        print(f"Using the saved boxes from {args.regions} (no drawing needed).")
    else:
        checker_box = pick_region(
        "box", "1) Select the checker (24 patches only) - Enter to confirm",
            img, args.zoom)
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
                box = pick_region(
                    "square",
                    f"2) Click to place a {args.size}px square - Enter to accept, Esc to finish",
                    img, args.zoom, size=args.size)
            else:
                box = pick_region(
                    "box", "2) Select a shell region - Enter to confirm, c to cancel",
                    img, args.zoom)
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
    t = max(2, int(max(ih, iw) / 700))                            # box line thickness
    label_scale = args.label_scale * max(0.5, max(ih, iw) / 5000.0)
    placed_labels = []
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
        others = [(bx, by, bx + bw, by + bh) for _, (bx, by, bw, bh) in regions
                  if (bx, by, bw, bh) != (x, y, w, h)]
        draw_label(overlay, label, (x, y, w, h), placed_labels, label_scale, others)

    # --- 5. save ----------------------------------------------------------
    cv2.imwrite(str(out / f"{stem}_selection.png"), overlay)

    if saved_regions is None and regions:
        regions_path = out / f"{stem}_regions.json"
        regions_path.write_text(json.dumps({
            "photo": Path(args.photo).name,
            "image_sha256": photo_hash,
            "patch_margin": PATCH_MARGIN,
            "image_loading": load_info,
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