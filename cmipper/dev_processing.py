from pathlib import Path
import xarray as xa

# import subprocess

# import glob
# from tempfile import TemporaryDirectory
import argparse

from cmipper import utils, processing
from concurrent.futures import ProcessPoolExecutor

N = 10
# TODO: parallelise this, especially regridding


def create_remap_textfile(
    output_dir,
    xsize=1440,
    ysize=720,
    xfirst=-180,
    xinc=0.25,
    yfirst=-90,
    yinc=0.25,
    # output_dir,
    # xsize=360,
    # ysize=180,
    # xfirst=-179.5,
    # xinc=1.0,
    # yfirst=-89.5,
    # yinc=1.0,
):
    """
    Create a remap grid description file for CDO.
    """
    remap_file = Path(output_dir) / "remap_grid.txt"
    with remap_file.open("w") as f:
        f.write("gridtype = lonlat\n")
        f.write(f"xsize = {xsize}\n")
        f.write(f"ysize = {ysize}\n")
        f.write(f"xfirst = {xfirst}\n")
        f.write(f"xinc = {xinc}\n")
        f.write(f"yfirst = {yfirst}\n")
        f.write(f"yinc = {yinc}\n")
    return remap_file


def extract_top_n_depths(nc_fp, n: int = 20):
    """
    Extract the top n depths from a NetCDF file and overwrite it.
    """
    ds = xa.open_dataset(nc_fp)
    depth_dim = "depth" if "depth" in ds.dims else "lev" if "lev" in ds.dims else None

    if depth_dim:
        ds = ds.isel({depth_dim: slice(0, n)})

        return ds
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
        return ds


# def remapycon_to_grid(input_file, remap_file, output_file):
#     """
#     Use CDO remapycon to remap the input NetCDF file to a regular grid.
#     """
#     cmd = ["cdo", f"remapycon,{remap_file}", input_file, output_file]
#     print(f"\tRemapping {input_file} -> {output_file}")
#     try:
#         subprocess.run(cmd, check=True)
#         print(f"Remapped: {input_file} -> {output_file}")
#     except subprocess.CalledProcessError as e:
#         print(f"Error remapping {input_file}: {e}")


class NetCDFProcessingPipeline:
    def __init__(self, parent_dir):
        """
        Initialize the pipeline with the parent directory containing subdirectories of .nc files.
        """
        self.parent_dir = Path(parent_dir)

    def process_directory(self, subdirectory):
        """
        Process all .nc files in a single subdirectory.
        """
        subdirectory = Path(subdirectory)
        nc_fps = list(subdirectory.glob("*.nc"))

        # Create the remap text file if necessary
        if len(nc_fps) > 0:
            remap_file = create_remap_textfile(subdirectory)
        else:
            print(f"No .nc files found in {subdirectory} | Skipping directory.")
            return

        if "remapped" not in subdirectory.parts:  # don't remap remapped files
            remap_dir_fp = subdirectory / "remapped"
            remap_dir_fp.mkdir(exist_ok=True)
            print(f"\tRemapping files in {subdirectory}")

            with ProcessPoolExecutor() as executor:
                futures = [
                    executor.submit(self.process_file, nc_fp, remap_file, remap_dir_fp)
                    for nc_fp in nc_fps
                ]
                for future in futures:
                    try:
                        future.result()
                    except Exception as e:
                        print(f"Error processing file: {e}")
        else:
            print(f"Files in {subdirectory} already remapped. Skipping...")

    def process_file(self, nc_fp, remap_file, remap_dir_fp):
        """
        Process a single .nc file.
        """
        try:
            output_file = remap_dir_fp / nc_fp.name
            if output_file.exists():
                print(f"{output_file} already exists. Skipping...")
            else:
                if "extracted_levs" not in nc_fp.parts:
                    print(f"Extracting levels from {nc_fp}")
                    ds = extract_top_n_depths(nc_fp, n=N)

                if not output_file.exists():
                    print(f"Remapping {nc_fp} -> {output_file}")
                    ds = utils.cdo_remap(ds, remap_file, "conservative")
                    # select desired level(s)

                    if any(
                        processing.check_lev_exists(file_path) for file_path in [nc_fp]
                    ):
                        print(
                            f"\tExtracting level value(s) from {nc_fp.stem}...",
                            flush=True,
                        )
                        variable_id = nc_fp.stem.split("_")[0]

                        if variable_id in ds.variables:
                            seafloor_indices = processing.gen_seafloor_indices(
                                ds, variable_id, "depth"
                            )
                            extracted_ds = processing.extract_seafloor_vals_from_ds(
                                ds, variable_id, seafloor_indices
                            )
                            ds.close()
                            ds = extracted_ds
                    ("Saving to", output_file)
                    ds.to_netcdf(output_file)
                else:
                    print(f"{output_file} already exists. Skipping...")
        except Exception as e:
            print(f"Error processing {nc_fp}: {e}")

    def run(self):
        """
        Run the pipeline on all subdirectories of the parent directory.
        """
        subdirs = [self.parent_dir] + [
            d for d in self.parent_dir.rglob("*") if d.is_dir()
        ]
        for subdir in subdirs:
            print(f"\t\tScanning directory: {subdir}")
            self.process_directory(subdir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process NetCDF files in a directory.")
    parser.add_argument(
        "parent_dir",
        nargs="?",
        default="/maps/rt582/cmipper/.esgpull/data/CMIP6/CMIP/AWI/AWI-CM-1-1-MR/historical/r2i1p1f1",
        help="The parent directory containing subdirectories of .nc files.",
    )
    args = parser.parse_args()

    pipeline = NetCDFProcessingPipeline(args.parent_dir)
    pipeline.run()
