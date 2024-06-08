import xarray as xa
import numpy as np
import re

from pathlib import Path


def lat_lon_string_from_tuples(
    lats: tuple[float, float], lons: tuple[float, float], dp: int = 0
):
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    lats = [round_to_1_sf_after_decimal(min_lat), round_to_1_sf_after_decimal(max_lat)]
    lons = [round_to_1_sf_after_decimal(min_lon), round_to_1_sf_after_decimal(max_lon)]

    lats_strs = [f"s{replace_dot_with_dash(str(abs(lat)))}" if lat < 0 else f"n{replace_dot_with_dash(str(abs(lat)))}" for lat in lats]   # noqa
    lons_strs = [f"w{replace_dot_with_dash(str(abs(lon)))}" if lon < 0 else f"e{replace_dot_with_dash(str(abs(lon)))}" for lon in lons]   # noqa

    return "_".join(lats_strs + lons_strs)


def round_to_1_sf_after_decimal(num):
    """
    Rounds a number to 1 significant figure after the decimal point.

    Args:
        num (float): The number to be rounded.

    Returns:
        float: The rounded number.

    Examples:
        >>> round_to_1_sf_after_decimal(3.14159)
        3.1
        >>> round_to_1_sf_after_decimal(10.567)
        10.6
        >>> round_to_1_sf_after_decimal(0.005)
        0.0
    """
    parts = str(num).split('.')
    # if there is a decimal part
    if len(parts) == 2:
        dec_part = parts[1]

        # determine number of zeros before first non-zero digit
        num_zeros = 0
        for i in range(len(dec_part)):
            if dec_part[i] == '0':
                num_zeros += 1
            else:
                break
        return float(parts[0] + '.' + num_zeros*'0' + f"{float(f"{float(dec_part):.1g}"):g}"[0])    # noqa
    else:
        return float(parts[0])


def iterative_to_string_list(iter_obj: tuple, dp: int = 0):
    # Round the values in the iterable object to the specified number of decimal places
    return [round(i, dp) for i in iter_obj]


def gen_seafloor_indices(xa_da: xa.Dataset, var: str, dim: str = "lev"):
    """Generate indices of seafloor values for a given variable in an xarray dataset.

    Args:
        xa_da (xa.Dataset): xarray dataset containing variable of interest
        var (str): name of variable of interest
        dim (str, optional): dimension along which to search for seafloor values. Defaults to "lev".

    Returns:
        indices_array (np.ndarray): array of indices of seafloor values for given variable
    """
    nans = np.isnan(xa_da[var]).sum(dim=dim)  # separate out
    indices_array = -(nans.values) - 1
    indices_array[indices_array == -(len(xa_da[dim].values) + 1)] = -1
    return indices_array


def extract_seafloor_vals(xa_da, indices_array):
    vals_array = xa_da.values
    t, j, i = indices_array.shape
    # create open grid for indices along each dimension
    t_grid, j_grid, i_grid = np.ogrid[:t, :j, :i]
    # select values from vals_array using indices_array
    return vals_array[t_grid, indices_array, j_grid, i_grid]


def generate_remap_info(eg_nc, resolution=0.25, out_grid: str = "latlon"):
    # [-180, 180] longitudinal range
    xfirst = float(np.min(eg_nc.longitude).values) - 180
    yfirst = float(np.min(eg_nc.latitude).values)

    xsize = int(360 / resolution)
    # [smallest latitude, largest latitude] range
    ysize = int((180 / resolution) + yfirst)

    x_inc, y_inc = resolution, resolution

    return xsize, ysize, xfirst, yfirst, x_inc, y_inc


def generate_remapping_file(
    eg_xa: xa.Dataset | xa.DataArray,
    remap_template_fp: str | Path,
    resolution: float = 0.25,
    out_grid: str = "latlon",
):
    xsize, ysize, xfirst, yfirst, x_inc, y_inc = generate_remap_info(
        eg_nc=eg_xa, resolution=resolution, out_grid=out_grid
    )

    print(f"Saving regridding info to {remap_template_fp}...")
    with open(remap_template_fp, "w") as file:
        file.write(
            f"gridtype = {out_grid}\n"
            f"xsize = {xsize}\n"
            f"ysize = {ysize}\n"
            f"xfirst = {xfirst}\n"
            f"yfirst = {yfirst}\n"
            f"xinc = {x_inc}\n"
            f"yinc = {y_inc}\n"
        )


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
    # drop variables which will never be variables
    # TODO: add as argument with default
    drop_vars = ["time_bnds"]
    temp_xa_d = temp_xa_d.drop_vars(
        [var for var in drop_vars if var in temp_xa_d.variables]
    )
    # sort coords by ascending values
    return temp_xa_d.sortby(list(temp_xa_d.dims))


def limit_model_info_dict(model, download):
    """
    Limit the model info dict to only the data that is specified for the download.
    """
    return {
        source_id: {
            "resolution": source_data["resolution"],
            "experiment_ids": [
                exp_id
                for exp_id in source_data["experiment_ids"]
                if exp_id in download["experiment_ids"]
            ],
            "member_ids": [
                member_id
                for member_id in source_data["member_ids"]
                if member_id in download["member_ids"]
            ],
            "data_nodes": source_data["data_nodes"],
            "frequency": source_data["frequency"],
            "variable_dict": {
                var_id: var_data
                for var_id, var_data in source_data["variable_dict"].items()
                if var_id in download["variable_ids"]
            },
        }
        for source_id, source_data in model.items()
        if any(
            var_id in download["variable_ids"]
            for var_id in source_data["variable_dict"]
        )
    }


def has_duplicates(arr):
    # Convert the array to a NumPy array if it's not already
    arr = np.asarray(arr)
    # Check if any values are duplicated
    return len(arr) != len(np.unique(arr))


def replace_dash_with_dot(string: str):
    return string.replace("-", ".")

def replace_dot_with_dash(string: str):
    return string.replace(".", "-")

def replace_decimal_dash_with_dot(string):
    return re.sub(r'(?<=\d)-(?=\d)', '.', string)


def dash_process_coordinate(num_string):
    if num_string[0] == "-":
        if "-" in num_string[1:] and re.match(r'\d+-\d+', num_string[1:]):
            return -float(replace_decimal_dash_with_dot(num_string[1:]))
    # Check if the dash is sandwiched between two numbers before replacing it
    if "-" in num_string and re.match(r'\d+-\d+', num_string):
        return float(replace_decimal_dash_with_dot(num_string))
    return float(num_string)



# POTENTIAL FUTURE USE
# ################################################################################

# def edit_yaml(yaml_path: str | Path, info: dict):
#     yaml_info = read_yaml(yaml_path)
#     yaml_info.update(info)

#     save_yaml(yaml_path, yaml_info)


# def save_yaml(yaml_path: str | Path, info: dict):
#     with open(yaml_path, "w") as file:
#         yaml.dump(info, file)
