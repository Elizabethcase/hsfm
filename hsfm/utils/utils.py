import hvplot
import hvplot.xarray
import hvplot.pandas
import rasterio
import xarray as xr
import cartopy.crs as ccrs
import geoviews as gv
from geoviews import opts
import glob
import holoviews as hv
from holoviews.streams import PointDraw
from osgeo import gdal
import os
import pandas as pd
import panel as pn
import numpy as np
import PIL
import shutil
import subprocess
from subprocess import Popen, PIPE, STDOUT
import time
import utm

hv.extension('bokeh')

import hsfm.io
import hsfm.geospatial


def run_command(command, verbose=False, log_directory=None, shell=False):
    
    p = Popen(command,
              stdout=PIPE,
              stderr=STDOUT,
              shell=shell)
    
    if log_directory != None:
        log_file_name = os.path.join(log_directory,command[0]+'_log.txt')
        hsfm.io.create_dir(log_directory)
    
        with open(log_file_name, "w") as log_file:
            
            while p.poll() is None:
                line = (p.stdout.readline()).decode('ASCII').rstrip('\n')
                if verbose == True:
                    print(line)
                log_file.write(line)
        return log_file_name
    
    else:
        while p.poll() is None:
            line = (p.stdout.readline()).decode('ASCII').rstrip('\n')
            if verbose == True:
                print(line)
        
        


def download_srtm(LLLON,LLLAT,URLON,URLAT,
                  output_directory='./data/reference_dem/',
                  verbose=True,
                  cleanup=False):
    # TODO
    # - Add function to determine extent automatically from input cameras
    # - Make geoid adjustment and converstion to UTM optional
    # - Preserve wgs84 dem
    import elevation
    
    run_command(['eio', 'selfcheck'], verbose=verbose)
    print('Downloading SRTM DEM data...')

    hsfm.io.create_dir(output_directory)

    cache_dir=output_directory
    product='SRTM3'
    dem_bounds = (LLLON, LLLAT, URLON, URLAT)

    elevation.seed(bounds=dem_bounds,
                   cache_dir=cache_dir,
                   product=product,
                   max_download_tiles=999)

    tifs = glob.glob(os.path.join(output_directory,'SRTM3/cache/','*tif'))
    
    vrt_file_name = os.path.join(output_directory,'SRTM3/cache/srtm.vrt')
    
    call = ['gdalbuildvrt', vrt_file_name]
    call.extend(tifs)
    run_command(call, verbose=verbose)

    
    ds = gdal.Open(vrt_file_name)
    vrt_subset_file_name = os.path.join(output_directory,'SRTM3/cache/srtm_subset.vrt')
    ds = gdal.Translate(vrt_subset_file_name,
                        ds, 
                        projWin = [LLLON, URLAT, URLON, LLLAT])
                        
    
    # Adjust from EGM96 geoid to WGS84 ellipsoid
    adjusted_vrt_subset_file_name_prefix = os.path.join(output_directory,'SRTM3/cache/srtm_subset')
    call = ['dem_geoid',
            '--reverse-adjustment',
            vrt_subset_file_name, 
            '-o', 
            adjusted_vrt_subset_file_name_prefix]
    run_command(call, verbose=verbose)
    
    adjusted_vrt_subset_file_name = adjusted_vrt_subset_file_name_prefix+'-adj.tif'

    # Get UTM EPSG code
    epsg_code = hsfm.geospatial.wgs_lon_lat_to_epsg_code(LLLON, LLLAT)
    
    # Convert to UTM
    utm_vrt_subset_file_name = os.path.join(output_directory,'SRTM3/cache/srtm_subset_utm_geoid_adj.tif')
    call = 'gdalwarp -co COMPRESS=LZW -co TILED=YES -co BIGTIFF=IF_SAFER -dstnodata -9999 -r cubic -t_srs EPSG:' + epsg_code
    call = call.split()
    call.extend([adjusted_vrt_subset_file_name,utm_vrt_subset_file_name])
    run_command(call, verbose=verbose)
    
    # Cleanup
    if cleanup == True:
        print('Cleaning up...','Reference DEM available at', out)
        out = os.path.join(output_directory,os.path.split(utm_vrt_subset_file_name)[-1])
        os.rename(utm_vrt_subset_file_name, out)
        shutil.rmtree(os.path.join(output_directory,'SRTM3/'))
    
        return out
        
    else:
        return utm_vrt_subset_file_name
        
def pick_headings(image_directory, camera_positions_file_name, subset,delta=0.015):
    df = hsfm.core.select_images_for_download(camera_positions_file_name, subset)
    
    image_file_paths = sorted(glob.glob(os.path.join(image_directory, '*.tif')))
    lons = df['Longitude'].values
    lats = df['Latitude'].values

    headings = []
    for i, v in enumerate(lats):
        image_file_name = image_file_paths[i]
        camera_center_lon = lons[i]
        camera_center_lat = lats[i]

        heading = pick_heading_from_map(image_file_name,
                                        camera_center_lon,
                                        camera_center_lat,
                                        dx= delta,
                                        dy= delta)
        headings.append(heading)

    df['heading'] = headings

    return df

def scale_down_number(number, threshold=1000):
    while number > threshold:
        number = number / 2
    number = int(number)
    return number
    
def pick_heading_from_map(image_file_name,
                          camera_center_lon,
                          camera_center_lat,
                          dx = 0.015,
                          dy = 0.015):
                          

    # Google Satellite tiled basemap imagery url
    url = 'https://mt1.google.com/vt/lyrs=s&x={X}&y={Y}&z={Z}'
    
    # TODO
    # # allow large images to be plotted or force resampling to thumbnail
    # # load the image with xarray and plot with hvplot to handle larger images
    src = rasterio.open(image_file_name)

    a = scale_down_number(src.shape[0])
    b = scale_down_number(src.shape[1])
    # a = 500
    # b = 500
    title = '''
    Select the approximate location of the green dot in the left image on the right map.
    to determine the heading aka flight direction of the aircraft.'''
    da = xr.open_rasterio(src)
    
    point_x = src.shape[0] / 2
    point_y = 100
    point_location = hv.Points([(point_x,point_y,
                                 'point_to_pick')], 
                                 vdims='location')
    image_point_stream = PointDraw(source=point_location)
    image = da.sel(band=1).hvplot.image(rasterize=True,
                                      width=b,
                                      height=a,
                                      flip_yaxis=True,
                                      colorbar=False,
                                      cmap='gray',
                                      title=title)
    img = (image*point_location).opts(opts.Points(width=a, 
                                                  height=b, 
                                                  size=10, 
                                                  color='green', 
                                                  tools=['hover']))
    
    # load the image with PIL
    # img = np.array(PIL.Image.open(image_file_name))
    # img = hv.Image(img)
    # img = hv.RGB(img).opts(width=500, height=500)

    # create the extent of the bounding box
    extents = (camera_center_lon-dx, 
               camera_center_lat-dy, 
               camera_center_lon+dx, 
               camera_center_lat+dy)


    # run the tile server
    tiles = gv.WMTS(url, extents=extents)

    location = gv.Points([(camera_center_lon,
                           camera_center_lat,
                           'camera_center')], 
                           vdims='location')

    point_stream = PointDraw(source=location)

    base_map = (tiles * location).opts(opts.Points(width=a, 
                                                   height=b, 
                                                   size=10, 
                                                   color='black', 
                                                   tools=["hover"]))

    row = pn.Row(img, base_map)

    server = row.show(threaded=True)

    condition = True
    while condition == True:
        try:
            if len(point_stream.data['x']) == 2:
                server.stop()
                condition = False
        except:
            pass

    projected = gv.operation.project_points(point_stream.element,
                                            projection=ccrs.PlateCarree())
    df = projected.dframe()
    df['location'] = ['camera_center', 'flight_direction']
    
    heading_lon = df.x[1]
    heading_lat = df.y[1]
    
    heading = hsfm.geospatial.calculate_heading(camera_center_lon,
                                                camera_center_lat,
                                                heading_lon,
                                                heading_lat)
    
    return heading
    
# def image_corner_coordinate_picker(image_file_name,
#                                    camera_center_lon,
#                                    camera_center_lat,
#                                    utm_zone,
#                                    dx = 1200,
#                                    dy = 1200):
#
#     # Google Satellite tiled basemap imagery url
#     url = 'https://mt1.google.com/vt/lyrs=s&x={X}&y={Y}&z={Z}'
#
#     # load the image
#     img = np.array(PIL.Image.open(image_file_name))
#     img = hv.Image(img)
#     img = hv.RGB(img).opts(width=500, height=500)
#
#     # create the extent of the bounding box
#     extents = (camera_center_lon-dx,
#                camera_center_lat-dy,
#                camera_center_lon+dx,
#                camera_center_lat+dy)
#
#
#     # run the tile server
#     tiles = gv.WMTS(url, extents=extents, crs=ccrs.UTM(utm_zone))
#
#     location = gv.Points([(camera_center_lon,
#                            camera_center_lat,
#                            'camera_center')], vdims="location", crs=ccrs.UTM(utm_zone))
#
#     point_stream = PointDraw(source=location)
#
#     base_map = (tiles * location).opts(opts.Points(width=500,
#                                                      height=500,
#                                                      size=12,
#                                                      color='black',
#                                                      tools=["hover"]))
#
#     row = pn.Row(img, base_map)
#
#     server = row.show(threaded=True)
#     condition = True
#     while condition == True:
#         try:
#             if len(point_stream.data['x']) == 2:
#                 server.stop()
#                 condition = False
#         except:
#             pass
#
#     projected = gv.operation.project_points(point_stream.element, projection=ccrs.UTM(utm_zone))
#     df = projected.dframe()
#     df['location'] = ['camera_center', 'UL', 'UR', 'LR', 'LL']
#     return df
    
# def geoviews_corner_coordinates_df_to_string(corner_coordinate_df):
#
#     lat_lon_string = []
#
#     for i in range(len(corner_coordinate_df)):
#         lat = corner_coordinate_df.lat[i]
#         lon = corner_coordinate_df.lon[i]
#         lat_lon_string.append(lat)
#         lat_lon_string.append(lon)
#
#     lat_lon_string = ','.join(map(str,lat_lon_string))
#
#     return lat_lon_string
    
# def iter_image_corner_coordinate_picker(camera_locations_csv,
#                                         image_directory,
#                                         camera_name_field='# label',
#                                         longtiude_field='lon',
#                                         latitude_field='lat',
#                                         extension='.tif'):
#     """
#     Function to pick corner coordinates for an unprojected image from a basemap.
#     """
#
#     # TODO
#     # - Simplify by using functions from hsfm.geospatial
#
#     image_files  = sorted(glob.glob(os.path.join(image_directory,'*'+ extension)))
#
#     df = pd.read_csv(camera_locations_csv)
#
#     list_of_corner_coordinates_strings = []
#
#     image_paths = []
#     for i in range(len(df)):
#         lon               = df[longtiude_field].iloc[i]
#         lat               = df[latitude_field].iloc[i]
#         u                 = utm.from_latlon(lat,lon)
#         camera_center_lon = u[0]
#         camera_center_lat = u[1]
#         utm_zone          = u[2]
#         utm_zone_code     = u[3]
#
#
#
#         # Select image file path corresponding to entry in dataframe.
#         # Won't break on subsampled files with new name.
#         # TODO
#         # - Write cleaner way to do this.
#         image_base_name = df[camera_name_field].iloc[i]
#         image_base_name = os.path.split(image_base_name)[-1].split('.')[0]
#         for image_file in image_files:
#             if image_base_name in image_file:
#                 image_file_name = image_file
#
#         # run the corner coordinate picker
#         corner_coordinate_df = image_corner_coordinate_picker(image_file_name,
#                                                               camera_center_lon,
#                                                               camera_center_lat,
#                                                               utm_zone)
#         # Drop the camera center from data from and reindex
#         # Data frame now only contains the UL, UR, LR, LL corner coordinatees,
#         # in that order.
#         corner_coordinate_df = corner_coordinate_df.drop(0)
#         corner_coordinate_df = corner_coordinate_df.reset_index(drop=True)
#
#         # convert utm back to lat lon
#         lon, lat = utm.to_latlon(corner_coordinate_df['x'],
#                                  corner_coordinate_df['y'],
#                                  utm_zone,
#                                  utm_zone_code)
#         corner_coordinate_df['lat'] = lat
#         corner_coordinate_df['lon'] = lon
#
#         # Create the string for ASP cam_gen and append to list
#         corner_coordinates_string = geoviews_corner_coordinates_df_to_string(corner_coordinate_df)
#         list_of_corner_coordinates_strings.append(corner_coordinates_string)
#         image_paths.append(image_file_name)
#
#     df['corner_coordinates_string'] = list_of_corner_coordinates_strings
#     df['image_file_paths']          = image_paths
#
#     return df
    
# def generate_cameras_from_picker_corner_coordinate_df(corner_coordinate_df,
#                                                       focal_length_mm,
#                                                       reference_dem,
#                                                       output_directory,
#                                                       scale = 1,
#                                                       verbose=True):
#     heading                           = None
#     camera_lat_lon_center_coordinates = None
#
#     for i in range(len(corner_coordinate_df)):
#         image_file_name                   = corner_coordinate_df.image_file_paths[i]
#         corner_coordinates_string         = corner_coordinate_df.corner_coordinates_string[i]
#
#         hsfm.asp.generate_camera(image_file_name,
#                                  camera_lat_lon_center_coordinates,
#                                  reference_dem,
#                                  focal_length_mm,
#                                  heading,
#                                  output_directory = output_directory,
#                                  scale = scale,
#                                  verbose = verbose,
#                                  corner_coordinates_string = corner_coordinates_string)
                                 
def difference_dems(dem_file_name_a,
                    dem_file_name_b,
                    verbose=False):
    
    file_path, file_name, file_extension = hsfm.io.split_file(dem_file_name_a)
    
    output_directory_and_prefix = os.path.join(file_path,file_name)
    
    call = ['geodiff',
            '--absolute',
            dem_file_name_a,
            dem_file_name_b,
            '-o', output_directory_and_prefix]
            
    run_command(call, verbose=verbose)
    
    output_file_name = output_directory_and_prefix+'-diff.tif'
    
    return output_file_name

def dem_align_custom(reference_dem,
                     dem_to_be_aligned,
                     mode='nuth',
                     max_offset = 1000,
                     verbose=False,
                     log_directory=None):
    
    call = ['dem_align.py',
            '-max_offset',str(max_offset),
            '-mode', mode,
            reference_dem,
            dem_to_be_aligned]
            
    log_file_name = run_command(call, verbose=verbose, log_directory=log_directory)

    with open(log_file_name, 'r') as file:
        output_plot_file_name = file.read().split()[-3]
    dem_difference_file_name = glob.glob(os.path.split(output_plot_file_name)[0]+'/*_align_diff.tif')[0]
    aligned_dem_file_name = glob.glob(os.path.split(output_plot_file_name)[0]+'/*align.tif')[0]
    
    return dem_difference_file_name , aligned_dem_file_name
    

def rescale_geotif(geotif_file_name,
                   output_file_name=None,
                   scale=1):
                   
    percent = str(100/scale) +'%'
    
    if output_file_name is None:
        file_path, file_name, file_extension = hsfm.io.split_file(geotif_file_name)
        output_file_name = os.path.join(file_path, 
                                        file_name+'rescaled_sub'+str(scale)+file_extension)
    
    call = ['gdal_translate',
            '-of','GTiff',
            '-co','TILED=YES',
            '-co','COMPRESS=LZW',
            '-co','BIGTIFF=IF_SAFER',
            '-outsize',percent,percent,
            geotif_file_name,
            output_file_name]
            
    run_command(call, verbose=False)
    
    return output_file_name
    
    