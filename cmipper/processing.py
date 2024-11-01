# general
import numpy as np
import pathlib
from pathlib import Path
from tqdm.auto import tqdm

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
    

def extract_dataset_at_level_xarray(file_path: str | Path, select_level: int | list | tuple) -> xa.Dataset:
    """Extract a dataset at a given pressure level index using xarray.
    
    Args:
        file_path (str | Path): path to the netCDF file
        select_level (int | list | tuple): specify pressure level(s) to extract.
            * -1: seafloor values
            * int: pressure level index
            * float: closest pressure level
            * list/tuple: range of pressure levels
    
    Returns:
        xa.Dataset: dataset containing variables at the specified pressure level
        
    Exceptions:
        IndexError: if the level index is out of bounds, return surface values instead        
    """ 
    try:
        ds = xa.open_dataset(file_path)
        data_at_level = {}

        if 'lev' in ds.dims:    # if the dataset has a 'lev' dimension, continue to extract
            for var_name, var_data in ds.data_vars.items():
                if var_name == "lev_bnds":
                    continue

                if 'lev' in var_data.dims:
                    if select_level == -1:  # select seafloor values
                        ds = extract_seafloor_vals_from_ds(ds, var_name)
                        data_at_level[var_name] = ds[var_name]
                    else:   # anything but seafloor values
                        try:
                            if isinstance(select_level, (tuple, list)): # if select_level is a range
                                data_at_level[var_name] = var_data.isel(lev=slice(min(select_level), max(select_level)))
                            else:   # if select_level is a float, return closest value; if an int, return that level index
                                data_at_level[var_name] = var_data.sel(lev=select_level, method="nearest") if isinstance(select_level, float) else var_data.isel(lev=select_level)
                        except IndexError:
                            print(f"{select_level} is out of bounds. Returning surface values instead...")
                            data_at_level[var_name] = var_data.isel(lev=0)
                else:
                    data_at_level[var_name] = var_data
        else:   # if no 'lev' dimension, return all data
            data_at_level = {var_name: var_data for var_name, var_data in ds.data_vars.items()}

        return xa.Dataset(data_at_level)

    except Exception as e:
        print(f"Error extracting pressure level data from {file_path}: {e}")
        return None


def load_dataset_with_dask(file_path: str | Path) -> xa.Dataset:
    """Load a dataset using xarray with dask for parallel processing. Leave spatial chunking as automatic"""
    return xa.open_dataset(file_path, chunks={"time": 1})


def find_seafloor_indices_for_directory(raw_data_dir_fp: Path):
    """Find the indices of seafloor values for all .nc files in a directory.
    
    Args:
        raw_data_dir_fp (Path): path to the directory containing .nc files
        
    Returns:
        seafloor_indices (dict): dictionary of seafloor indices for directory .nc files
    """
    seafloor_indices = {}
    directory = pathlib.Path(raw_data_dir_fp)

    # Iterate through all .nc files in the directory
    for nc_file in directory.glob('**/*.nc'):
        ds = load_dataset_with_dask(nc_file)
        # in naming of file, first section before _ is the variable name
        variable_id = nc_file.stem.split('_')[0]
        indices = gen_seafloor_indices(ds, var=variable_id)  # Assuming this function is already defined
        seafloor_indices[nc_file.parent] = indices  # Store by filename stem
        # Close the dataset to free resources
        ds.close()
        break  # Since all files are the same, we can break after the first

    return seafloor_indices


def extract_seafloor_vals_from_ds(ds: xa.Dataset, variable_id: str) -> xa.Dataset:
    """Extract seafloor values from a dataset for a given variable.
    
    Args:
        ds (xa.Dataset): xarray dataset containing variable of interest
        variable_id (str): name of variable of interest
    
    Returns:
        ds (xa.Dataset): dataset with seafloor values extracted
    """
    seafloor_indices = gen_seafloor_indices(ds, var=variable_id)
    cmip6_array = extract_3d_index_vals(ds[variable_id], seafloor_indices)
    # Overwrite the original variable with the extracted values
    ds[variable_id] = (["time", "i", "j"], cmip6_array)
    return ds


def extract_3d_index_vals(xa_da: xa.DataArray, indices_array: np.ndarray) -> np.ndarray:
    """Extract values from an xarray data array using 3D indices.
    
    Args:
        xa_da (xa.DataArray): xarray data array containing values to extract
        indices_array (np.ndarray): array of indices to extract
        
    Returns:
        np.ndarray: array of extracted values
    """
    vals_array = xa_da.values   # this is what takes a long time since involves loading whole file at a limited rate
    t, j, i = indices_array.shape
    # create open grid for indices along each dimension
    t_grid, j_grid, i_grid = np.ogrid[:t, :j, :i]
    # select values from vals_array using indices_array
    return vals_array[t_grid, indices_array, j_grid, i_grid]


def process_raw_data_directory(raw_data_dir_fp: Path):
    """Process all .nc files in a directory by extracting seafloor values.
    
    Args:
        raw_data_dir_fp (Path): path to the directory containing .nc files
    
    Returns:
        None
    """
    seafloor_indices = find_seafloor_indices_for_directory(raw_data_dir_fp)

    # Process each file using the precomputed indices
    for nc_file in tqdm(Path(raw_data_dir_fp).glob('**/*.nc'), desc="Extracting seafloor values...", total=len(list(Path(raw_data_dir_fp).glob('**/*.nc')))):
        variable_id = nc_file.stem.split('_')[0]
        ds = load_dataset_with_dask(nc_file)
        
        if variable_id in ds.variables:
            ds = extract_seafloor_vals_from_ds(ds, variable_id, seafloor_indices[raw_data_dir_fp])
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
