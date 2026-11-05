# Calibrite ColorChecker Version 2.0

Measure the CIE L\*a\*b\* colour of mussel shells from photos, using a Calibrite
(X-Rite) ColorChecker in the same photo to correct for the camera and lighting.

For every photo you:
1. mark the ColorChecker (24 colour squares),
2. mark one or more regions on the shell,

and the script outputs the raw and corrected L\*a\*b\* values of each shell region
in a CSV you can analyze elsewhere.

---

## What's in this repo

`measure_shells.py` - The script you run. Handles one photo at a time. |
`colour_utils.py` - Shared helper functions (colour conversion, checker sampling, correction). Must sit next to `measure_shells.py`. |
`references/reference_values.py` - The 24 reference L\*a\*b\* values of the ColorChecker (`colour_checker_lab_reference`, in order A1 to F4). 
| `outputs/` - All results go here. 
| `old/`, `Colour_extractor`, `Colour_corrector` - Earlier two-step version, kept for reference. Not needed.

---

## One-time setup

You need Python 3 and three libraries. In the VS Code terminal, from the project folder:

```
python3 -m pip install opencv-python numpy pandas
```

## Photo Notes: 
- The checker can be rotated or upside down. The script works out the orientation itself.

---

## Measuring a photo

From the project folder:

```
python3 measure_shells.py IMG_9563.jpg --sample Mussel_1
```

(`--sample` is the shell ID that goes in the results. If you leave it out, the photo's file name is used.)

Then, in the windows that open:

1. **Select the checker.** Drag a box around the 24 colour squares **only**, tight to the squares with no border, then press **Enter**.
2. The terminal prints the correction it calculated and how well it fits.
3. **Select a shell region.** Drag a box on a clean part of the shell and press **Enter**.
4. **Type a label** in the terminal for that spot (for example `mid`, `edge`), then press Enter.
5. When asked `Another region on this photo? [y/N]`, type `y` and Enter to pick another spot on the same shell, or just press Enter to finish.


The results file is only written after the last question, so wait for the line that says `Saved ... region(s)`.

### Options

`--sample NAME` - Shell ID written to the results. 
`--size N`  Shell regions are a fixed **N x N pixel square** (for example `--size 150`). You **click** to place the square instead of dragging a box, so every region is exactly the same size. 
`--debug` - Saves and shows a picture of exactly which part of each checker patch was sampled, with measured vs reference colours. Press any key to close it. 
`--regions FILE`  - Re-use the boxes saved by an earlier run, with no drawing. Measures the exact same pixels again.
`--out FOLDER` - Saves results somewhere other than `outputs/`. 
`--zoom`  Two-step selection. First drag a rough box around the area on the whole photo, then pick the precise box (or click the square) on an **enlarged view** of just that area. Works for the checker and for shell regions, with or without `--size`. The result is converted back to full-resolution pixels. 
`--regions FILE` Re-use the boxes saved by an earlier run (`outputs/<photo>_regions.json`), with no drawing. Measures the exact same pixels again.
`--wb daylight` or `--wb camera`  **Raw files only.** `daylight` (default) uses the same fixed white balance for every photo. `camera` uses the white balance the camera recorded for each shot, which usually fixes a yellow or blue tint. Use **one** setting for every photo you compare. 
`--label-scale X` The size of the labels on the `_selection.png` picture. `1` is the default, `0.5` is half size, `1.5` is larger. Use a smaller number if your regions are close together.
`--help` or `-h` Prints the list of options in the terminal. 

For example (using different options):

python3 measure_shells.py IMG_9563.jpg --sample Mussel_1 --size 150 --debug

---

## Measuring many photos

Run the script once per photo. Every run adds its rows to the same
`outputs/all_results.csv`, so at the end you have one table.

- **Several spots on one shell:** answer `y` to "Another region on this photo?" and give each spot its own label.
- **Several photos:** run the command again for each photo with a new `--sample` name.
- **Keep names consistent.** Use the same region labels (`umbo`, `mid`, `edge`) across shells so spots can be compared. Put any group in the sample name (for example `Mussel_02_infested`).

To go through a whole folder of photos in one go (you still draw the boxes on each photo yourself):

```
for f in photos/*.jpg; do python3 measure_shells.py "$f" --sample "$(basename "$f" .jpg)" --size 150; done
```

Two things to watch:
- `all_results.csv` only ever **adds** rows. If you re-run the same photo you get duplicate rows, so delete the bad ones. To start a new project, move or rename `all_results.csv` first.
- Each photo's own `<photo>_results.csv` is overwritten if you re-run that photo.

---

## What gets saved

Everything goes into `outputs/`. For a photo called `IMG_9563.jpg`:

| File | What it is |
|---|---|
| `all_results.csv` | **The main results.** One row per shell region, across all photos. |
| `IMG_9563_results.csv` | Rows for this photo only. |
| `IMG_9563_selection.png` | Your photo with the boxes drawn on it. Open this to check you selected the right places. |
| `IMG_9563_checker_debug.png` | Only with `--debug`. Which part of each checker patch was sampled, and measured vs reference colours. |
| `IMG_9563_<label>_crop.png` | The exact pixels measured for each shell region (lossless). |
| `IMG_9563_checker_crop.png` | The exact checker crop used. |
| `IMG_9563_correction.csv` | The correction that was applied. |
| `IMG_9563_regions.json` | The saved boxes, for re-measuring the same pixels with `--regions`. |

To open the folder in Finder: `open outputs`. To print the results in the terminal: `cat outputs/all_results.csv`.

---

## Reading the results

Each row of `all_results.csv` is one shell region.

| Column | Meaning |
|---|---|
| `Photo`, `Sample`, `Region` | Which photo, which shell, which spot. |
| `L*`, `a*`, `b*` | Colour measured from the photo, **before** correction. |
| `L_corrected`, `a_corrected`, `b_corrected` | Colour **after** correction using the checker. **Use these for analysis.** |
| `Pixels`, `Box_x`, `Box_y`, `Box_w`, `Box_h` | Size and position of the measured box. |
| `Boxes` | `drawn` (selected by hand) or `saved` (re-used from a regions file). |

CIE L\*a\*b\*:
- **L\*** is lightness: 0 is black, 100 is white.
- **a\*** runs from green (negative) to red (positive).
- **b\*** runs from blue (negative) to yellow (positive).

The value for each region is the **median** of every pixel in the box.

To compare two measurements, use the colour difference
ΔE = √(ΔL\*² + Δa\*² + Δb\*²). Roughly, a ΔE of 2 to 3 is the smallest difference a
person can notice; larger values are clearly different. A single measurement doesn't
mean much by itself. Compare several regions per shell and several shells per group.

### Exporting for analysis

`outputs/all_results.csv` is a normal CSV file. Open it in Excel or Numbers, or import
it into JMP, R or Python. The columns to analyze are `Sample`, `Region`,
`L_corrected`, `a_corrected` and `b_corrected`. Keep the whole `outputs/` folder as the
record of what was measured.

---

## Checking the colour correction

When you run the script it prints something like:

```
Mean patch error vs reference (before correction): 18.8
Correction to add:  dL*=-12.66  da*=-4.11  db*=-7.60
Per-patch error (delta E76): mean 18.8 -> 10.6 after correction, worst patch 25.0
```

- The **mean error before correction** tells you how far the photo's colours are from the true checker colours. Over about 20 triggers a warning: check the crop, the lighting, and the reference values.
- The **mean error after correction** tells you how well a single correction fits. Below about 3 is good. Higher means the corrected values are approximate.
- Run with `--debug` and open `*_checker_debug.png`. The green boxes should sit inside each colour square, with A1 (dark brown) at the top left of the left-hand picture, and the top and bottom halves of each patch on the right should be fairly close.

### Reproducibility

- `*_regions.json` saves the exact boxes and a fingerprint of the photo. Re-running with
  `--regions outputs/IMG_9563_regions.json` measures the identical pixels and gives identical numbers.
- Saved boxes only match the **same photo file**. For a different photo you draw new
  boxes. Use `--size` so every region is the same size.
- If the camera is fixed and nothing moves between photos, you can try another
  photo's regions file. The script warns that the photo is different, so check the
  `_selection.png` to confirm the boxes landed in the right places.

---

## Changing the sampling area on the checker

Each checker patch is sampled over the middle of the square. This is set in `colour_utils.py`:

```
PATCH_MARGIN = 0.25
```

| `PATCH_MARGIN` | Area sampled in each patch |
|---|---|
| 0.25 | middle 50% of each side (default) |
| 0.40 | middle 20% of each side |
| 0.45 | middle 10% of each side |

Don't use 0.5 or higher (the area would be empty). A single pixel is not recommended
because it picks up camera noise.

---

## Known limitations

- **One constant correction.** The script adds one average offset to L\*, a\* and b\*. This is a simple correction. If the mean error after correction is high, treat the corrected values as approximate. A per-channel or matrix fit would do better.
- **Illuminant.** The colour conversion uses OpenCV, which assumes a D65 white point. Calibrite's published reference values are usually D50. Check which one `references/reference_values.py` contains. A mismatch adds an error that the correction can't fully remove.
- **Conditions must match.** A correction only applies to the photo it came from, so every photo needs its own checker in frame under the same lighting as the shell.
- **Rectangular regions only.** Regions are rectangles (or squares with `--size`), so choose flat, glare-free spots on the shell.