from pathlib import Path
import subprocess
import argparse


def create_remap_textfile(
    output_dir,
    xsize=1440,
    ysize=720,
    xfirst=-180,
    xinc=0.25,
    yfirst=-90,
    yinc=0.25,
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


def remap_to_grid(
    input_file: str | Path,
    remap_file: str | Path,
    remap_method: str,
    output_file: str,
    levels="1",
):  # 1/10
    """
    Use CDO remapycon to remap the input NetCDF file to a regular grid.
    """
    cmd = [
        "cdo",
        "-P",
        "128",
        f"{remap_method},{str(remap_file)}",
        f"-sellevidx,{levels}",  # select levels based on the provided parameter
        str(input_file),
        str(output_file),
    ]
    print(f"\tRemapping {input_file} -> {output_file}")
    try:
        subprocess.run(cmd, check=True)
        print(f"Remapped: {input_file} -> {output_file}")
    except subprocess.CalledProcessError as e:
        print(f"Error remapping {input_file}: {e}")


class NetCDFProcessingPipeline:
    def __init__(
        self,
        parent_dir: str | Path,
        max_depth: float = 100,
        depth_subsetting: str = "1",
        remap_method: str = "remapcon",
    ):
        """
        Initialize the pipeline with the parent directory containing subdirectories of .nc files.
        """
        self.parent_dir = Path(parent_dir)
        self.max_depth = max_depth
        self.depth_subsetting = depth_subsetting
        self.remap_method = remap_method

    def regrid_directory(self, subdirectory):
        """
        Process all .nc files in a single subdirectory.
        """
        subdirectory = Path(subdirectory)

        # Skip directories that already contain "remapped" in the path
        if (
            "remapped" in subdirectory.parts
            or "processed" in subdirectory.parts
            or "extracted_levs" in subdirectory.parts
        ):
            print(
                f"Skipping directory (filepath contains remapped/processed): {subdirectory}"
            )
            return

        # 2. Process each .nc file in the subdirectory
        nc_fps = list(subdirectory.glob("*.nc"))
        remap_dir_fp = subdirectory / "remapped"

        if len(nc_fps) == 0:
            print(f"No .nc files found in {subdirectory}")
            return
        else:
            remap_file = create_remap_textfile(subdirectory)

        print(f"\tRemapping {len(list(nc_fps))} files in {subdirectory}")
        print(f"\tRemapping {len(list(nc_fps))} files in {subdirectory}")
        for nc_fp in nc_fps:
            remap_dir_fp.mkdir(exist_ok=True)
            output_file = remap_dir_fp / nc_fp.name
            if output_file.exists():
                print(f"{output_file} already exists. Skipping...")
            else:
                # Extract top 20 depths if applicable
                # if "extracted_levs" not in subdirectory.parts:
                #     nc_fp = extract_top_20_depths(nc_fp)

                if not output_file.exists():
                    remap_to_grid(
                        input_file=nc_fp,
                        remap_file=remap_file,
                        remap_method=self.remap_method,
                        output_file=output_file,
                        levels=self.depth_subsetting,
                    )
                else:
                    print(f"{output_file} already exists. Skipping...")
                # unlink original
                nc_fp.unlink()

    # def do_level_extraction(self, subdirectory):  # TODO
    #     nc_fps = list(subdirectory.glob("*.nc"))
    #     # create remapped data directory
    #     processed_dir_fp = subdirectory / "processed"
    #     processed_dir_fp.mkdir(exist_ok=True)
    #     seafloor_indices = None
    #     for nc_fp in nc_fps:
    #         ds = xa.open_dataset(nc_fp).sel(depth_dim=slice(0, self.max_depth))
    #         depth_dim = (
    #             "depth" if "depth" in ds.dims else "lev" if "lev" in ds.dims else None
    #         )
    #         output_file = processed_dir_fp / nc_fp.name
    #         if any(processing.check_lev_exists(file_path) for file_path in [nc_fp]):
    #             print(
    #                 f"\tExtracting level value(s) from {nc_fp.stem}...",
    #                 flush=True,
    #             )

    #             variable_id = nc_fp.stem.split("_")[0]
    #             # open ds
    #             # get level dimension
    #             if variable_id in ds.variables:
    #                 if not seafloor_indices:  # only generate once per directory
    #                     seafloor_indices = processing.gen_seafloor_indices(
    #                         ds, variable_id, dim=depth_dim
    #                     )
    #                 ds = processing.extract_seafloor_vals_from_ds(
    #                     ds, variable_id, seafloor_indices
    #                 )
    #             else:
    #                 print(
    #                     f"\tVariable '{variable_id}' not found in {nc_fp.stem} | Skipping level extraction.",
    #                     flush=True,
    #                 )
    #         else:
    #             print(
    #                 f"\tNo 'depth' or 'lev' dimension found in {nc_fp} | Skipping level extraction."
    #             )
    #         print(f"Saving {nc_fp} -> {output_file}", flush=True)
    #         ds.to_netcdf(output_file)
    #         # unlink original
    #         nc_fp.unlink()

    def run(self):
        """
        Run the pipeline on all subdirectories of the parent directory.
        """
        subdirs = [d for d in self.parent_dir.rglob("*") if d.is_dir()] + [
            self.parent_dir
        ]
        for subdir in subdirs:
            print(f"Scanning directory: {subdir}")
            self.regrid_directory(subdir)
        # remapped_dirs = [
        #     d
        #     for d in self.parent_dir.rglob("*")
        #     if d.is_dir() and "remapped" in d.parts
        # ] + ([self.parent_dir] if "remapped" in self.parent_dir.parts else [])
        # for remapped_subdir in remapped_dirs:
        #     print(f"Scanning for level values in: {remapped_subdir}")
        #     self.do_level_extraction(subdir)


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
        default=128,
        help="Maximum number of workers for parallel processing.",
    )
    parser.add_argument(
        "--depth_subsetting",
        type=str,
        default="1",
        help="Depth subsetting for cdo remapping. int for single level, int/int for range.",
    )
    parser.add_argument(
        "--remap_method",
        type=str,
        default="remapcon",
        help="Remapping method for cdo remap. Default is remapcon. Alternatives are remapbil, remapnn, remapdis, remapcon2, remapbil2, remapnn2, remapdis2.",  # noqa
    )
    args = parser.parse_args()

    pipeline = NetCDFProcessingPipeline(args.parent_dir)
    pipeline.run()
