#!/bin/bash
# Run timesift for Mt Baker bounds
###########################################################################################
# Run first step 
python hsfm/timesift/timesift.py \
    --output-path               /data2/elilouis/mt_baker_timesift_cam_calib/ \
    --templates-dir             /home/elilouis/hipp/examples/fiducial_proxy_detection/input_data/fiducials/nagap/ \
    --bounds                    -121.94 48.84 -121.70 48.70 \
    --nagap-metadata-csv        /home/elilouis/hipp/examples/fiducial_proxy_detection/input_data/nagap_image_metadata_updated_manual.csv \
    --densecloud-quality        4 \
    --image-matching-accuracy   2 \
    --output-resolution         2 \
    --pixel-pitch               0.02 \
    --parallelization           2 \
    --reference-dem-4d          /data2/elilouis/hsfm-geomorph/data/reference_dem_highres/baker/baker_2015_utm_10m.tif \
    --reference-dem             /data2/elilouis/hsfm-geomorph/data/reference_dem_highres/baker/baker_2015_utm_m.tif \
    --license-path              uw_agisoft.lic

# Run timesift for Mt Adams bounds
###########################################################################################
# Run first step 
python hsfm/timesift/timesift.py \
    --output-path           /data2/elilouis/mt_adams_timesift_updated/ \
    --templates-dir         /home/elilouis/hipp/examples/fiducial_proxy_detection/input_data/fiducials/nagap/ \
    --bounds                -121.5857 46.2708 -121.4036 46.1195 \
    --nagap-metadata-csv        /home/elilouis/hipp/examples/fiducial_proxy_detection/input_data/nagap_image_metadata_updated_manual.csv \
    --densecloud-quality        4 \
    --image-matching-accuracy   2 \
    --output-resolution         2 \
    --pixel-pitch               0.02 \
    --parallelization           2 \
    --reference-dem-4d          /data2/elilouis/hsfm-geomorph/data/reference_dem_highres/adams/2016.tif \
    --reference-dem             /data2/elilouis/hsfm-geomorph/data/reference_dem_highres/adams/2016.tif \
    --license-path              uw_agisoft.lic

# Run timesift for Mt Hood bounds
###########################################################################################
# Run first step 
python hsfm/timesift/timesift.py \
    --output-path           /data2/elilouis/mt_hood_timesift/ \
    --templates-dir         /home/elilouis/hipp/examples/fiducial_proxy_detection/input_data/fiducials/nagap/ \
    --bounds                -121.7467 45.4722 -121.6138 45.3015 \
    --nagap-metadata-csv        /home/elilouis/hipp/examples/fiducial_proxy_detection/input_data/nagap_image_metadata_updated.csv \
    --densecloud-quality        4 \
    --image-matching-accuracy   2 \
    --output-resolution         2 \
    --pixel-pitch               0.02 \
    --parallelization           2 \
    --reference-dem-4d          /data2/elilouis/hsfm-geomorph/data/reference_dem_highres/hood/2009.tif \
    --reference-dem             /data2/elilouis/hsfm-geomorph/data/reference_dem_highres/hood/2009.tif \
    --license-path              uw_agisoft.lic