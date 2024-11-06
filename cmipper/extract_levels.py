# from concurrent.futures import ProcessPoolExecutor, as_completed
# from cmipper import config, processing, file_ops
# from pathlib import Path
# from tqdm import tqdm

# RAW_DATA_DIR = config.ESGPULL_DATA_DIR
# NUM_CORES = 16  # Specify the number of cores to use
# data_processing_config = file_ops.read_yaml(config.TMP_DIR / "data_processing.yaml")

# # set up download parameters
# # select_level = data_processing_config["select_level"]
# DO_DELETE_ORIGINAL = data_processing_config["do_delete_original"]

# def extract_levels(subdir): # TODO: more options
#     """Process a single subdirectory."""
#     print(subdir)
#     processing.process_raw_data_directory(subdir, chunk_schema=None, delete_og=DO_DELETE_ORIGINAL)

# def main():
#     # Fetch all subdirectories, ignoring those with 'deprecated'
#     subdirs = [subdir for subdir in Path(RAW_DATA_DIR).glob("**/")
#                     if "deprecated" not in str(subdir) and subdir.is_dir()]

#     # Use ProcessPoolExecutor to parallelize the processing of subdirectories
#     with ProcessPoolExecutor(max_workers=NUM_CORES) as executor:
#         futures = {executor.submit(extract_levels, subdir): subdir for subdir in subdirs}
#         for future in tqdm(as_completed(futures), total=len(futures),
#               desc="Processing raw data to extract levels..."):
#             subdir = futures[future]
#             try:
#                 future.result()  # Get the result to raise any exceptions
#             except Exception as e:
#                 print(f"Error processing {subdir}: {e}")


# def extract_levels(subdir):  # TODO: more options
#     """Process a single subdirectory."""
#     print(subdir)
#     processing.process_raw_data_directory(
#         subdir, chunk_schema=None, delete_og=DO_DELETE_ORIGINAL
#     )


# def main():
#     # Fetch all subdirectories, ignoring those with 'deprecated'
#     subdirs = [
#         subdir
#         for subdir in Path(RAW_DATA_DIR).glob("**/")
#         if "deprecated" not in str(subdir) and subdir.is_dir()
#     ]

#     # Process each subdirectory sequentially
#     for subdir in tqdm(subdirs, desc="Processing raw data to extract levels..."):
#         extract_levels(subdir)

from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from tqdm import tqdm
from cmipper import utils, config, processing, file_ops

RAW_DATA_DIR = config.ESGPULL_DATA_DIR
NUM_CORES = 16  # Specify the number of cores to use
data_processing_config = file_ops.read_yaml(config.TMP_DIR / "data_processing.yaml")

DO_DELETE_ORIGINAL = data_processing_config["do_delete_original"]
SELECT_LEVEL = data_processing_config["select_level"]
DO_REGRID = data_processing_config["do_regrid"]
REMAP_METHOD = data_processing_config["remap_method"]
OUTPUT_GRID = data_processing_config["output_grid"]


# regrid dir
regridded_data_dir_fp = config.TEST_DATA_DIR


def process_raw_data_directory(raw_data_dir_fp: Path, chunk_schema: dict = {"time": 1}):
    """Process all .nc files in a directory by extracting seafloor values.

    This function handles the setup and checks that should only run once per directory.

    Args:
        raw_data_dir_fp (Path): path to the directory containing .nc files

    Returns:
        None
    """
    nc_fps = list(Path(raw_data_dir_fp).glob("*.nc"))

    # level extraction
    if bool(SELECT_LEVEL):
        # ccheck if any .nc files in directory with 'lev' dimension
        if any(processing.check_lev_exists(file_path) for file_path in nc_fps):
            test_dir = raw_data_dir_fp / "extracted_lev"
            Path.mkdir(test_dir, exist_ok=True)

            # Check if files don't already exist in test_dir
            existing_files = set(test_dir.glob("*.nc"))
            if set(nc_fps).issubset(existing_files):
                print(f"All files in {raw_data_dir_fp} already processed.")
                return

            # Process each file
            unprocessed_files = set(nc_fps) - existing_files
            print(
                f"Found {len(unprocessed_files)} unprocessed files in {raw_data_dir_fp}."
            )

            # Use a lock to manage concurrent file processing
            for nc_file in tqdm(
                unprocessed_files,
                desc="Extracting level value(s)...",
                total=len(unprocessed_files),
            ):
                print(f"\tExtracting level value(s) from {nc_file.stem}...", flush=True)
                variable_id = nc_file.stem.split("_")[0]
                ds = processing.load_dataset_with_dask(
                    nc_file, chunk_schema=chunk_schema
                )

                if variable_id in ds.variables:
                    seafloor_indices = processing.find_seafloor_indices_for_directory(
                        raw_data_dir_fp
                    )
                    ds = processing.extract_seafloor_vals_from_ds(
                        ds, variable_id, seafloor_indices[raw_data_dir_fp]
                    )
                    ds.close()
                    ds.to_netcdf(test_dir / f"{nc_file.stem}.nc")

                if DO_DELETE_ORIGINAL:
                    nc_file.unlink()

        # regridding
        if DO_REGRID:
            # select directories either "extracted_lev" which are subdirectories of raw_data_dir_fp,
            # or which are "tos", "rsds"
            if "extracted_lev" in str(raw_data_dir_fp) or raw_data_dir_fp.name in [
                "tos",
                "rsds",
            ]:
                nc_files = list(raw_data_dir_fp.glob("*.nc"))
                remap_template_fp = processing.handle_cdo_template(
                    nc_files[0],
                    raw_data_dir_fp,
                    OUTPUT_GRID,
                )
                # make new directory for regridded data
                regridded_dir = (
                    regridded_data_dir_fp
                    / raw_data_dir_fp.resolve().relative_to(config.ESGPULL_DATA_DIR)
                )
                Path.mkdir(regridded_dir, exist_ok=True)

                for nc_file in tqdm(nc_files, desc=f"Regridding {raw_data_dir_fp}..."):
                    # get new fp
                    regridded_fp = regridded_dir / nc_file.name
                    # if file already exists, skip
                    if regridded_fp.exists():
                        print(f"{regridded_fp} already exists.")
                        continue

                    # Perform regridding operation here
                    print(f"\tRegridding {nc_file.stem}...", flush=True)
                    ds = processing.load_dataset_with_dask(
                        nc_file, chunk_schema=chunk_schema
                    )
                    regridded_ds = utils.process_xa_d(
                        utils.cdo_remap(
                            ds,
                            remap_template_fp=remap_template_fp,
                            remap_method=REMAP_METHOD,
                        )
                    )
                    regridded_ds.to_netcdf(regridded_fp)
                    ds.close()
                    regridded_ds.close()

                if DO_DELETE_ORIGINAL:
                    nc_file.unlink()


def extract_levels(subdir):
    """Process a single subdirectory."""
    process_raw_data_directory(subdir)


def main():
    # Fetch all subdirectories, ignoring those with 'deprecated'
    subdirs = [
        subdir
        for subdir in Path(RAW_DATA_DIR).glob("**/")
        if "deprecated" not in str(subdir) and subdir.is_dir()
    ]

    # Use ProcessPoolExecutor to parallelize the processing of subdirectories
    with ProcessPoolExecutor(max_workers=NUM_CORES) as executor:
        futures = {
            executor.submit(extract_levels, subdir): subdir for subdir in subdirs
        }
        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc="Processing raw data to extract levels...",
        ):
            subdir = futures[future]
            try:
                future.result()  # Get the result to raise any exceptions
            except Exception as e:
                print(f"Error processing {subdir}: {e}")


if __name__ == "__main__":
    main()
