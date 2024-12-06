from pathlib import Path
import xarray as xa
import argparse
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from concurrent.futures import ProcessPoolExecutor
from cmipper import utils
import logging
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("processing.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


# Variable-specific remapping methods
VARIABLE_REMAP_METHODS = {
    "tos": "bilinear",
    "thetao": "bilinear",
    "so": "bilinear",
    "rsdo": "bilinear",
    "arag": "conservative",
    "no3": "conservative",
    "po4": "conservative",
}


def open_with_retries(file_path, engine="netcdf4", max_retries=10, delay=3):
    """
    Attempts to open a NetCDF file with retries to handle transient errors.

    Parameters:
        file_path (str): Path to the NetCDF file.
        engine (str): xarray engine to use for opening the file.
        max_retries (int): Maximum number of retries before raising an error.
        delay (int): Delay (in seconds) between retries.

    Returns:
        xarray.Dataset: Opened dataset.

    Raises:
        Exception: If the file cannot be opened after all retries.
    """
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
    """
    Check if a file is stable (i.e., not being written to).

    Parameters:
        file_path (Path): Path to the file to check.
        wait_time (int): Total time to wait for stability in seconds.
        check_interval (float): Interval between size checks in seconds.

    Returns:
        bool: True if the file is stable, False otherwise.
    """
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


def process_file(nc_fp, remap_template, max_depths, remap_dir, remap_method):
    """Function to process a single file."""
    try:
        nc_fp = Path(nc_fp)
        remap_dir = Path(remap_dir)
        output_file = remap_dir / nc_fp.name

        if output_file.exists():
            logger.warning(f"{output_file} already exists. Skipping...")
            return

        logger.info(f"Processing {nc_fp}")
        ds = open_with_retries(nc_fp, engine="netcdf4")

        # Extract top N depths if applicable: speeds up seafloor indexing
        depth_dim = (
            "depth" if "depth" in ds.dims else "lev" if "lev" in ds.dims else None
        )
        if depth_dim:
            ds = ds.isel({depth_dim: slice(0, max_depths)})

        # Remap using cdo
        remap_file = remap_dir / "remap_grid.txt"
        ds = utils.process_xa_d(utils.cdo_remap(ds, remap_file, remap_method))
        ds.to_netcdf(output_file)
        logger.info(f"\t\tSaved remapped file: {output_file}")
        ds.close()

    except Exception as e:
        logger.error(f"Error processing {nc_fp}: {e}")


class FileEventHandler(FileSystemEventHandler):
    def __init__(self, remap_template, max_depths, executor, max_workers=4):
        super().__init__()
        self.remap_template = remap_template
        self.max_depths = max_depths
        self.executor = executor

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".nc"):
            nc_fp = Path(event.src_path).resolve()
            remap_dir = nc_fp.parent / "remapped"

            # Skip processing if already in remap directory
            if "remapped" in nc_fp.parts:
                logger.info(f"Skipping already remapped file: {nc_fp}")
                return

            logger.info(f"Detected new file: {nc_fp}")

            # Ensure the file is stable before proceeding
            if not is_file_stable(nc_fp):
                logger.warning(f"File {nc_fp} is not stable. Skipping...")
                return
            else:
                logger.info(f"File {nc_fp} is stable.")

            # Determine the variable name from the directory structure
            variable = self.get_variable_name(nc_fp)
            if not variable:
                logger.warning(f"Variable not found in path: {nc_fp}")
                return

            # Get the remapping method for the variable
            remap_method = VARIABLE_REMAP_METHODS.get(
                variable, "bilinear"
            )  # Default to bilinear
            logger.info(f"Variable: {variable}, Remapping method: {remap_method}")

            remap_dir.mkdir(exist_ok=True)

            # Create remap grid text file
            remap_file = remap_dir / "remap_grid.txt"
            if not remap_file.exists():
                self.create_remap_textfile(remap_file)

            # Submit file processing task to the executor
            self.executor.submit(
                process_file,
                nc_fp,
                self.remap_template,
                self.max_depths,
                remap_dir,
                remap_method,
            )

    def get_variable_name(self, nc_fp):
        # Extract the variable name from the file name
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
    def __init__(self, parent_dir, remap_template, max_depths, max_workers=4):
        self.parent_dir = Path(parent_dir)
        self.remap_template = remap_template
        self.max_depths = max_depths
        self.executor = ProcessPoolExecutor(max_workers=max_workers)

    def run(self):
        event_handler = FileEventHandler(
            remap_template=self.remap_template,
            max_depths=self.max_depths,
            executor=self.executor,
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
        finally:
            self.executor.shutdown(wait=True)
        observer.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Watch a directory for NetCDF files and process them."
    )
    parser.add_argument(
        "parent_dir",
        help="The parent directory to watch for new .nc files.",
    )
    parser.add_argument(
        "--max_workers",
        type=int,
        default=4,
        help="Maximum number of workers for parallel processing.",
    )
    args = parser.parse_args()

    # Remapping grid configuration
    remap_template = {
        "xsize": 1440,
        "ysize": 720,
        "xfirst": -180,
        "xinc": 0.25,
        "yfirst": -90,
        "yinc": 0.25,
    }

    logger.info(f"Ready to accept files in {args.parent_dir}...")
    watcher = DirectoryWatcher(
        parent_dir=args.parent_dir,
        remap_template=remap_template,
        max_depths=20,
        max_workers=args.max_workers,
    )
    watcher.run()
