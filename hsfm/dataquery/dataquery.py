import contextily as ctx
import fsspec
import geopandas as gpd
import os
import glob
import sys
import pathlib
import subprocess
from subprocess import Popen, PIPE, STDOUT
import pathlib
import json
from shapely.geometry import Polygon
import matplotlib.pyplot as plt
import psutil

import hsfm


##### 3DEP AWS lidar #####
# TODO 
# - make this a class

def process_3DEP_laz_to_DEM(
    bounds,
    aws_3DEP_directory=None,
    epsg_code=None,
    output_path="./",
    DEM_file_name="dem.tif",
    verbose=True,
    cleanup=False,
    cache_directory='cache',
):

    pathlib.Path(output_path).mkdir(parents=True, exist_ok=True)

    result_gdf, bounds_gdf = hsfm.dataquery.get_3DEP_lidar_data_dirs(bounds, cache_directory=cache_directory)

    if not epsg_code:
        epsg_code = hsfm.dataquery.get_UTM_EPSG_code_from_bounds(bounds)
    epsg_code = str(epsg_code)

    if aws_3DEP_directory:
        if aws_3DEP_directory in result_gdf["directory"].to_list():
            result_gdf = result_gdf.loc[result_gdf["directory"] == aws_3DEP_directory]
            result_gdf = result_gdf.reset_index(drop=True)
        else:
            message = " ".join(
                [
                    aws_3DEP_directory,
                    "not in",
                    " ".join(result_gdf["directory"].to_list()),
                ]
            )
            sys.exit(message)

    hsfm.dataquery.plot_3DEP_bounds(result_gdf, bounds_gdf, qc_plot_output_directory=output_path)
    
    if len(result_gdf.index) != 1:
        print(
            "Multiple directories with laz data found on AWS.",
            "Check bounds_qc_plot.png in",
            output_path,
            "directory. Rerun and specify a valid aws_3DEP_directory",
            "you would like to download data from. Options include",
            " ".join(result_gdf["directory"].to_list()),
        )

    else:
        aws_3DEP_directory = result_gdf["directory"].loc[0]

        pipeline_json_file, output_laz_file = hsfm.dataquery.create_3DEP_pipeline(
            bounds_gdf,
            aws_3DEP_directory,
            epsg_code,
            output_path=output_path,
        )

        hsfm.dataquery.run_3DEP_pdal_pipeline(pipeline_json_file, verbose=verbose)
        print(output_laz_file)

        output_dem_file = hsfm.dataquery.grid_3DEP_laz(output_laz_file, epsg_code, verbose=verbose)

        out = os.path.join(output_path, DEM_file_name)
        os.rename(output_dem_file, out)
        print(out)
        print('DONE')

        if cleanup == True:
            os.remove(output_laz_file)
            os.remove(pipeline_json_file)
            files = glob.glob(os.path.join(output_path, "*log*.txt"))
            for i in files:
                os.remove(i)


def grid_3DEP_laz(laz_file, epsg_code, target_resolution=1, verbose=False):
    out_srs = "EPSG:" + str(epsg_code)
    call = [
        "point2dem",
        "--nodata-value",
        "-9999",
        "--threads", str(psutil.cpu_count(logical=True)),
        "--t_srs",
        out_srs,
        "--tr",
        str(target_resolution),
        laz_file,
    ]
    hsfm.utils.run_command(call, verbose=verbose)

    file_path = str(pathlib.Path(laz_file).parent.resolve())
    file_name = str(pathlib.Path(laz_file).stem)
    output_dem_file = os.path.join(file_path, file_name + "-DEM.tif")
    return output_dem_file


def run_3DEP_pdal_pipeline(pipeline_json_file, verbose=True):

    call = ["pdal", "pipeline", pipeline_json_file]
    if verbose:
        call.extend(["--verbose", "7"])
    hsfm.utils.run_command(call, verbose=verbose)


def create_3DEP_pipeline(
    bounds_gdf,
    aws_3DEP_directory,
    epsg_code,
    output_path="./",
    pipeline_json_file="pipeline.json",
    output_laz_file="output.laz",
):
    pipeline_json_file = os.path.join(output_path, pipeline_json_file)
    output_laz_file = os.path.join(output_path, output_laz_file)

    base_url = "http://usgs-lidar-public.s3.amazonaws.com/"
    filename = os.path.join(base_url, aws_3DEP_directory, "ept.json")
    print('Downloading from',filename)

    lons, lats = bounds_gdf.to_crs("EPSG:3857").geometry.boundary.loc[0].xy
    lats = list(set(lats))
    lons = list(set(lons))
    bounds_str = "(" + str(lons) + "," + str(lats) + ")"

    out_srs = "EPSG:" + str(epsg_code)

    pipeline = {
        "pipeline": [
            {
                "type": "readers.ept",
                "filename": filename,
                "bounds": bounds_str,
                "threads": str(psutil.cpu_count(logical=True)),
            },
            {"type": "filters.returns", "groups": "first,only"},
            {"type": "filters.reprojection", "out_srs": out_srs},
            #             {
            #                 "type": "filters.splitter",
            #                 "length": "100",
            #             },
            output_laz_file,
        ]
    }

    with open(pipeline_json_file, "w") as f:
        json.dump(pipeline, f)

    return pipeline_json_file, output_laz_file


def get_3DEP_lidar_data_dirs(bounds, cache_directory="cache"):
    """
    bounds = [east, south, west, north]
    """
    fs = fsspec.filesystem("s3", anon=True)

    base_url = "s3://usgs-lidar-public/"
    aws_3DEP_directories = fs.ls(base_url)

    vertices = [
        (bounds[0], bounds[1]),
        (bounds[0], bounds[3]),
        (bounds[2], bounds[3]),
        (bounds[2], bounds[1]),
    ]

    bounds_polygon = Polygon(vertices)
    bounds_gdf = gpd.GeoDataFrame(
        gpd.GeoSeries(bounds_polygon), columns=["geometry"], crs="epsg:4326"
    )
    data_dirs_without_boundary_file = []

    pathlib.Path(cache_directory).mkdir(parents=True, exist_ok=True)
    out = os.path.join(cache_directory, "boundary.geojson")

    if os.path.isfile(out):
        df = gpd.read_file(out)
        result_gdf = gpd.overlay(df, bounds_gdf)

    else:
        df = gpd.GeoDataFrame(columns=["directory", "geometry"])
        for directory in aws_3DEP_directories:
            if os.path.isfile(out):
                gdf = gpd.read_file(out)
                gdf["directory"] = directory.split("/")[-1]
                df = df.append(gdf)
            else:
                try:
                    dir_url = "s3://" + directory
                    url = os.path.join(dir_url, "boundary.json")
                    gdf = gpd.read_file(fs.open(url, "rb"))
                    gdf["directory"] = directory.split("/")[-1]
                    df = df.append(gdf)
                except FileNotFoundError:
                    # not doing anything with this but could log
                    data_dirs_without_boundary_file.append(directory)
                    pass

        df.crs = bounds_gdf.crs
        df.to_file(out, driver="GeoJSON")
        result_gdf = gpd.overlay(df, bounds_gdf)

    return result_gdf, bounds_gdf


def get_UTM_EPSG_code_from_bounds(bounds):
    """
    bounds = [east, south, west, north]
    """
    east_south_epsg_code = hsfm.geospatial.lon_lat_to_utm_epsg_code(
        bounds[0], bounds[1]
    )
    west_north_epsg_code = hsfm.geospatial.lon_lat_to_utm_epsg_code(
        bounds[2], bounds[3]
    )

    if east_south_epsg_code == west_north_epsg_code:
        epsg_code = west_north_epsg_code
        return epsg_code
    else:
        print("Bounds span two UTM zones.")
        print(
            "EPSG:" + west_north_epsg_code,
            "and",
            "EPSG:" + east_south_epsg_code,
        )
        print("Using", "EPSG:" + west_north_epsg_code)
        epsg_code = west_north_epsg_code
        return epsg_code


def plot_3DEP_bounds(result_gdf, bounds_gdf, qc_plot_output_directory="./"):
    """
    takes outputs from tools.get_3DEP_lidar_data_dirs()

    results_gdf: geopandas.geodataframe.GeoDataFrame
    bounds_gdf: geopandas.geodataframe.GeoDataFrame

    """

    bounds_gdf["coords"] = bounds_gdf["geometry"].apply(
        lambda x: x.representative_point().coords[:]
    )
    result_gdf["coords"] = result_gdf["geometry"].apply(
        lambda x: x.representative_point().coords[:]
    )

    prop_cycle = plt.rcParams["axes.prop_cycle"]
    colors = prop_cycle.by_key()["color"]

    fig, ax = plt.subplots(figsize=(10, 10))

    for i, v in enumerate(result_gdf.index):
        result_gdf.loc[result_gdf.index == i].plot(
            ax=ax, edgecolor=colors[i], facecolor="none", linewidth=3
        )

    bounds_gdf.plot(ax=ax, edgecolor="black", facecolor="none", linewidth=1)

    try:
        ctx.add_basemap(
            ax,
            source="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
            crs=bounds_gdf.crs.to_string(),
            alpha=0.5,
        )
    except:
        # if fails the bounds are likely too small to pull a tile
        pass

    for idx, row in result_gdf.iterrows():
        plt.annotate(
            s=row["directory"], xy=row["coords"][0], horizontalalignment="center"
        )

    out = os.path.join(qc_plot_output_directory, "bounds_qc_plot.png")
    plt.tight_layout()
    plt.savefig(out, bbox_inches="tight", pad_inches=0.1)
