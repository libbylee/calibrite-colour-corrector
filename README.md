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
`--size 150` - Shell regions are a fixed 150 x 150 pixel square. You **click** to place it (click again to move it), Enter to accept, Esc to finish. Gives the same region size every time. 
`--debug` - Saves and shows a picture of exactly which part of each checker patch was sampled, with measured vs reference colours. Press any key to close it. 
`--regions FILE`  - Re-use the boxes saved by an earlier run, with no drawing. Measures the exact same pixels again.
`--out FOLDER` - Saves results somewhere other than `outputs/`. 

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

