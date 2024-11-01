# general
import numpy as np
import pathlib
from pathlib import Path

# spatial
import xarray as xa
from netCDF4 import Dataset


def check_lev_exists(file_path):
    """Check if the file has a 'lev' dimension or variable without loading it all into memory."""
    try:
        with Dataset(str(file_path), 'r') as nc_file:
            return 'lev' in nc_file.dimensions or 'lev' in nc_file.variables
    except Exception as e:
        print(f"Error checking {file_path}: {e}")
        return False
    

def extract_all_variables_at_level_netcdf(file_path, level_index):
    data_at_level = {}
    try:
        with Dataset(file_path, 'r') as nc_file:
            # Check if 'lev' dimension exists
            if 'lev' in nc_file.dimensions:
                for var_name, var in nc_file.variables.items():
                    # Ensure the variable has the 'lev' dimension
                    if 'lev' in var.dimensions:
                        # Get the data for the specific level index
                        data_at_level[var_name] = var[level_index, ...]  # Get all dimensions at the specific level
                    else:
                        # If the variable does not have 'lev' dimension, you can choose to include it if needed
                        data_at_level[var_name] = var[:]
    except Exception as e:
        print(f"Error extracting pressure level data from {file_path}: {e}")
    return data_at_level



def load_dataset_with_dask(file_path):
    return xa.open_dataset(file_path, chunks={"time": 1, "j": 100, "i": 100})  # Adjust chunks based on your memory constraints



def find_seafloor_indices_for_directory(raw_data_dir_fp: Path):
    seafloor_indices = {}
    directory = pathlib.Path(raw_data_dir_fp)

    # in naming of file, first section before _ is the variable name
    # Iterate through all .nc files in the directory
    for nc_file in directory.glob('**/*.nc'):
        ds = load_dataset_with_dask(nc_file)
        variable_id = nc_file.stem.split('_')[0]
        indices = gen_seafloor_indices(ds, var=variable_id)  # Assuming this function is already defined
        seafloor_indices[nc_file.stem] = indices  # Store by filename stem
        # Close the dataset to free resources
        ds.close()
        break  # Since all files are the same, we can break after the first

    return seafloor_indices


def extract_seafloor_vals_from_ds(ds, variable_id: str, seafloor_indices: np.ndarray):
    print("\n\textracting seafloor values...", flush=True)
    cmip6_array = extract_3d_index_vals(ds[variable_id], seafloor_indices)
    
    # Overwrite the original variable with the extracted values
    ds[variable_id] = (["time", "j", "i"], cmip6_array)
    return ds


def extract_3d_index_vals(xa_da: xa.DataArray, indices_array: np.ndarray):
    # Use the Dask array for efficient indexing
    return xa_da.isel(lev=indices_array).data


def process_raw_data_directory(raw_data_dir_fp: Path):
    seafloor_indices = find_seafloor_indices_for_directory(raw_data_dir_fp)

    # Process each file using the precomputed indices
    for nc_file in pathlib.Path(raw_data_dir_fp).glob('**/*.nc'):
        variable_id = nc_file.stem.split('_')[0]
        ds = load_dataset_with_dask(nc_file)
        
        if variable_id in ds.variables:
            ds = extract_seafloor_vals_from_ds(ds, variable_id, seafloor_indices[nc_file.stem])
            # Save or process the dataset as needed
            # ds.to_netcdf(f"processed/{nc_file.name}")
        
        ds.close()


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
    # if 'time' in xa_d.dims (seafloor indices are constant in time):
    time_slice = xa_d.isel(time=0)
    
    valid_mask = ~np.isnan(time_slice[var])
    seafloor_indices = xa.where(valid_mask, time_slice[dim], -1)  # Replace NaNs with -1
    indices_array = seafloor_indices.argmax(dim=dim)
    # Set indices to -1 where no valid levels were found
    indices_array = indices_array.where(valid_mask.any(dim=dim), -1)
    
    # broadcast to all time slices
    indices_array = indices_array.expand_dims({"time": xa_d.time})

    return indices_array.values  # Convert to NumPy array

# def gen_seafloor_indices(xa_d: xa.Dataset, var: str, dim: str = "lev"):
#     """Generate indices of seafloor values for a given variable in an xarray dataset.

#     Args:
#         xa_d (xa.Dataset): xarray dataset containing variable of interest
#         var (str): name of variable of interest
#         dim (str, optional): dimension along which to search for seafloor values. Defaults to "lev".

#     Returns:
#         indices_array (np.ndarray): array of indices of seafloor values for given variable
#     """
#     print("\ndetermining seafloor indices... ", flush=True)
#     nans = np.isnan(xa_d[var]).sum(dim=dim)  # separate out
#     indices_array = -(nans.values) - 1
#     indices_array[indices_array == -(len(xa_d[dim].values) + 1)] = -1
#     return indices_array

    
    # if plevels == -1:  # plevel == -1: seafloor
    #     ds, seafloor_indices = utils.extract_seafloor_vals(ds, variable_id, seafloor_indices)
    # elif isinstance(plevels, tuple):    # plevel == list[float]: multiple pressure levels
    #     print(f"extracting {min(plevels) / 100:.03f} to {max(plevels) / 100:.03f} hPa", flush=True)
    #     ds = ds.sel(lev=slice(min(plevels), max(plevels)))[variable_id]
    # elif isinstance(plevels, list):    # plevel == list[float]: multiple pressure levels                                
    #     plevels_strs = [f"{p / 100:.03f}" for p in plevels]
    #     print(f"extracting {plevels_strs} hPa pressure levels", flush=True)
    #     ds = ds.sel(plevels)[variable_id]
    # elif isinstance(plevels, float):    # plevel == float: single pressure levelß
    #     print(f"extracting {plevels / 100:.03f} hPa", flush=True)
    #     ds = ds.sel(lev=plevels)[variable_id]
    # else:
    #     raise ValueError("plevels must be null (indicating seafloor variable), a list of floats, a float, or -1 (indicating seafloor variable)")
