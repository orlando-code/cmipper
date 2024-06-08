from pathlib import Path
import re
import xarray as xa

from cmipper import utils, config

import sys
import yaml
import concurrent.futures


def find_files_for_time(filepaths, year_range):
    result = []
    for fp in filepaths:
        start_year = int(str(fp).split("_")[-1].split("-")[0][:4])
        end_year = (
            int(str(fp).split("_")[-1].split("-")[1][:4]) + 1
        )  # +1: XXXX12 = full XXXX year
        if (min(year_range) >= start_year) and (max(year_range)) <= end_year:
            result.append(fp)
    return result


def find_files_for_area(filepaths, lat_range, lon_range):
    result = []

    for filepath in filepaths:
        # uncropped refers to global coverage
        if "uncropped" in str(filepath):
            result.append(filepath)
            continue

        fp_lats, fp_lons = extract_lat_lon_ranges_from_fp(filepath)
        if (
            max(lat_range) <= max(fp_lats)
            and min(lat_range) >= min(fp_lats)
            and max(lon_range) <= max(fp_lons)
            and min(lon_range) >= min(fp_lons)
        ):
            result.append(filepath)

    return result


def get_min_max_coords_from_xa_d(xa_d: xa.Dataset | xa.DataArray, lat_coord_name: str = None, lon_coord_name: str = None):
    lat_coord_possibilities = ["lat", "latitude", "y"] if not lat_coord_name else [lat_coord_name]
    lon_coord_possibilities = ["lon", "longitude", "x"] if not lon_coord_name else [lon_coord_name]

    lat_coord = next((coord for coord in lat_coord_possibilities if coord in xa_d.coords), None)
    lon_coord = next((coord for coord in lon_coord_possibilities if coord in xa_d.coords), None)

    if not lat_coord:
        raise ValueError("Latitude coordinate not found in the dataset.")
    if not lon_coord:
        raise ValueError("Longitude coordinate not found in the dataset.")

    return xa_d[lat_coord].values.min(), xa_d[lat_coord].values.max(), xa_d[lon_coord].values.min(), xa_d[lon_coord].values.max()


def formatted_lat_lon_from_vals(min_lat, max_lat, min_lon, max_lon):
    lats_strs = [f"s{utils.replace_dot_with_dash(str(abs(round(lat, 1))))}" if lat < 0 else f"n{utils.replace_dot_with_dash(str(abs(round(lat, 1))))}" for lat in [min_lat, max_lat]]   # noqa
    lons_strs = [f"w{utils.replace_dot_with_dash(str(abs(round(lon, 1))))}" if lon < 0 else f"e{utils.replace_dot_with_dash(str(abs(round(lon, 1))))}" for lon in [min_lon, max_lon]]   # noqa

    return lats_strs, lons_strs

def rename_nc_with_coords(
    nc_fp: Path | str, lat_coord_name: str = None, lon_coord_name: str = None, delete_og: bool = True
) -> None:
    """
    Renames a NetCDF file with latitude and longitude coordinates.

    Args:
        nc_fp (Path | str): The file path of the NetCDF file to be renamed.
        lat_coord_name (str, optional): The name of the latitude coordinate variable. If not provided,
            common latitude coordinate names will be used.
        lon_coord_name (str, optional): The name of the longitude coordinate variable. If not provided,
            common longitude coordinate names will be used.
        delete_og (bool, optional): Whether to delete the original file after renaming. Defaults to False.

    Raises:
        ValueError: If the latitude or longitude coordinate is not found in the dataset.
        FileExistsError: If the new file path already exists.

    Returns:
        None
    """
    nc_fp = Path(nc_fp)
    nc_xa = xa.open_dataset(nc_fp)

    min_lat, max_lat, min_lon, max_lon = get_min_max_coords_from_xa_d(nc_xa, lat_coord_name, lon_coord_name)

    lats_strs, lons_strs = formatted_lat_lon_from_vals(min_lat, max_lat, min_lon, max_lon)

    new_fp = nc_fp.parent / f"{nc_fp.stem}_{lats_strs[1]}_{lats_strs[0]}_{lons_strs[0]}_{lons_strs[1]}.nc"

    if new_fp.exists():
        raise FileExistsError(f"File {new_fp} already exists.")

    print("Writing file...")
    nc_xa.to_netcdf(new_fp)
    print(f"Written {nc_fp} to {new_fp}")

    if delete_og:
        nc_fp.unlink()
        print(f"Deleted {nc_fp}")


def extract_lat_lon_ranges_from_fp(fp: Path | str):
    # Define the regular expression pattern
    coord_pattern = re.compile(
        # r".*_[ns](?P<north>-?\d+-?.?\d?)_[ns](?P<south>-?\d+-?.?\d?)_[we](?P<west>-?\d+-?.?\d?)_[we](?P<east>-?\d+-?.?\d?).*\.nc",    # og
        r".*_[ns](?P<north>-?\d+-?.?\d?)_[ns](?P<south>-?\d+-?.?\d?)_[we](?P<west>-?\d+-?.?\d?)_[we](?P<east>-?\d+-?\.?\d*).*.nc",

        re.IGNORECASE,
    )
    coord_match = coord_pattern.match(str(Path(fp).name))

    # Match the pattern in the filename
    if not coord_match:
        raise ValueError(f"Could not extract latitudes and longitudes from {fp}. Ensure the filename is formatted correctly.")

    # Extract cardinal directions and determine signs
    cardinal_directions = re.findall(r"([nsew])(?=-?\d+)", str(Path(fp).name), re.IGNORECASE)
    direction_signs = [1 if d.lower() in 'ne' else -1 for d in cardinal_directions]

    # Extract and process coordinates
    north = float(utils.dash_process_coordinate(coord_match.group("north")))
    south = float(utils.dash_process_coordinate(coord_match.group("south")))
    west = float(utils.dash_process_coordinate(coord_match.group("west")))
    east = float(utils.dash_process_coordinate(coord_match.group("east")))

    # Apply direction_signs
    north *= direction_signs[0]
    south *= direction_signs[1]
    west *= direction_signs[2]
    east *= direction_signs[3]

    # Create lists of latitudes and longitudes
    lats = [north, south]
    lons = [west, east]

    return lats, lons


class FileName:
    def __init__(
        self,
        variable_id: str | list,
        grid_type: str,
        fname_type: str,
        date_range: str = None,
        lats: list[float, float] = None,
        lons: list[float, float] = None,
        levs: list[int, int] = None,
        plevels: list[float, float] = None,
    ):
        """
        Args:
            source_id (str): name of climate model
            member_id (str): model run
            variable_id (str): variable name
            grid_type (str): type of grid (tripolar or latlon)
            fname_type (str): type of file (individual, time-concatted, var_concatted) TODO
            lats (list[float, float], optional): latitude range. Defaults to None.
            lons (list[float, float], optional): longitude range. Defaults to None.
            plevels (list[float, float], optional): pressure level range. Defaults to None.
            fname (str, optional): filename. Defaults to None to allow construction.
        """
        self.variable_id = variable_id
        self.grid_type = grid_type
        self.fname_type = fname_type
        self.date_range = date_range
        self.lats = lats
        self.lons = lons
        self.levs = levs
        self.plevels = plevels

    def get_spatial(self):
        if self.lats and self.lons:  # if spatial range specified (i.e. cropping)
            # cast self.lats and self.lons lists to integers. Replaced with clever sf rounding
            # lats = [int(lat) for lat in self.lats]
            # lons = [int(lon) for lon in self.lons]
            return utils.lat_lon_string_from_tuples(self.lats, self.lons).upper()
        else:
            # min_lat, max_lat, min_lon, max_lon = get_min_max_coords_from_xa_d
            return "uncropped"

    def get_plevels(self):
        if self.plevels == [-1] or self.plevels == -1:  # seafloor
            return f"sfl-{max(self.levs)}"
        elif not self.plevels:
            return "sfc"
            if self.plevels[0] is None:
                return "sfc"
        elif isinstance(self.plevels, float):  # specified pressure level
            return "{:.0f}".format(self.plevels / 100)
        elif isinstance(self.plevels, list):  # pressure level range
            if self.plevels[0] is None:  # if plevels is list of None, surface
                return "sfc"
            return f"levs_{min(self.plevels)}-{max(self.plevels)}"
        else:
            raise ValueError(
                f"plevel must be one of [-1, float, list]. Instead received '{self.plevels}'"
            )

    def get_var_str(self):
        if isinstance(self.variable_id, list):
            return "_".join(self.variable_id)
        else:
            return self.variable_id

    def get_grid_type(self):
        if self.grid_type == "tripolar":
            return "tp"
        elif self.grid_type == "latlon":
            return "ll"
        else:
            raise ValueError(
                f"grid_type must be 'tripolar' or 'latlon'. Instead received '{self.grid_type}'"
            )

    def get_date_range(self):
        if not self.date_range:
            return None
        if self.fname_type == "time_concatted" or self.fname_type == "var_concatted":
            # Can't figure out how it's being done currently
            return str("-".join((str(self.date_range[0]), str(self.date_range[1]))))
        else:
            return self.date_range

    def join_as_necessary(self):
        var_str = self.get_var_str()
        spatial = self.get_spatial()
        plevels = self.get_plevels()
        grid_type = self.get_grid_type()
        date_range = self.get_date_range()

        # join these variables separated by '_', so long as the variable is not None
        return "_".join(
            [i for i in [var_str, spatial, plevels, grid_type, date_range] if i]
        )

    def construct_fname(self):

        if self.fname_type == "var_concatted":
            if not isinstance(self.variable_id, list):
                raise TypeError(
                    f"Concatted variable requires multiple variable_ids. Instead received '{self.variable_id}'"
                )

        self.fname = self.join_as_necessary()

        return f"{self.fname}.nc"


def read_yaml(yaml_path: str | Path):
    with open(yaml_path, "r") as file:
        yaml_info = yaml.safe_load(file)
    return yaml_info


def redirect_stdout_stderr_to_file(filename):
    sys.stdout = open(filename, "w")
    sys.stderr = sys.stdout


def reset_stdout_stderr():
    """TODO: doesn't reset when in Jupyter Notebooks, works fine between files"""
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    if sys.stdout is not sys.__stdout__:
        sys.stdout.close()  # Close the file handle opened for stdout
        sys.stdout = sys.__stdout__
    if sys.stderr is not sys.__stderr__:
        sys.stderr.close()  # Close the file handle opened for stderr
        sys.stderr = sys.__stderr__


def execute_functions_in_threadpool(func, args):
    # hardcoding mac_workers so as to not cause issues on sherwood
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as executor:
        futures = [executor.submit(func, *arg) for arg in args]
        return futures


def handle_errors(futures):
    for future in futures:
        try:
            future.result()
        except Exception as e:
            print(f"An error occurred: {e}")


# NEEDS WORK
################################################################################


def find_intersecting_cmip(
    variables: list[str],
    source_id: str = "EC-Earth3P-HR",
    member_id: str = "r1i1p2f1",
    lats: list[float, float] = [-40, 0],
    lons: list[float, float] = [130, 170],
    year_range: list[int, int] = [1950, 2014],
    levs: list[int, int] = [0, 20],
    cmip6_data_dir: Path | str = None
):

    # check whether exact intersecting cropped file already exists
    cmip6_dir_fp = config.cmip6_data_dir / source_id / member_id / "regridded" if not cmip6_data_dir else Path(cmip6_data_dir)
    print("Searching for correct CMIP files in:", cmip6_dir_fp)
    # TODO: include levs check. Much harder, so leaving for now
    correct_area_fps = list(
        find_files_for_area(cmip6_dir_fp.rglob("*.nc"), lat_range=lats, lon_range=lons),
    )
    # check that also spans full year range
    correct_fps = find_files_for_time(correct_area_fps, year_range=sorted(year_range))

    if len(correct_fps) > 0:
        # check that file includes all variables in variables list
        for fp in correct_fps:
            if all(variable in str(fp) for variable in variables):
                ds = utils.process_xa_d(xa.open_dataset(fp))
                ds_years = ds["time.year"]
                return (
                    ds.sel(
                        time=(ds_years >= min(year_range))
                        & (ds_years <= max(year_range)),
                        latitude=slice(min(lats), max(lats)),
                        longitude=slice(min(lons), max(lons)),
                    )[variables],
                    fp,
                )
    return None, None
