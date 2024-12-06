from pathlib import Path
import xarray as xa
import argparse
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from queue import Queue
from threading import Thread
import time
import logging
import subprocess
from cmipper import utils

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("processing.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

DO_DELETE_ORIGINAL = False
# Variable-specific remapping methods
# VARIABLE_REMAP_METHODS = {
#     "tos": "bilinear",
#     "thetao": "bilinear",
#     "so": "bilinear",
#     "rsdo": "bilinear",
#     "arag": "conservative",
#     "no3": "conservative",
#     "po4": "conservative",
# } # can't use bilinear for unstructred grids


def open_with_retries(file_path, engine="netcdf4", max_retries=10, delay=3):
    """Attempts to open a NetCDF file with retries to handle transient errors."""
    for attempt in range(max_retries):
        try:
            return xa.open_dataset(file_path, engine=engine)
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(delay)
            else:
                raise RuntimeError(
                    f"Failed to open {file_path} after {max_retries} attempts: {e}"
                )


def is_file_stable(file_path, wait_time=60, check_interval=0.5):
    """Check if a file is stable (i.e., not being written to)."""
    try:
        file_path = Path(file_path)
        previous_size = -1
        for _ in range(int(wait_time / check_interval)):
            current_size = file_path.stat().st_size
            if current_size == previous_size:
                return True
            previous_size = current_size
            time.sleep(check_interval)
    except FileNotFoundError:
        pass
    return False


def remapycon_to_grid(input_file, remap_file, output_file):
    """
    Use CDO remapycon to remap the input NetCDF file to a regular grid.
    """
    cmd = [
        "cdo",
        f"remapcon,{remap_file}",
        input_file,
        output_file,
    ]
    print(f"\tRemapping {input_file} -> {output_file}")
    try:
        subprocess.run(cmd, check=True)
        print(f"Remapped: {input_file} -> {output_file}")
    except subprocess.CalledProcessError as e:
        print(f"Error remapping {input_file}: {e}")


def extract_top_n_depths(nc_fp, n=10):
    """
    Extract the top 20 depths from a NetCDF file and overwrite it.
    """
    ds = xa.open_dataset(nc_fp)
    depth_dim = "depth" if "depth" in ds.dims else "lev" if "lev" in ds.dims else None

    if depth_dim:
        ds = ds.isel({depth_dim: slice(0, 2)})
        temp_dir = Path(nc_fp).parent / "extracted_levs"
        temp_dir.mkdir(exist_ok=True)
        temp_file = Path(temp_dir) / nc_fp.name
        if temp_file.exists():
            print(f"{temp_file} already exists. Skipping...")
        else:
            ds.to_netcdf(temp_file)
            print(f"\tProcessed file saved to temporary location: {temp_file}")
        return temp_file
    else:
        print(
            f"No 'depth' or 'lev' dimension found in {nc_fp} | Skipping level extraction."
        )
        return nc_fp


def process_file(
    nc_fp: Path,
    # remap_template: dict,
    max_depths: int,
    remap_dir: Path,
    processed_dir: Path,
    remap_file: Path,
    remap_method: str,
):
    """Function to process a single file."""
    try:
        nc_fp = Path(nc_fp)

        remap_dir = Path(remap_dir)
        remap_output_file = remap_dir / nc_fp.name
        processed_output_file = processed_dir / nc_fp.name

        if remap_output_file.exists():
            logger.warning(f"{remap_output_file} already exists. Skipping remapping...")
        else:
            logger.info(f"Remapping (conservative) {nc_fp}")
            # if irregular grid (contains "AWI" in the path), use remapcon now
            if "AWI" in str(nc_fp):

                ds = open_with_retries(nc_fp, engine="netcdf4")
                ds = utils.process_xa_d(utils.cdo_remap(ds, remap_file, remap_method))
                # remapycon_to_grid(
                #     nc_fp, remap_dir / "remap_grid.txt", remap_output_file
                # )
                # TODO: non-AWI files

        # extract desired level
        logger.info("remapped file", str(remap_output_file))
        ds.to_netcdf(remap_output_file)
        logger.info("processed_output_file", processed_output_file)
        # if not processed_output_file.exists():
        #     # select desired level(s)
        #     if any(processing.check_lev_exists(nc_fp)):
        #         logger.info(
        #             f"\tExtracting level value(s) from {nc_fp.stem}...",
        #             flush=True,
        #         )
        #         depth_dim = (
        #             "depth"
        #             if "depth" in ds.dims
        #             else "lev" if "lev" in ds.dims else None
        #         )
        #         ds = ds.isel({depth_dim: slice(0, 10)})
        #         logger.info("selected layers")
        #         # variable_id = nc_fp.stem.split("_")[0]

        #         # if variable_id in ds.variables:
        #         #     seafloor_indices = processing.gen_seafloor_indices(
        #         #         ds, variable_id, "depth"
        #         #     )
        #         #     ds = processing.extract_seafloor_vals_from_ds(
        #         #         ds, variable_id, seafloor_indices
        #         #     )
        #     else:
        #         logger.info(
        #             f"No depth values found in {nc_fp.stem} | Skipping extraction."
        #         )

        #     ("Saving to", processed_output_file)
        #     ds.to_netcdf(processed_output_file)

        # ds = open_with_retries(nc_fp, engine="netcdf4")

        # nc_fp = extract_top_n_depths(nc_fp, 10)  # TODO
        # # remap using cdo

        # # Remap using cdo
        # remap_file = remap_dir / "remap_grid.txt"
        # ds.to_netcdf(output_file)
        # ds = utils.process_xa_d(utils.cdo_remap(ds, remap_file, remap_method))

        logger.info(
            f"Saved processed (remapped and level selected) file: {processed_output_file}"
        )
        # ds.close()
        # if DO_DELETE_ORIGINAL:
        #     nc_fp.unlink()

    except Exception as e:
        logger.error(f"\n\nError processing {nc_fp}: {e}")


class FileEventHandler(FileSystemEventHandler):
    def __init__(self, remap_template, max_depths):
        super().__init__()
        self.remap_template = remap_template
        self.max_depths = max_depths
        self.file_queue = Queue()
        self.worker = Thread(target=self.process_queue, daemon=True)
        self.worker.start()

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".nc"):
            nc_fp = Path(event.src_path).resolve()

            # Skip processing if already in remap directory
            if any(dir in nc_fp.parts for dir in ["remapped", "processed"]):
                logger.info(f"Skipping already remapped/processed file: {nc_fp}")
                return

            logger.info(f"Detected new file: {nc_fp}")

            # Ensure the file is stable before proceeding
            if not is_file_stable(nc_fp):
                logger.warning(f"File {nc_fp} is not stable. Skipping...")
                return
            else:
                logger.info(f"File {nc_fp} is stable.")
                self.file_queue.put(nc_fp)

    def process_queue(self):
        while True:
            nc_fp = self.file_queue.get()
            try:
                self.process_file(nc_fp)
            except Exception as e:
                logger.error(f"Error processing {nc_fp}: {e}")
            finally:
                self.file_queue.task_done()

    def process_file(self, nc_fp):
        remap_dir = nc_fp.parent / "remapped"
        remap_dir.mkdir(exist_ok=True)
        processed_dir = nc_fp.parent / "processed"
        processed_dir.mkdir(exist_ok=True)

        # Determine the variable name from the directory structure
        variable = self.get_variable_name(nc_fp)
        if not variable:
            logger.warning(f"Variable not found in path: {nc_fp}")
            return

        # Get the remapping method for the variable
        # remap_method = VARIABLE_REMAP_METHODS.get(variable, "bilinear")
        remap_method = "conservative"
        logger.info(
            f"Variable: {variable}, Remapping method: {remap_method} for {nc_fp.name}"
        )

        # Create remap grid text file
        remap_file = remap_dir / "remap_grid.txt"
        if not remap_file.exists():
            self.create_remap_textfile(remap_file)

        process_file(
            nc_fp,
            # self.remap_template,
            self.max_depths,
            remap_dir,
            processed_dir,
            remap_file,
            remap_method,
        )

    def get_variable_name(self, nc_fp):
        try:
            return nc_fp.stem.split("_")[0]
        except IndexError:
            return None

    def create_remap_textfile(self, remap_file):
        try:
            with remap_file.open("w") as f:
                f.write("gridtype = lonlat\n")
                f.write(f"xsize = {self.remap_template['xsize']}\n")
                f.write(f"ysize = {self.remap_template['ysize']}\n")
                f.write(f"xfirst = {self.remap_template['xfirst']}\n")
                f.write(f"xinc = {self.remap_template['xinc']}\n")
                f.write(f"yfirst = {self.remap_template['yfirst']}\n")
                f.write(f"yinc = {self.remap_template['yinc']}\n")
            logger.info(f"Created remap grid text file: {remap_file}")
        except Exception as e:
            logger.error(f"Failed to create remap grid text file: {e}")


class DirectoryWatcher:
    def __init__(self, parent_dir, remap_template, max_depths):
        self.parent_dir = Path(parent_dir)
        self.remap_template = remap_template
        self.max_depths = max_depths

    def run(self):
        event_handler = FileEventHandler(
            remap_template=self.remap_template,
            max_depths=self.max_depths,
        )
        observer = Observer()
        observer.schedule(event_handler, str(self.parent_dir), recursive=True)
        observer.start()
        logger.info(f"Watching directory: {self.parent_dir}")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping directory watcher...")
            observer.stop()
        observer.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Watch a directory for NetCDF files and process them."
    )
    parser.add_argument(
        "parent_dir", help="The parent directory to watch for new .nc files."
    )
    args = parser.parse_args()

    remap_template = {
        "xsize": 1440,
        "ysize": 720,
        "xfirst": -180,
        "xinc": 0.25,
        "yfirst": -90,
        "yinc": 0.25,
    }

    logger.info(
        f"\n\n\n========================= {time.strftime('%Y-%m-%d %H:%M:%S')} ========================="
    )
    logger.info(f"Ready to accept files in {args.parent_dir}...")
    watcher = DirectoryWatcher(
        parent_dir=args.parent_dir,
        remap_template=remap_template,
        max_depths=20,
    )
    watcher.run()
