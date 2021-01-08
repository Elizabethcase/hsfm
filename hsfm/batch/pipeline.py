# TODO: Convert hsfm.batch.pipeline to this class
class Pipeline():
"""
Historical Structure from Motion pipeline. 
Generates a DEM for a given set of images, runs a series of alignment steps, and outputs
various quality control plots along the way. 

The pipeline completes the following steps in order:
    1. Crestes point cloud from images using Metashape
    2. Extracts DEM and orthomosaic from Metashape project
    3. Runs point cloud alignment routine on the extracted DEM and the provided reference 
        DEM using NASA ASP
    4. Runs Nuth and Kaab Alignment routine on aligned DEM and the provided reference DEM
        using the demcoreg library.

After each step, updated camera positions are saved and camera position changes are 
plotted with CE90 and LE90 scores.
"""

    def __init__(
        self,
        input_images_path,
        reference_dem,
        pixel_pitch,
        image_matching_accuracy,
        densecloud_quality,
        output_DEM_resolution,
        project_name,
        output_path,
        input_images_metadata_file,
        license_path = 'uw_agisoft.lic',
        verbose               = True,
        rotation_enabled      = True
    ):
        """Initialize Pipeline attributes."""
        self.input_images_path = input_images_path
        self.reference_dem = reference_dem
        self.pixel_pitch = pixel_pitch
        self.image_matching_accuracy = image_matching_accuracy
        self.densecloud_quality = densecloud_quality
        self.output_DEM_resolution = output_DEM_resolution
        self.project_name = project_name
        self.output_path = output_path
        self.input_images_metadata_file = input_images_metadata_file
        self.license_path = license_path
        self.verbose = verbose
        self.rotation_enabled = rotation_enabled

        # Assign paths for files that we will create
        self.bundle_adjusted_metadata_file                = os.path.join(output_path, 'metaflow_bundle_adj_metadata.csv')
        self.aligned_bundle_adjusted_metadata_file        = os.path.join(output_path, 'aligned_bundle_adj_metadata.csv')
        self.nuthed_aligned_bundle_adjusted_metadata_file = os.path.join(output_path, 'nuth_aligned_bundle_adj_metadata.csv')
        self.clipped_reference_dem_file = os.path.join(output_path,'reference_dem_clipped.tif')
        
        # Get some data that the pipeline needs
        self.focal_length = __get_focal_length_from_metadata_file(input_images_metadata_file)
        
    def run(self):
        metashape_is_activated = __is_metashape_activated()
        if metashape_is_activated:
            # 1. Structure from Motion
            project_file, point_cloud_file = __run_metashape()
            __extract_orthomosaic()
            dem = __extract_dem(point_cloud_file)
            __update_camera_data(project_file)
            __compare_camera_positions(
                self.input_images_metadata_file, 
                self.bundle_adjusted_metadata_file, 
                'Initial vs Bundle Adjusted', 
                'initial_vs_bundle_adj_offsets.png'
            )

            # 2. Point Cloud Alignment
            aligned_dem_file, transform = __pc_align_routine(dem)
            df = __apply_transform_and_update_camera_data(transform)
            __compare_camera_positions(
                self.bundle_adjusted_metadata_file, 
                self.aligned_bundle_adjusted_metadata_file,
                'Bundle Adjusted vs Bundle Adjusted and Aligned',
                'bundle_adj__vs_bundle_adj_and_aligned_offsets.png'
            )

            # 3. DEM Coregistration Alignment
            __nuth_kaab_align_routine(aligned_dem_file)
            __apply_nuth_transform_and_update_camera_data(df)
            __compare_camera_positions(
                self.aligned_bundle_adjusted_metadata_file, 
                self.nuthed_aligned_bundle_adjusted_metadata_file,
                'Bundle Adjusted + Aligned vs Bundle Adjusted + Aligned + Nuth-Aligned',
                'bundle_adj_and_aligned_vs_bundle_adj_and_aligned_and_nuthed_offsets.png'
            )
            __compare_camera_positions(
                self.input_images_metadata_file, 
                self.nuthed_aligned_bundle_adjusted_metadata_file,
                'Original vs Bundle Adjusted + Aligned + Nuth-Aligned',
                'og_vs_final_offsets.png'
            )
        else:
            print('Exiting...Metashape is not activated.')

    def __is_metashape_activated():
        print('Checking Metashape authentication...')
        #ToDo I don't like that the authentication method called below creates a symlink...can we avoid that or clean it up later?
        import Metashape
        hsfm.metashape.authentication(metashape_licence_file)
        print(Metashape.app.activated)
        return Metashape.app.activated

    def __get_focal_length_from_metadata_file(file):
        return pd.read_csv(file)['focal_length'][0]

    def __run_metashape():
        print('Running Metashape Camera Bundle Adjustment and Point Cloud Creation...')
        project_file, point_cloud_file = hsfm.metashape.images2las(
            self.project_name,
            self.input_images_path,
            self.input_images_metadata_file,
            self.output_path,
            focal_length            = self.focal_length,
            pixel_pitch             = self.pixel_pitch,
            image_matching_accuracy = self.image_matching_accuracy,
            densecloud_quality      = self.densecloud_quality,
            rotation_enabled        = self.rotation_enabled
        )
        return project_file, point_cloud_file
    
    def __extract_orthomosaic():
        print('Extracting Orthomosaic...')
        hsfm.metashape.images2ortho(
            self.project_name,
            self.output_path,
            build_dem       = True,
            split_in_blocks = False,
            iteration       = 0)
    
    def __extract_dem(point_cloud_file):
        print('Extracting DEM...')
        epsg_code = 'EPSG:'+ hsfm.geospatial.get_epsg_code(self.reference_dem)
        dem = hsfm.asp.point2dem(
            point_cloud_file, 
            '--nodata-value','-9999',
            '--tr',str(self.output_DEM_resolution),
            #  '--threads', '10',
            '--t_srs', epsg_code,
            verbose=self.verbose
        )
        return dem
    
    def __update_camera_data(project_file):
        print('Updating and extracting bundle-adjusted camera metadata...')
        ba_cameras_df, unaligned_cameras_df = hsfm.metashape.update_ba_camera_metadata(
            metashape_project_file = project_file, 
            metashape_metadata_csv = self.input_images_metadata_file
        )
        ba_cameras_df.to_csv(self.bundle_adjusted_metadata_file, index = False)
    
    def __compare_camera_positions(metadata_file_1, metadata_file_2, title, plot_file_name):
        print('Comparing and plotting camera position changes...')
        x_offset, y_offset, z_offset = hsfm.core.compute_point_offsets(
            metadata_file_1, 
            metadata_file_2
        )
        ba_CE90, ba_LE90 = hsfm.geospatial.CE90(x_offset,y_offset), hsfm.geospatial.LE90(z_offset)
        hsfm.plot.plot_offsets(
            ba_LE90,
            ba_CE90,
            x_offset, 
            y_offset, 
            z_offset,
            title = title,
            plot_file_name = os.path.join(self.output_path, plot_file_name)
        )
    
    def __pc_align_routine(dem):
        print('Running Point Cloud Alignment Routine...')
        clipped_reference_dem_file = hsfm.utils.clip_reference_dem(
            dem, 
            self.reference_dem,
            output_file_name = self.clipped_reference_dem_file,
            buff_size        = 2000,
            verbose = self.verbose
        )
        aligned_dem_file, transform =  hsfm.asp.pc_align_p2p_sp2p(
            dem,
            clipped_reference_dem_file,
            self.output_path,
            verbose = self.verbose
        )
        return aligned_dem_file, transform
    
    def __apply_transform_and_update_camera_data(transform):
        print('Applying PC alignment transform to bundle-adjusted camera positions...')
        hsfm.core.metadata_transform(
            self.bundle_adjusted_metadata_file,
            transform,
            output_file_name = self.aligned_bundle_adjusted_metadata_file
        )
        df = pd.read_csv(self.aligned_bundle_adjusted_metadata_file)
        df['focal_length'] = pd.read_csv(self.input_images_metadata_file)['focal_length']
        return df
    
    def __nuth_kaab_align_routine(aligned_dem_file):
        print('Running Nuth and Kaab Alignment Routine...')
        hsfm.utils.dem_align_custom(
            self.clipped_reference_dem_file,
            aligned_dem_file,
            self.output_path,
            verbose = self.verbose
        )
    
    def __apply_nuth_transform_and_update_camera_data(df):
        print('Applying transform from Nuth and Kaab to aligned and bundle adjusted camera positions...')

        path = __find_first_json_file_in_nested_directory(os.path.join(self.output_path, 'pc_align'))
        with open(os.path.join(self.output_path, 'pc_align', path)) as src:
            data = json.load(src)
        gdf = gpd.GeoDataFrame(
            df, geometry=gpd.points_from_xy(x=df.lon, y=df.lat)
        )
        # TODO: these should not be hardcoded....or at least the second should not be
        gdf.crs = 'EPSG:4326'
        gdf = gdf.to_crs('EPSG:32610')

        gdf['new_lat'] = gdf.geometry.y + data['shift']['dy']
        gdf['new_lon'] = gdf.geometry.x + data['shift']['dx']
        gdf = gpd.GeoDataFrame(
            df, geometry=gpd.points_from_xy(x=gdf.new_lon, y=gdf.new_lat)
        )
        gdf.crs = 'EPSG:32610'
        gdf = gdf.to_crs('EPSG:4326')

        df.lat = gdf.geometry.y
        df.lon = gdf.geometry.x
        df.alt = df.alt + data['shift']['dz']
        df = df.drop(['geometry'], axis=1)
        df.to_csv(self.nuthed_aligned_bundle_adjusted_metadata_file, index = False)

    # This is kind of hacky... but works to find the Nuth and Kaab algorithm's json file output...at least in my experience.
    def __find_first_json_file_in_nested_directory(directory):
        file_list = []
        dir_list = []
        for root, dirs, files in os.walk(directory):
            if len(dirs) > 0:
                dir_list.append(dirs[0])
            json_files = [file for file in files if 'json' in file]
            if len(json_files) > 0:
                file_list.append(json_files[0])
        if len(file_list) > 0:
            return os.path.join(dir_list[0],file_list[0])