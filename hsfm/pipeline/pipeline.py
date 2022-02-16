import os
import pandas as pd
import geopandas as gpd
import json
import argparse
import rioxarray as rix
from shapely.geometry import box

import hsfm.metashape
import hsfm.geospatial
import hsfm.asp
import hsfm.core
import hsfm.plot
import hsfm.utils

class Pipeline:
    """
    Historical Structure from Motion pipeline.
    Generates a DEM for a given set of images, runs a series of alignment steps, and outputs
    various quality control plots along the way.

    The pipeline completes the following steps in order:
        1. Creates point cloud from images using Metashape
        2. Extracts DEM and orthomosaic from Metashape project
        3. Runs point cloud alignment routine on the extracted DEM and the provided reference
            DEM using NASA ASP
        4. Runs Nuth and Kaab Alignment routine on aligned DEM and the provided reference DEM
            using the demcoreg library.
        5. Extracts orthomosaic using the cameras aligned using the Nuth and Kaab routine and the DEM
            output by that routine.

    After each step, updated camera positions are saved and camera position changes are
    plotted with CE90 and LE90 scores.

    Using the Pipeline class involves 2 steps - instantiation and a call to the run method.
    For example:
        ```
        my_pipeline = Pipeline(
            input_images_path,
            reference_dem,
            image_matching_accuracy,
            densecloud_quality,
            output_DEM_resolution,
            project_name,
            output_path,
            input_images_metadata_file,
        )
        updated_camera_positions_file = my_pipeline.run()
        # or
        updated_camera_positions_file = my_pipeline.run_multi()
        # or
        updated_camera_positions_file = my_pipeline.run_multi(4)
        ```
    The `run` method returns a path to a CSV file containing the most-updated camera positions
    (post bundle adjustment, point cloud alignment, and Nuth and Kaab alignment).
    """

    #TODO: make iterations a class member (self.iterations) and increment the member so the pipeline
    #   class keeps track of where you are.
    # Make functions to get output paths of generated camera metadata files, and only access the 
    #   class members within those functions (ie get_aligned_bundle_adjusted_metadata_path(), which
    #   would generate the proper file path based on self.iterations and other paths)
    def __init__(
        self,
        input_images_path,
        reference_dem,
        image_matching_accuracy,
        densecloud_quality,
        output_DEM_resolution,
        project_name,
        output_path,
        input_images_metadata_file,
        camera_models_path=None,
        license_path="uw_agisoft.lic",
        verbose=True,
        rotation_enabled=True,
    ):
        """Initialize pipeline with parameters.

        Args:
            input_images_path (str): Path to directory containing input images referenced in input_images_metadata_file.
            reference_dem (str): Path to reference DEM file. Should be buffer the geographic extent of the aerial images.
            image_matching_accuracy (int): Metashape parameter. 1-4 from highest to lowest quality.
            densecloud_quality (int): Metashape parameter. 1-4 from highest to lowest quality.
            output_DEM_resolution (float): Output resolution of generated DEMs.
            project_name (str): Name for Metashape project file.
            output_path (str): Output path for all of the outputs generated by the pipeline.
            input_images_metadata_file (str): Path to file containing list of preprocessed aerial image file names and the metadata necessary for Metashape.
            camera_models_path (str): Path to directory containing camera models. Allows you to use pre-calibrated cameras generating point clouds from selected cameras/images.
            license_path (str, optional): [description]. Path to Agisoft license. Defaults to "uw_agisoft.lic".
            verbose (bool, optional): [description]. More logging. Defaults to True.
        """
        self.input_images_path = input_images_path
        self.reference_dem = reference_dem
        self.image_matching_accuracy = image_matching_accuracy
        self.densecloud_quality = densecloud_quality
        self.output_DEM_resolution = output_DEM_resolution
        self.project_name = project_name
        self.output_path = output_path
        self.input_images_metadata_file = input_images_metadata_file
        self.license_path = license_path
        self.verbose = verbose
        self.rotation_enabled = rotation_enabled
        self.camera_models_path = camera_models_path

        self.original_output_path = self.output_path

        # Assign paths for files that we will create
        #   These class members get updated when the output path is updated, which happens when running multiple iterations
        self.bundle_adjusted_metadata_file = os.path.join(
            output_path, "metaflow_bundle_adj_metadata.csv"
        )
        self.bundle_adjusted_unaligned_metadata_file = os.path.join(
            output_path, "metaflow_bundle_adj_unaligned_metadata.csv"
        )
        self.aligned_bundle_adjusted_metadata_file = os.path.join(
            output_path, "aligned_bundle_adj_metadata.csv"
        )
        self.nuthed_aligned_bundle_adjusted_metadata_file = os.path.join(
            output_path, "nuth_aligned_bundle_adj_metadata.csv"
        )
        self.clipped_reference_dem_file = os.path.join(
            output_path, "reference_dem_clipped.tif"
        )


    def run_multi(self, iterations=2, export_orthomosaic=True):
        """Run n pipeline iterations for further alignment/refinement.
        The final output camera locations of one pipeline iteration are fed in as the original camera positions
        for the subsequent pipeline run. During the first iteration, the Metashape rotation_enabled parameter is
        True and for subsequent iterations is false.
        Has the side effect of modifying multiple class fields by calling
            self._set_input_images_metadata_file and self._update_output_paths

        Args:
            iterations (int, optional): Number of times to run the pipeline. Defaults to 3.
        """
        rotation_enabled = self.rotation_enabled
        for i in range(0, iterations):
            self._update_output_paths(
                os.path.join(self.original_output_path, str(i) + "/")
            )  # need this '/' due to internal part of HSFM not using os.path.join
            updated_cameras = self.run(rotation_enabled, export_orthomosaic=export_orthomosaic)
            self._set_input_images_metadata_file(updated_cameras)
            rotation_enabled = False
        return updated_cameras

    def _update_output_paths(self, new_output_path):
        """
        Has the side effect of modifying:
            self.output_path
            self.bundle_adjusted_metadata_file
            self.bundle_adjusted_unaligned_metadata_file
            self.aligned_bundle_adjusted_metadata_file
            self.nuthed_aligned_bundle_adjusted_metadata_file
        """
        # TODO this is really ugly and contradicts the creation of these variables above...maybe multi_run should be a separate class...
        self.output_path = new_output_path
        self.bundle_adjusted_metadata_file = os.path.join(
            self.output_path, "metaflow_bundle_adj_metadata.csv"
        )
        self.bundle_adjusted_unaligned_metadata_file = os.path.join(
            self.output_path, "metaflow_bundle_adj_unaligned_metadata.csv"
        )
        self.aligned_bundle_adjusted_metadata_file = os.path.join(
            self.output_path, "aligned_bundle_adj_metadata.csv"
        )
        self.nuthed_aligned_bundle_adjusted_metadata_file = os.path.join(
            self.output_path, "nuth_aligned_bundle_adj_metadata.csv"
        )

    def _set_input_images_metadata_file(self, updated_cameras):
        """
        Has the side effect of modifying self.input_images_metadata_file.
        """
        self.input_images_metadata_file = updated_cameras

    def run(self, rotation_enabled=True, export_orthomosaic=True):
        """Run all steps in the pipeline.
        1. Generates a dense point cloud using Metashape's SfM algorithm.
        2. Aligns the point cloud to a reference DEM using an internally defined NASA ASP pc_align routine.
        3. Align the point cloud using the Nuth and Kaab Algorithm.
        Args:
            rotation_enabled (bool, optional): Metashape parameter.. Defaults to True.

        Returns:
            (str, str): (
                Path to CSV file containing the most updated/aligned camera positions after all pipeline steps.,
                Dataframe containing info for all cameras that could not be aligned
            )
        """
        metashape_is_activated = self._is_metashape_activated()
        if metashape_is_activated:
            print(
                f"Running pipeline with {len(pd.read_csv(self.input_images_metadata_file))} input images."
            )

            # 1. Structure from Motion
            project_file, point_cloud_file = self._run_metashape(rotation_enabled)
            if export_orthomosaic:
                _ = self._extract_orthomosaic()
            dem = self._extract_dem(point_cloud_file)
            unaligned_cameras_df = self._update_camera_data(project_file)
            _ = self._compare_camera_positions(
                self.input_images_metadata_file,
                self.bundle_adjusted_metadata_file,
                "Initial vs Bundle Adjusted",
                "initial_vs_bundle_adj_offsets.png",
            )

            # 2. Point Cloud Alignment
            aligned_dem_file, transform = self._pc_align_routine(dem)
            df = self._apply_transform_and_update_camera_data(transform)
            _ = self._compare_camera_positions(
                self.bundle_adjusted_metadata_file,
                self.aligned_bundle_adjusted_metadata_file,
                "Bundle Adjusted vs Bundle Adjusted and Aligned",
                "bundle_adj__vs_bundle_adj_and_aligned_offsets.png",
            )

            # 3. DEM Coregistration Alignment
            dem_difference_file, nuth_aligned_dem_file = self._nuth_kaab_align_routine(aligned_dem_file)
            _ = self._apply_nuth_transform_and_update_camera_data(df)
            _ = self._compare_camera_positions(
                self.aligned_bundle_adjusted_metadata_file,
                self.nuthed_aligned_bundle_adjusted_metadata_file,
                "Bundle Adjusted + Aligned vs Bundle Adjusted + Aligned + Nuth-Aligned",
                "bundle_adj_and_aligned_vs_bundle_adj_and_aligned_and_nuthed_offsets.png",
            )
            _ = self._compare_camera_positions(
                self.input_images_metadata_file,
                self.nuthed_aligned_bundle_adjusted_metadata_file,
                "Original vs Bundle Adjusted + Aligned + Nuth-Aligned",
                "og_vs_final_offsets.png",
            )
            if export_orthomosaic:
                _ = self._export_aligned_orthomosaic(nuth_aligned_dem_file, project_file)
            
            return self.nuthed_aligned_bundle_adjusted_metadata_file, unaligned_cameras_df
        else:
            print("Exiting...Metashape is not activated.")
            exit

    def _is_metashape_activated(self):
        print("Checking Metashape authentication...")
        # ToDo I don't like that the authentication method called below creates a symlink...can we avoid that or clean it up later?
        import Metashape

        hsfm.metashape.authentication(self.license_path)
        print(Metashape.app.activated)
        return Metashape.app.activated

    def _run_metashape(self, rotation_enabled):
        """Makes sure yaw, pitch, and roll columns are set to 0 for the camera metadata."""
        self._reset_yaw_pitch_roll(self.input_images_metadata_file)
        print(
            f"Running Metashape Camera Bundle Adjustment and Point Cloud Creation with camera metadata file {self.input_images_metadata_file}..."
        )
        project_file, point_cloud_file = hsfm.metashape.images2las(
            self.project_name,
            self.input_images_path,
            self.input_images_metadata_file,
            self.output_path,
            image_matching_accuracy=self.image_matching_accuracy,
            densecloud_quality=self.densecloud_quality,
            rotation_enabled=rotation_enabled,
            camera_model_xml_files_path=self.camera_models_path
        )
        return project_file, point_cloud_file

    def _reset_yaw_pitch_roll(self, camera_metadata_file_path):
        df = pd.read_csv(camera_metadata_file_path)
        df["yaw"] = df["pitch"] = df["roll"] = 0
        df.to_csv(camera_metadata_file_path, index=False)

    def _extract_orthomosaic(self, split_in_blocks=False):
        print("Extracting Orthomosaic...")
        hsfm.metashape.images2ortho(
            self.project_name,
            self.output_path,
            build_dem=True,
            split_in_blocks=split_in_blocks,
            iteration=0,
        )

    def _extract_dem(self, point_cloud_file):
        print("Extracting DEM...")
        epsg_code = "EPSG:" + hsfm.geospatial.get_epsg_code(self.reference_dem)
        dem = hsfm.asp.point2dem(
            point_cloud_file,
            "--nodata-value",
            "-9999",
            "--tr",
            str(self.output_DEM_resolution),
            #  '--threads', '10',
            "--t_srs",
            epsg_code,
            verbose=self.verbose,
        )
        return dem

    def _update_camera_data(self, project_file):
        print("Updating and extracting bundle-adjusted camera metadata...")
        # ToDo: DO NOT JUST DROP THESE UNALIGNED CAMERAS!!! Try processing them again...how to do this?
        ba_cameras_df, unaligned_cameras_df = hsfm.metashape.update_ba_camera_metadata(
            metashape_project_file=project_file,
            metashape_metadata_csv=self.input_images_metadata_file,
        )
        ba_cameras_df.to_csv(self.bundle_adjusted_metadata_file, index=False)
        unaligned_cameras_df.to_csv(self.bundle_adjusted_unaligned_metadata_file, index=False)
        return unaligned_cameras_df

    def _compare_camera_positions(
        self, metadata_file_1, metadata_file_2, title, plot_file_name
    ):
        print("Comparing and plotting camera position changes...")
        x_offset, y_offset, z_offset = hsfm.core.compute_point_offsets(
            metadata_file_1, metadata_file_2
        )
        ba_CE90, ba_LE90 = (
            hsfm.geospatial.CE90(x_offset, y_offset),
            hsfm.geospatial.LE90(z_offset),
        )
        hsfm.plot.plot_offsets(
            ba_LE90,
            ba_CE90,
            x_offset,
            y_offset,
            z_offset,
            title=title,
            plot_file_name=os.path.join(self.output_path, plot_file_name),
        )

    def _pc_align_routine(self, dem):
        print("Running Point Cloud Alignment Routine...")
        #clip reference DEM if its completely surrounds the new DEM - otherwise leave it alone.
        reference_dem_bounds = rix.open_rasterio(self.reference_dem).rio.bounds()
        new_dem_bounds = rix.open_rasterio(dem).rio.bounds()
        ref_box = box(*reference_dem_bounds)
        src_box = box(*new_dem_bounds)
        if ref_box.contains(src_box):
            clipped_reference_dem_file = hsfm.utils.clip_reference_dem(
                dem,
                self.reference_dem,
                output_file_name=self.clipped_reference_dem_file,
                verbose=self.verbose
            )
            aligned_dem_file, transform = hsfm.asp.pc_align_p2p_sp2p(
                dem, clipped_reference_dem_file, self.output_path, verbose=self.verbose
            )
        else:
            aligned_dem_file, transform = hsfm.asp.pc_align_p2p_sp2p(
                dem, self.reference_dem, self.output_path, verbose=self.verbose
            )
        return aligned_dem_file, transform

    def _apply_transform_and_update_camera_data(self, transform):
        print("Applying PC alignment transform to bundle-adjusted camera positions...")
        hsfm.core.metadata_transform(
            self.bundle_adjusted_metadata_file,
            transform,
            output_file_name=self.aligned_bundle_adjusted_metadata_file,
        )
        df = pd.read_csv(self.aligned_bundle_adjusted_metadata_file)
        df.to_csv(self.aligned_bundle_adjusted_metadata_file, index=False)
        return df

    #ToDo this using/not using clipped reference dem logic is repeated with the pc_align step above
    # ...amend that somehow
    def _nuth_kaab_align_routine(self, aligned_dem_file):
        print("Running Nuth and Kaab Alignment Routine...")
        reference_dem_bounds = rix.open_rasterio(self.reference_dem).rio.bounds()
        new_dem_bounds = rix.open_rasterio(aligned_dem_file).rio.bounds()
        ref_box = box(*reference_dem_bounds)
        src_box = box(*new_dem_bounds)
        if ref_box.contains(src_box):
            return hsfm.utils.dem_align_custom(
                self.clipped_reference_dem_file,
                aligned_dem_file,
                self.output_path,
                verbose=self.verbose,
            )
        else:
            return hsfm.utils.dem_align_custom(
                self.reference_dem,
                aligned_dem_file,
                self.output_path,
                verbose=self.verbose,
            )

    def _apply_nuth_transform_and_update_camera_data(self, df):
        print(
            "Applying transform from Nuth and Kaab to aligned and bundle adjusted camera positions..."
        )

        path_to_nuth_output = os.path.join(self.output_path, "pc_align", "spoint2point_bareground-trans_source-DEM_dem_align")
        transformed_metadata_csv_output_path = self.nuthed_aligned_bundle_adjusted_metadata_file

        hsfm.utils.apply_nuth_transform_to_camera_metadata(
            df,
            path_to_nuth_output,

        )

    def _export_aligned_orthomosaic(self, dem, project_file):
        orthomosaic_file = os.path.join(self.output_path, 'orthomosaic_final.tif')
        print(f'Generating nuth-aligned orthomosaic to path {orthomosaic_file} using dem at path {dem}')
        hsfm.metashape.export_updated_orthomosaic(
            project_file,
            self.nuthed_aligned_bundle_adjusted_metadata_file,
            dem,
            orthomosaic_file
        )


########################################################################################
########################################################################################
#
# App code
# Run like this
#
#   nohup python hsfm/pipeline/pipeline.py \
#       --reference-dem            /data2/elilouis/hsfm-geomorph/data/reference_dem_highres/rainier_lidar_dsm-adj.tif \
#       --input-images-path        /data2/elilouis/rainier_carbon_timesift/preprocessed_images \
#       --project-name             test \
#       --output-path                   /data2/elilouis/rainier_carbon_timesift/rainier_carbon_post_timesift_hsfm/73_0_0_test/ \
#       --input-images-metadata-file    /data2/elilouis/rainier_carbon_timesift/rainier_carbon_post_timesift_hsfm/73_0_0_test/metashape_metadata.csv \
#       --densecloud-quality            4 \
#       --image-matching-accuracy       4 \
#       --output-resolution 2 \
#       --license-path uw_agisoft.lic \
#       --iterations 3 \
#       --rotation-enabled false &
#
########################################################################################
########################################################################################
def parse_args():
    parser = argparse.ArgumentParser("Run the HSFM Pipeline on a batch of images.")
    parser.add_argument(
        "-r", "--reference-dem", help="Path to reference DEM file.", required=True
    )
    parser.add_argument(
        "-m",
        "--input-images-path",
        help="Path to directory containing preprocessed input images listed in the input images metadata file.",
        required=True,
    )
    parser.add_argument(
        "-p", "--project-name", help="Name for Metashape project files.", required=True
    )
    parser.add_argument(
        "-o",
        "--output-path",
        help="Path to directory where pipeline output will be stored.",
        required=True,
    )
    parser.add_argument(
        "-f",
        "--input-images-metadata-file",
        help="Path to csv file containing appropriate Metashape metadata with files names.",
        required=True,
    )
    parser.add_argument(
        "-q",
        "--densecloud-quality",
        help="Densecloud quality parameter for Metashape. Values include 1 - 4, from highest to lowest quality.",
        required=True,
        type=int,
    )
    parser.add_argument(
        "-a",
        "--image-matching-accuracy",
        help="Image matching accuracy parameter for Metashape. Values include 1 - 4, from highest to lowest quality.",
        required=True,
        type=int,
    )
    parser.add_argument(
        "-t",
        "--output-resolution",
        help="Output DEM target resolution",
        required=True,
        type=float,
    )
    parser.add_argument(
        "-l", "--license-path", help="Path to Agisoft license file", required=False
    )
    parser.add_argument(
        "-i",
        "--iterations",
        help="Iterations of the pipeline to run.",
        default=3,
        type=int,
    )
    parser.add_argument(
        "-rot",
        "--rotation-enabled",
        help="Enable Metashape rotation. When running run(), rotation is enabled. When running run_multi(), rotation is enabled for only the first iteration.",
        default=True,
        type=bool,
    )
    return parser.parse_args()


def main():
    print("Parsing arguments...")
    args = parse_args()
    print(f"Arguments: \n\t {args}")
    pipeline = Pipeline(
        args.input_images_path,
        args.reference_dem,
        args.image_matching_accuracy,
        args.densecloud_quality,
        args.output_resolution,
        args.project_name,
        args.output_path,
        args.input_images_metadata_file,
        license_path=args.license_path,
        rotation_enabled=args.rotation_enabled,
    )
    final_camera_metadata = pipeline.run_multi(args.iterations)
    print(f"Final updated camera metadata at path {final_camera_metadata}")


if __name__ == "__main__":
    main()
