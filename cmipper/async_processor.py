from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from tqdm import tqdm
import xarray as xa
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from cmipper import utils, config, processing, file_ops
import time

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

        if any(
            keyword in str(raw_data_dir_fp)
            for keyword in ["extracted_lev", "tos", "rsds"]
        ):

            nc_files = list(raw_data_dir_fp.glob("*.nc"))
            remap_template_fp = processing.handle_cdo_template(
                xa.open_dataset(nc_files[0]),
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


class NewFileHandler(FileSystemEventHandler):
    def __init__(self, executor):
        self.executor = executor

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(".nc"):
            subdir = Path(event.src_path).parent
            self.executor.submit(process_raw_data_directory, subdir)


def main():
    print("Waiting for new files...")
    # Use ProcessPoolExecutor to parallelize the processing of subdirectories
    with ProcessPoolExecutor(max_workers=NUM_CORES) as executor:
        event_handler = NewFileHandler(executor)
        observer = Observer()
        observer.schedule(event_handler, str(RAW_DATA_DIR), recursive=True)
        observer.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()


if __name__ == "__main__":
    main()
