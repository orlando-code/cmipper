# file handling
from pathlib import Path
import requests
import xarray as xa

# download
from concurrent.futures import ThreadPoolExecutor
import subprocess
from cdo import Cdo

# custom
import config


def construct_cmip_command(
    variable: str,
    source_id: str = "EC-Earth3P-HR",
    member_id: str = "r1i1p2f1",
    lats: list[float, float] = [-40, 0],
    lons: list[float, float] = [130, 170],
    levs: list[int, int] = [0, 20],
    script_fp: str = "cmipper/download_cmip6_data_parallel.py",
):
    arguments = [
        "--source_id",
        source_id,
        "--member_id",
        member_id,
        "--variable_id",
        variable,
    ]

    # Define the list arguments with their corresponding values
    list_arguments = [
        ("--lats", lats),
        ("--lons", lons),
        ("--levs", levs),
    ]
    list_str = [
        item
        for sublist in [
            [flag, str(val)] for flag, vals in list_arguments for val in vals
        ]
        for item in sublist
    ]

    arguments += list_str
    return ["/Users/rt582/miniforge3/envs/cmipper/bin/python", script_fp] + arguments


def construct_cmip_commands(
    variables,
    source_id: str = "EC-Earth3P-HR",
    member_id: str = "r1i1p2f1",
    lats: list[float, float] = [-40, 0],
    lons: list[float, float] = [130, 170],
    levs: list[int, int] = [0, 20],
    logging_dir: str = "/Users/rt582/Library/CloudStorage/OneDrive-UniversityofCambridge/cambridge/phd/cmipper/logs",
) -> (list, list):
    cmip_commands = []
    output_log_paths = []

    for variable in variables:
        # if not, run necessary downloading
        cmip_command = construct_cmip_command(
            variable, source_id, member_id, lats, lons, levs
        )
        cmip_commands.append(cmip_command)

        output_log_paths.append(
            Path(logging_dir) / f"{source_id}_{member_id}_{variable}.txt"
        )
    return cmip_commands, output_log_paths


def execute_subprocess_command(command, output_log_path):
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        print(f"{output_log_path}")
        with open(output_log_path, "w") as output_log_file:
            output_log_file.write(result.stdout.decode())
            output_log_file.write(result.stderr.decode())

        # with open(str(output_log_path), "w") as error_log_file:
        #     error_log_file.write(result.stderr.decode())

    except subprocess.CalledProcessError as e:
        print(f"Error{e}")
        # # Handle the exception if needed
        with open(output_log_path, "w") as error_log_file:
            error_log_file.write(f"Error: {e}")
            error_log_file.write(result.stderr.decode())


def run_commands_with_thread_pool(cmip_commands, output_log_paths, error_log_paths):
    with ThreadPoolExecutor(max_workers=len(cmip_commands)) as executor:
        # Submit each script command to the executor
        executor.map(execute_subprocess_command, cmip_commands, output_log_paths)


def ensure_cmip6_downloaded(
    variables: list[str],
    source_id: str = "EC-Earth3P-HR",
    member_id: str = "r1i1p2f1",
    lats: list[float, float] = [-40, 0],
    lons: list[float, float] = [130, 170],
    year_range_to_include: list[int, int] = [1950, 1960],
    levs: list[int, int] = [0, 20],
    logging_dir: str = "/Users/rt582/Library/CloudStorage/OneDrive-UniversityofCambridge/cambridge/phd/cmipper/logs",
):
    if not Path(config.cmip6_data_folder).exists():
        Path(config.cmip6_data_folder).mkdir(parents=True, exist_ok=True)

    potential_ds, potential_ds_fp = find_intersecting_cmip(
        variables, source_id, member_id, lats, lons, levs
    )
    if potential_ds is None:
        if not Path(logging_dir).exists():
            Path(logging_dir).mkdir(parents=True, exist_ok=True)

        print("Creating/downloading necessary file(s)...")
        # TODO: add in other sources/members

        cmip_commands, output_log_paths = construct_cmip_commands(
            variables, source_id, member_id, lats, lons, levs
        )
        run_commands_with_thread_pool(cmip_commands, output_log_paths, output_log_paths)
    else:
        print(
            f"CMIP6 file with necessary variables spanning latitudes {lats} and longitudes {lons} already exists at: \n{potential_ds_fp}"  # noqa
        )


def find_intersecting_cmip(
    variables: list[str],
    source_id: str = "EC-Earth3P-HR",
    member_id: str = "r1i1p2f1",
    lats: list[float, float] = [-40, 0],
    lons: list[float, float] = [130, 170],
    year_range_to_include: list[int, int] = [1950, 2014],
    levs: list[int, int] = [0, 20],
):

    # check whether intersecting cropped file already exists
    cmip6_dir_fp = Path(config.cmip6_data_folder) / source_id / member_id
    # TODO: include levs check
    correct_area_fps = list(
        find_files_for_area(cmip6_dir_fp.rglob("*.nc"), lat_range=lats, lon_range=lons),
    )
    # TODO: check that also spans full year range
    if len(correct_area_fps) > 0:
        # check that file includes all variables in variables list
        for fp in correct_area_fps:
            if all(variable in str(fp) for variable in variables):
                return (
                    process_xa_d(xa.open_dataset(fp)).sel(
                        latitude=slice(min(lats), max(lats)),
                        longitude=slice(min(lons), max(lons)),
                    ),
                    fp,
                )
    return None, None


def find_files_for_area(filepaths, lat_range, lon_range):
    result = []

    for filepath in filepaths:
        fp_lats, fp_lons = extract_lat_lon_ranges_from_fp(filepath)

        if (
            max(lat_range) <= max(fp_lats)
            and min(lat_range) >= min(fp_lats)
            and max(lon_range) <= max(fp_lons)
            and min(lon_range) >= min(fp_lons)
        ):
            result.append(filepath)

    return result


def process_xa_d(
    xa_d: xa.Dataset | xa.DataArray,
    rename_lat_lon_grids: bool = False,
    rename_mapping: dict = {
        "lat": "latitude",
        "lon": "longitude",
        "y": "latitude",
        "x": "longitude",
        "i": "longitude",
        "j": "latitude",
        "lev": "depth",
    },
    squeeze_coords: str | list[str] = None,
    # chunk_dict: dict = {"latitude": 100, "longitude": 100, "time": 100},
    crs: str = "EPSG:4326",
):
    """
    Process the input xarray Dataset or DataArray by standardizing coordinate names, squeezing dimensions,
    chunking along specified dimensions, and sorting coordinates.

    Parameters
    ----------
        xa_d (xa.Dataset or xa.DataArray): The xarray Dataset or DataArray to be processed.
        rename_mapping (dict, optional): A dictionary specifying the mapping for coordinate renaming.
            The keys are the existing coordinate names, and the values are the desired names.
            Defaults to a mapping that standardizes common coordinate names.
        squeeze_coords (str or list of str, optional): The coordinates to squeeze by removing size-1 dimensions.
                                                      Defaults to ['band'].
        chunk_dict (dict, optional): A dictionary specifying the chunk size for each dimension.
                                     The keys are the dimension names, and the values are the desired chunk sizes.
                                     Defaults to {'latitude': 100, 'longitude': 100, 'time': 100}.

    Returns
    -------
        xa.Dataset or xa.DataArray: The processed xarray Dataset or DataArray.

    """
    temp_xa_d = xa_d.copy()

    if rename_lat_lon_grids:
        temp_xa_d = temp_xa_d.rename(
            {"latitude": "latitude_grid", "longitude": "longitude_grid"}
        )

    for coord, new_coord in rename_mapping.items():
        if new_coord not in temp_xa_d.coords and coord in temp_xa_d.coords:
            temp_xa_d = temp_xa_d.rename({coord: new_coord})
    # temp_xa_d = xa_d.rename(
    #     {coord: rename_mapping.get(coord, coord) for coord in xa_d.coords}
    # )
    if "band" in temp_xa_d.dims:
        temp_xa_d = temp_xa_d.squeeze("band")
    if squeeze_coords:
        temp_xa_d = temp_xa_d.squeeze(squeeze_coords)

    if "time" in temp_xa_d.dims:
        temp_xa_d = temp_xa_d.transpose("time", "latitude", "longitude", ...)
    else:
        temp_xa_d = temp_xa_d.transpose("latitude", "longitude")

    if "grid_mapping" in temp_xa_d.attrs:
        del temp_xa_d.attrs["grid_mapping"]
    # add crs
    #     temp_xa_d.rio.write_crs(crs, inplace=True)
    # if chunk_dict is not None:
    #     temp_xa_d = chunk_as_necessary(temp_xa_d, chunk_dict)
    # sort coords by ascending values
    return temp_xa_d.sortby(list(temp_xa_d.dims))
