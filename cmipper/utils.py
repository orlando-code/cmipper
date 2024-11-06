# general
from pathlib import Path
import numpy as np
import re

# spatial
import xarray as xa
from cdo import Cdo

# TODO: add expected finish time based on length of results and time of execution per result


def lat_lon_string_from_tuples(
    lats: tuple[float, float], lons: tuple[float, float], dp: int = 0
):
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    lats = [round_to_1_sf_after_decimal(min_lat), round_to_1_sf_after_decimal(max_lat)]
    lons = [round_to_1_sf_after_decimal(min_lon), round_to_1_sf_after_decimal(max_lon)]

    lats_strs = [
        (
            f"s{replace_dot_with_dash(str(abs(lat)))}"
            if lat < 0
            else f"n{replace_dot_with_dash(str(abs(lat)))}"
        )
        for lat in lats
    ]  # noqa
    lons_strs = [
        (
            f"w{replace_dot_with_dash(str(abs(lon)))}"
            if lon < 0
            else f"e{replace_dot_with_dash(str(abs(lon)))}"
        )
        for lon in lons
    ]  # noqa

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
    parts = str(num).split(".")
    # if there is a decimal part
    if len(parts) == 2:
        dec_part = parts[1]

        # determine number of zeros before first non-zero digit
        num_zeros = 0
        for i in range(len(dec_part)):
            if dec_part[i] == "0":
                num_zeros += 1
            else:
                break
        return float(f"{parts[0]}.{num_zeros*'0'}{dec_part[0]}")  # noqa
    else:
        return float(parts[0])


def iterative_to_string_list(iter_obj: tuple, dp: int = 0):
    # Round the values in the iterable object to the specified number of decimal places
    return [round(i, dp) for i in iter_obj]


def gen_seafloor_indices(xa_d: xa.Dataset, var: str, dim: str = "lev"):
    """Generate indices of seafloor values for a given variable in an xarray dataset.

    Args:
        xa_d (xa.Dataset): xarray dataset containing variable of interest
        var (str): name of variable of interest
        dim (str, optional): dimension along which to search for seafloor values. Defaults to "lev".

    Returns:
        indices_array (np.ndarray): array of indices of seafloor values for given variable
    """
    print("\ndetermining seafloor indices... ", flush=True)
    nans = np.isnan(xa_d[var]).sum(dim=dim)  # separate out
    indices_array = -(nans.values) - 1
    indices_array[indices_array == -(len(xa_d[dim].values) + 1)] = -1
    return indices_array


def extract_3d_index_vals(xa_da, indices_array):
    vals_array = (
        xa_da.values
    )  # this is what takes a long time since involves loading whole file at a limited rate
    t, j, i = indices_array.shape
    # create open grid for indices along each dimension
    t_grid, j_grid, i_grid = np.ogrid[:t, :j, :i]
    # select values from vals_array using indices_array
    return vals_array[t_grid, indices_array, j_grid, i_grid]


def extract_seafloor_vals_from_ds(ds, variable_id):
    # print(type(ds))
    # print(ds)
    seafloor_indices = gen_seafloor_indices(ds, var=variable_id)
    seafloor_indices = np.broadcast_to(
        seafloor_indices,
        (
            len(ds.time),
            len(ds.j),
            len(ds.i),
        ),  # these variable names may differ by model
    )
    print("\n\textracting seafloor values...", flush=True)
    cmip6_array = extract_3d_index_vals(ds[variable_id], seafloor_indices)
    ds[variable_id] = (["time", "j", "i"], cmip6_array)
    return ds, seafloor_indices


def extract_seafloor_vals(
    ds: xa.Dataset, variable_id: str = None, seafloor_indices: np.ndarray = None
):
    # if seafloor indices not yet calculated, calculate
    if seafloor_indices is None:
        seafloor_indices = gen_seafloor_indices(
            ds.isel(time=0),
            var=variable_id,
        )
        seafloor_indices = np.broadcast_to(
            seafloor_indices,
            (
                len(ds.time),
                len(ds.j),
                len(ds.i),
            ),  # these variable names may differ by model
        )
    print("\n\textracting seafloor values...", flush=True)
    cmip6_array = extract_3d_index_vals(ds[variable_id], seafloor_indices)
    ds[variable_id] = (["time", "j", "i"], cmip6_array)
    return ds, seafloor_indices


def return_remap_template(
    input_file: str | xa.Dataset,
    remap_template_fp: str | Path,
    resolutions: tuple[float] = None,
    out_grid: str = "latlon",
):
    # if not Path(remap_template_fp).exists():   # if remap template not provided, generate it
    # if file provided as fp rather than ds, open dataset to determine data
    if isinstance(input_file, str):
        input_file = xa.open_dataset(Path(input_file))

    generate_remapping_file(
        input_file,
        remap_template_fp=remap_template_fp,
        resolutions=resolutions,
        out_grid=out_grid,
    )
    # else:
    #     print(f"Found existing remap template file at {remap_template_fp}")
    return remap_template_fp


def generate_remapping_file(
    eg_xa: xa.Dataset | xa.DataArray,
    remap_template_fp: str | Path,
    resolutions: tuple[float] = None,
    out_grid: str = "latlon",
):
    xsize, ysize, xfirst, yfirst, x_inc, y_inc = generate_remap_info(
        eg_nc=eg_xa, resolutions=resolutions
    )

    # print(f"Saving regridding info to {remap_template_fp}")
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


def generate_remap_info(eg_nc, resolutions: tuple[float] = None):
    # standardise names to extract values
    rename_mapping = {
        "lat": "latitude",
        "lon": "longitude",
        "y": "latitude",
        "x": "longitude",
    }
    for coord, new_coord in rename_mapping.items():
        if new_coord not in eg_nc.coords and coord in eg_nc.coords:
            eg_nc = eg_nc.rename({coord: new_coord})

    # [-180, 180] longitudinal range
    max_lon = np.max(eg_nc.longitude.values)
    min_lon = np.min(eg_nc.longitude.values)
    if max_lon > 180:  # no better way to check this without providing explicit argument
        min_lon -= 180
    else:
        min_lon = np.min(eg_nc.longitude.values)
    min_lat = np.min(eg_nc.latitude.values)
    xfirst = min_lon
    yfirst = min_lat

    # xsize = int(360 / resolution)
    # # [smallest latitude, largest latitude] range
    # ysize = int((180 / resolution) + yfirst)

    lat_range = np.max(eg_nc.latitude.values) - np.min(eg_nc.latitude.values)
    lon_range = np.max(eg_nc.longitude.values) - np.min(eg_nc.longitude.values)

    if not resolutions:  # keep at original resolution
        coord_shape = eg_nc.latitude.shape
        if len(coord_shape) == 2:
            num_xcells = coord_shape[1]
            num_ycells = coord_shape[0]
        else:
            num_xcells = len(eg_nc.latitude.values)
            num_ycells = len(eg_nc.longitude.values)

        lat_res = lat_range / num_ycells
        lon_res = lon_range / num_xcells
    else:
        lat_res, lon_res = resolutions

    xsize = int(lon_range / lon_res)
    ysize = int(lat_range / lat_res)

    xinc, yinc = lon_res, lat_res

    # xsize = (np.max(eg_nc.longitude.values)-np.min(eg_nc.longitude.values))/num_xcells
    # ysize = (np.max(eg_nc.longitude.values)-np.min(eg_nc.longitude.values))/num_ycells

    # x_inc, y_inc = resolution, resolution

    return xsize, ysize, xfirst, yfirst, xinc, yinc


def cdo_remap_fly(
    input_object: str | xa.Dataset,
    resolutions: tuple[float] = None,
    variable: str = None,
    remap_method: str = "bilinear",
):
    remap_template_fp = Path.cwd() / "temp_remap_template.txt"
    remap_template_fp = return_remap_template(
        input_object, remap_template_fp, resolutions=resolutions
    )
    remapped = cdo_remap(input_object, remap_template_fp, remap_method)
    remap_template_fp.unlink()  # remove temporary remap template file
    return remapped


def cdo_remap(
    input_object: str | xa.Dataset,
    remap_template_fp: str = None,
    remap_method: str = "bilinear",
):
    cdo = Cdo()
    if remap_method == "bilinear":
        return cdo.remapbil(remap_template_fp, input=input_object, returnXDataset=True)
    elif remap_method == "bicubic":
        return cdo.remapbic(remap_template_fp, input=input_object, returnXDataset=True)
    elif remap_method == "nearest":
        return cdo.remapnn(remap_template_fp, input=input_object, returnXDataset=True)
    elif remap_method == "remapdis":
        return cdo.remapdis(remap_template_fp, input=input_object, returnXDataset=True)
    elif remap_method == "conservative":
        return cdo.remapcon(remap_template_fp, input=input_object, returnXDataset=True)
    elif remap_method == "distance":
        return cdo.remapdis(
            remap_template_fp, neighbours=8, input=input_object, returnXDataset=True
        )
    elif remap_method == "mean":
        return cdo.remapmean(remap_template_fp, input=input_object, returnXDataset=True)
    elif remap_method == "sum":
        print("summing")
        return cdo.remapsum(remap_template_fp, input=input_object, returnXDataset=True)
    else:
        raise ValueError(f"Invalid/not-yet-implemented remap method: {remap_method}")


def generate_chunk_bounds(
    degrees_lat,
    degrees_lon,
    lat_range=(-90, 90),
    lon_range=(-180, 180),
    lat_buffer=1,
    lon_buffer=1,
):
    """
    Generate latitude and longitude bounds for chunks spanning a specified range.

    Parameters:
    - degrees_lat (float): Number of degrees on each side of latitude chunks.
    - degrees_lon (float): Number of degrees on each side of longitude chunks.
    - lat_range (tuple): Range of latitudes (default: (-90, 90)).
    - lon_range (tuple): Range of longitudes (default: (-180, 180)).

    Returns:
    - lat_bounds (list): List of latitude bounds for each chunk.
    - lon_bounds (list): List of longitude bounds for each chunk.
    """

    # Calculate the number of latitude and longitude chunks
    N_lat = int((lat_range[1] - lat_range[0]) / degrees_lat)
    N_lon = int((lon_range[1] - lon_range[0]) / degrees_lon)

    # Calculate the step size for latitude and longitude
    lat_step = (lat_range[1] - lat_range[0]) / N_lat
    lon_step = (lon_range[1] - lon_range[0]) / N_lon

    # Generate latitude bounds
    lat_bounds = [
        (lat_range[0] + i * lat_step, lat_range[0] + (i + 1) * lat_step)
        for i in range(N_lat)
    ]
    # Generate longitude bounds
    lon_bounds = [
        (lon_range[0] + i * lon_step, lon_range[0] + (i + 1) * lon_step)
        for i in range(N_lon)
    ]

    lat_bounds = [
        (min(lat_bound) - lat_buffer, max(lat_bound) + lat_buffer)
        for lat_bound in lat_bounds
    ]
    lon_bounds = [
        (min(lon_bound) - lat_buffer, max(lon_bound) + lat_buffer)
        for lon_bound in lon_bounds
    ]

    return lat_bounds, lon_bounds


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
    temp_xa_d = temp_xa_d.squeeze()  # remove size 1 dimensions

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


def limit_model_info_dict(model: dict, download: dict):
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


def extract_matching_subsets(first_dict, second_dict):
    matching_subsets = {}

    for model in first_dict:
        if model in second_dict:
            matching_subsets[model] = {}

            # Extract matching variable_ids
            first_var_ids = set(first_dict[model].get("variable_ids", []))
            second_var_dict = second_dict[model].get("variable_dict", {})
            matching_var_ids = {
                var: second_var_dict[var]
                for var in first_var_ids
                if var in second_var_dict
            }
            if matching_var_ids:
                matching_subsets[model]["variable_dict"] = matching_var_ids

            # Extract matching member_ids
            first_member_ids = set(first_dict[model].get("member_ids", []))
            second_member_ids = set(second_dict[model].get("member_ids", []))
            matching_member_ids = list(first_member_ids.intersection(second_member_ids))
            if matching_member_ids:
                matching_subsets[model]["member_ids"] = matching_member_ids

            # Extract matching experiment_ids
            first_experiment_ids = set(first_dict[model].get("experiment_ids", {}))
            second_experiment_ids = set(second_dict[model].get("experiment_ids", []))
            matching_experiment_ids = list(
                first_experiment_ids.intersection(second_experiment_ids)
            )
            if matching_experiment_ids:
                matching_subsets[model]["experiment_ids"] = matching_experiment_ids

    return matching_subsets


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
    return re.sub(r"(?<=\d)-(?=\d)", ".", string)


def dash_process_coordinate(num_string):
    if num_string[0] == "-":
        if "-" in num_string[1:] and re.match(r"\d+-\d+", num_string[1:]):
            return -float(replace_decimal_dash_with_dot(num_string[1:]))
    # Check if the dash is sandwiched between two numbers before replacing it
    if "-" in num_string and re.match(r"\d+-\d+", num_string):
        return float(replace_decimal_dash_with_dot(num_string))
    return float(num_string)


def does_nc_open(nc_fp):
    try:
        xa.open_dataset(nc_fp)
        return True
    except Exception:
        return False


def does_nc_have_duplicate_coords(nc_fp):
    ds = xa.open_dataset(nc_fp)
    # iterate through coords
    for coord in ds.coords:
        if has_duplicates(ds[coord].values):
            return False
    else:
        return True


# POTENTIAL FUTURE USE
# ################################################################################

# def edit_yaml(yaml_path: str | Path, info: dict):
#     yaml_info = read_yaml(yaml_path)
#     yaml_info.update(info)

#     save_yaml(yaml_path, yaml_info)


# def save_yaml(yaml_path: str | Path, info: dict):
#     with open(yaml_path, "w") as file:
#         yaml.dump(info, file)
