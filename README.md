# calibritecolourcorrector
This is an automated colour corrector for computing the l*a*b* values of images.

## How to use:

1. Crop the photo with measuring region of interest and ColorChecker to just include the Calibrite Passport ColorChecker, with colours in the same order and orientation. Make sure that the photo is zoomed in enough to the point where borders are not shown: Crop image such that order of colours and orientation are as below:

![Example Image](test_photo.jpg)

2. Run the colour_extractor script with the correct path file to the photo

3. Run the colour_corrector script with the new measured_colorchecker csv file, make sure to update the file paths as needed:
 # File paths - UPDATE THESE
    colorchecker_measured_csv = "measured_colorchecker.csv"
    mussel_data_csv = "mussel_measurements.csv"
    corrected_output_csv = "mussel_measurements_corrected.csv"

4. New corrected values to be adjusted should be computed in a new csv. Export those values and adjust measured mussel data as needed (manually), or upload mussel measurements to automatically adjust these values. 



