import os
import numpy as np

import time
import warnings
import xarray as xa
import argparse
from tqdm.auto import tqdm

from pathlib import Path
import re

from cdo import Cdo

from cmipper import config, utils, downloading, file_ops

"""
Script to download monthly-averaged CMIP6 climate simulation runs from the Earth
System Grid Federation (ESFG):
https://esgf-node.llnl.gov/search/cmip6/.
The simulations are regridded from latitude/longitude

The --source_id and --member_id command line inputs control which climate model
and model run to download.

The `model_dict` dictates which variables to download from each climate
model. Entries within the variable dictionaries of `variable_dict` provide
further specification for the variable to download - e.g. whether it is on an
ocean grid and whether to download data at a specified pressure level. All this
information is used to create the `query` dictionary that is passed to
downloading.esgf_search to find download links for the variable. The script loops
through and downloads each variable specified in the variable dictionary.

Variable files are saved to relevant folders beneath cmip6/<source_id>/<member_id>/
directory.

See download_cmip6_data_in_parallel.sh to download and regrid multiple climate
simulations in parallel using this script.
# TODO: add notebook option
"""


# Ignore "Missing CF-netCDF variable" warnings from download
warnings.simplefilter("ignore", UserWarning)


# Download function
################################################################################


def download_cmip_variable_data(
    source_id: str,
    member_id: str,
    variable_id: str,
):
    """
    This downloads a single variable, for however many experiments are specified in the source_id_dict.
    """
    # read download values
    source_id_dict = file_ops.read_yaml(config.model_info)
    download_config_processing_dict = file_ops.read_yaml(config.download_config)[source_id]["processing"]
    download_config_dict = file_ops.read_yaml(config.download_config)[source_id]

    # limit model info to that specified in download yaml
    source_id_dict = utils.limit_model_info_dict(source_id_dict, download_config_dict)[source_id]

    # TODO: parallelise by source_id and member_id
    variable_id_dict = source_id_dict["variable_dict"][variable_id]

    
    # processing values
    do_regrid = download_config_processing_dict["do_regrid"]
    do_save_og = download_config_processing_dict["do_save_og"]
    do_crop = download_config_processing_dict["do_crop"]
    do_regrid_on_fly = download_config_processing_dict["do_regrid_on_fly"]
    out_grid = download_config_processing_dict["remap_to"]
    remap_method = download_config_processing_dict["remap_method"]

    if do_crop:
        # spatial values
        LATS = sorted(download_config_processing_dict["lats"])
        LONS = sorted(download_config_processing_dict["lons"])
    # INT_LATS = [int(lat) for lat in LATS]   # TODO: remove these
    # INT_LONS = [int(lon) for lon in LONS]
    LEVS = sorted([abs(val) for val in download_config_processing_dict["levs"]])
    RESOLUTION = source_id_dict["resolution"]
    if do_crop and not do_regrid:
        print("WARNING: cropping without regridding may lead to unexpected results", flush=True)

    # file setting
    download_dir = (
        config.cmip6_data_dir / source_id / member_id
    )  # TODO: remove testing folder
    if not download_dir.exists():
        download_dir.mkdir(parents=True, exist_ok=True)

    tic = time.time()

    print(f"TIME CREATED: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(tic))}", flush=True)
    print(f"\nProcessing data for {source_id}, {member_id}, {variable_id}\n", flush=True)

    # BUILD QUERY   # TODO: wrap this up
    query = {
        "source_id": source_id,
        "member_id": member_id,
        "frequency": source_id_dict["frequency"],
        "variable_id": variable_id,
        "table_id": variable_id_dict["table_id"],
    }

    if (
        "ocean_variable" in variable_id_dict.keys()
    ):  # this originally included "or EC-Earth3" (lower-res version)
        # TODO: figure out what this is doing. May be redundant
        query["grid_label"] = "gr"
    else:
        query["grid_label"] = "gn"

    print("\n\n{}: ".format(variable_id), end="", flush=True)
    print("searching ESGF servers \n", end="", flush=True)
    results = []

    for experiment_id in source_id_dict["experiment_ids"]:
        query["experiment_id"] = experiment_id

        experiment_id_results = []
        node_results = []
        for data_node in source_id_dict["data_nodes"]:
            query["data_node"] = data_node
            # EXECUTE QUERY
            # experiment_id_results.extend(downloading.esgf_search(**query))
            node_results.append(downloading.esgf_search(**query))
            # Keep looping over possible data nodes until the experiment data is found – this isn't sufficient: some have more files than others, but may happen to have a few of the correct files floating around
            
        # select the node result with the most files
        results = node_results[node_results.index(max(node_results, key=len))]
        results = list(set(results))  # remove any duplicate values

            # if len(experiment_id_results) > 0:
            #     print("\nfound {}, ".format(experiment_id), end="", flush=True)
            #     results.extend(experiment_id_results)
            #     break  # Break out of the loop over data nodes when data found


        YEAR_RANGE = sorted(download_config_dict["experiment_ids"][experiment_id])
        print(YEAR_RANGE)
        # skip any unrequired dates
        relevant_results = file_ops.return_files_within_date_range(results, year_range=YEAR_RANGE)
        print(
            f"""found {len(results)} file(s) on {data_node} node of which {len(relevant_results)} fall(s) within required date range.""".format(
                end="", flush=True
            )
        )

        # SET UP FILE PATHS REFERENCING
        fpaths_og = {}
        fpaths_regridded = {}

        # plevels = (
        #     list(variable_id_dict["plevels"])
        #     if not isinstance(variable_id_dict["plevels"], list)
        #     else variable_id_dict["plevels"]
        # )
        plevels = variable_id_dict["plevels"]

        chunk_schema = "auto"
        # for plevel in plevels:  # TODO: this isn't really necessary, but need to check values list before removing
        # reset indices for each level
        seafloor_indices = None
        # TODO: not taking single (lowest)
        failed_regrids = []
        print("downloading individual files ", flush=True)
        ind_download_dir = download_dir / "og_grid" / variable_id
        if not ind_download_dir.exists():
            ind_download_dir.mkdir(parents=True, exist_ok=True)

        for i, result in enumerate(relevant_results):
            print("\n", result, flush=True)

            date_range = result.split("_")[-1].split(".")[0]

            ### LOADING/DONWLOADING FUNCTIONALITY
            fname_og = file_ops.FileName(
                variable_id=variable_id,
                grid_type="tripolar",  # TODO: get this info from the associated dataset
                fname_type="individual",
                levs=LEVS,
                date_range=date_range,
                plevels=plevels,
            ).construct_fname()
            og_save_fp = ind_download_dir / fname_og
            fpaths_og[i] = og_save_fp

            regrid_dir_fp = download_dir / "regridded" / variable_id
            if not regrid_dir_fp.exists():
                regrid_dir_fp.mkdir(parents=True, exist_ok=True)
            fname_regrid = file_ops.FileName(
                variable_id=variable_id,
                grid_type=out_grid,
                fname_type="individual",
                plevels=plevels,
                levs=LEVS,
                date_range=date_range,
            ).construct_fname()
            # add to list of regridded files
            fpaths_regridded[i] = regrid_dir_fp / fname_regrid

            # if raw downloaded file already exists, open it (for further processing)
            if og_save_fp.exists():
                print(f"\t{i}: existing file found at {og_save_fp}", flush=True)
                ds = xa.open_dataset(og_save_fp)
            # if we care about regridding
            if do_regrid:
                # and regridded file already exists, open it for potential further (non-regridding) processing
                if fpaths_regridded[i].exists():
                    print(
                        f"\t{i}: existing regridded file found at {fpaths_regridded[i]}", flush=True
                    )
                    ds = xa.open_dataset(fpaths_regridded[i])

            # if no file already exists, download from server file and select correct level(s)
            if not og_save_fp.exists() and not fpaths_regridded[i].exists():
                # if chunk_schema == "auto":
                # TRY TO DOWNLOAD, STARTING WITH AUTO AS DEFAULT
                if chunk_schema == "auto":
                    try:
                        ds = xa.open_dataset(
                            result, decode_times=True, chunks={"time": "499MB"}
                        )[variable_id]
                    except:
                        chunk_schema = "manual"
                        print("Dataset loading failed with auto chunking, switching to manual chunking...", flush=True)
                
                if not plevels:     # plevel = null: surface variable (chunk by time)
                    if chunk_schema == "manual":  # if didn't pass auto check will need to load manually
                        ds = xa.open_dataset(
                            result, decode_times=True, chunks={"time": 30} # TODO: adjust automatically if fails (changed down to 30 from 60)
                        )[variable_id]
                else:   # load chunks depending on auto or manual schema
                    ds = xa.open_dataset(
                            result,
                            decode_times=True,  # N.B. not all times easily decoded
                            # chunks={"i": "499MB"} if chunk_schema == "auto" else {"i": 180, "j": 180},
                            chunks = {"time": 5, "i": 360, "j": 360}
                        ).isel(lev=slice(min(LEVS), max(LEVS)))

                    # EXTRACT CORRECT PRESSURE LEVEL FROM DS
                    if plevels == -1:  # plevel == -1: seafloor
                        ds, seafloor_indices = utils.extract_seafloor_vals(ds, variable_id, seafloor_indices)
                    elif isinstance(plevels, tuple):    # plevel == list[float]: multiple pressure levels
                        print(f"extracting {min(plevels) / 100:.03f} to {max(plevels) / 100:.03f} hPa", flush=True)
                        ds = ds.sel(lev=slice(min(plevels), max(plevels)))[variable_id]
                    elif isinstance(plevels, list):    # plevel == list[float]: multiple pressure levels                                
                        plevels_strs = [f"{p / 100:.03f}" for p in plevels]
                        print(f"extracting {plevels_strs} hPa pressure levels", flush=True)
                        ds = ds.sel(plevels)[variable_id]
                    elif isinstance(plevels, float):    # plevel == float: single pressure levelß
                        print(f"extracting {plevels / 100:.03f} hPa", flush=True)
                        ds = ds.sel(lev=plevels)[variable_id]
                    else:
                        raise ValueError("plevels must be null (indicating seafloor variable), a list of floats, a float, or -1 (indicating seafloor variable)")

                #     # DOWNLOAD DS
                #     if not plevels:  # plevel = null: surface variable (chunk by time)
                #         try:
                #             ds = xa.open_dataset(
                #                 result, decode_times=True, chunks={"time": "499MB"}
                #             )[variable_id]
                #         except NotImplementedError:
                #             chunk_schema = "manual"
                #             print("Loading failed, switching to manual chunking")

                #     else:  # plevel != null: specific or multiple pressure levels, or seafloor (chunk by space)

                #         try:
                #             ds = xa.open_dataset(
                #                 result,
                #                 decode_times=True,  # not all times easily decoded
                #                 chunks={"i": "499MB"},
                #             ).isel(lev=slice(min(LEVS), max(LEVS)))
                #             continue
                #         except NotImplementedError:
                #             chunk_schema = "manual"
                #             print("Loading failed, switching to manual chunking")


                # if chunk_schema == "manual":
                #     # DOWNLOAD DS
                #     if not plevels:  # plevel = null: surface variable (chunk by time)
                #         try:
                #             ds = xa.open_dataset(
                #                 result, decode_times=True, chunks={"time": 100} # TODO: optimise this chunking (altho seems pretty good already)
                #             )[variable_id]
                #             continue
                #         except NotImplementedError:
                #             print("Loading failed with manual chunking. See further error.")
                #     else:  # plevel != null: specific or multiple pressure levels, or seafloor (chunk by space)
                #         try:
                #             ds = xa.open_dataset(
                #                 result,
                #                 decode_times=True,  # not all times easily decoded
                #                 chunks={"i": 180},
                #             ).isel(lev=slice(min(LEVS), max(LEVS)))
                #         except NotImplementedError:
                #             chunk_schema = "manual"
                #             print("Loading failed with manual chunking. See further error.")


            if not og_save_fp.exists() and do_save_og: 
                print(f"\t{i}: saving {fname_og} file: {og_save_fp}", flush=True)
                fpaths_og[i] = og_save_fp
                # TODO: change dtype?
                ds.to_netcdf(og_save_fp)

            ### PROCESSING FUNCTIONALITY
            if do_regrid:
                # if regridded file does not exist, regrid
                if not fpaths_regridded[i].exists():
                    remap_template_fp = (
                        config.cmip6_data_dir
                        / source_id
                        / f"{source_id}_remap_template.txt"
                    )
                    # generate remap file if necessary
                    remap_template_fp = utils.return_remap_template(input_file=ds, remap_template_fp=remap_template_fp, out_grid=out_grid)
                    
                    print(f"\t{i}: regridding to {fpaths_regridded[i]}", flush=True)
                    try:
                        # remap via cdo
                        ds = utils.cdo_remap(ds, remap_template_fp=remap_template_fp, remap_method=remap_method)
                        # save to nc # TODO: is there a way to parallelise this further?
                        print(f"\t{i}: saving regridded file to: {fpaths_regridded[i]}", flush=True)
                        utils.process_xa_d(ds).to_netcdf(fpaths_regridded[i])
                    except: # noqa # TODO: find proper exception
                        print(
                            f"regridding failed for {fpaths_og[i]}, skipping",
                            flush=True,
                        )
                        failed_regrids.append(fpaths_og[i])
                        continue

                # if do_delete_og:
                #     print(fpaths_og[i])
                #     os.remove(fpaths_og[i])

            if do_crop: # TODO: this should become unnecessary with dask processing?
                cropped_dir_name = f"cropped_{utils.lat_lon_string_from_tuples(LATS, LONS).upper()}"
                cropped_dir_fp = (
                    download_dir / "regridded" / cropped_dir_name / variable_id
                )
                if not cropped_dir_fp.exists():
                    cropped_dir_fp.mkdir(parents=True, exist_ok=True)

                fname_cropped = file_ops.FileName(
                    variable_id=variable_id,
                    grid_type="latlon",
                    fname_type="individual",
                    lats=LATS,
                    lons=LONS,
                    levs=LEVS,
                    plevels=plevels,
                    date_range=date_range,
                ).construct_fname()

                cropped_save_fp = cropped_dir_fp / fname_cropped
                if not cropped_save_fp.exists():
                    # N.B. may be different between models, and may need to include levs
                    ds = utils.process_xa_d(ds).sel(
                        latitude=slice(min(LATS), max(LATS)),
                        longitude=slice(min(LONS), max(LONS)),
                    )
                    print(
                        f"\t{i}: saving {fname_cropped} file: {cropped_save_fp}",
                        flush=True,
                    )
                    # TODO: change dtype?
                    ds.to_netcdf(cropped_save_fp)
                else:
                    print(
                        f"\t{i}: skipping cropping due to existing file: {cropped_save_fp}",
                        flush=True,
                    )

        download_tic = time.time() - tic
        actions_undertaken = [
            action
            for action, flag in [("regridding", do_regrid), ("cropping", do_crop)]
            if flag
        ]
        message = (
            f"Searching/downloading/{'/'.join(actions_undertaken)}"
            if actions_undertaken
            else "Searching/downloading"
        )
        print(
            f"\n{message} took {np.floor(download_tic / 60):.0f}m:{download_tic % 60:.0f}s.", flush=True
        )

        print(
            f"\n{len(failed_regrids)} regrid(s) failed.\n"
            if len(failed_regrids) == 0
            else f"\n{len(failed_regrids)} regrid(s) failed. The following are/is likely corrupted: \n"
            + "\n".join(str(item) for item in list(set(failed_regrids)))
            + "\n", flush=True
        )


# Processing (concatenation by time, merging by variables) functions
################################################################################


def concat_cmip_files_by_time(source_id, year_range, member_id, fp_dir: Path | str = None, download_config_dict: dict = None):
    download_dir = (
        config.cmip6_data_dir / source_id / member_id
    )  if fp_dir is None else Path(fp_dir)
    source_id_dict = file_ops.read_yaml(config.model_info)[source_id]
    download_config_dict = file_ops.read_yaml(config.download_config)[source_id] if download_config_dict is None else download_config_dict
    download_config_processing_dict = file_ops.read_yaml(config.download_config)["processing"]


    # limit model info to that specified in download yaml
    source_id_dict = utils.limit_model_info_dict(source_id_dict, download_config_dict)


    DO_CROP = download_config_dict["processing"]["do_crop"]
    LATS = sorted(download_config_dict["lats"])
    LONS = sorted(download_config_dict["lons"])
    # INT_LATS = [int(lat) for lat in LATS]
    # INT_LONS = [int(lon) for lon in LONS]
    LEVS = sorted([abs(val) for val in download_config_dict["levs"]])
    YEAR_RANGE = sorted(year_range)  # TODO: include months option
    # YEAR_RANGE = download_config_dict["experiment_ids"][experiment_id]

    # CONCATENATE BY TIME
    tic = time.time()

    conc_var_dir = download_dir / "regridded" / "concatted_vars"
    if DO_CROP:
        conc_var_dir = Path(
            str(conc_var_dir)
            + f"_{utils.lat_lon_string_from_tuples(LATS, LONS).upper()}"
        )
    if not conc_var_dir.exists():
        conc_var_dir.mkdir(parents=True, exist_ok=True)

    num_concatted = 0
    # fetch variable_id to fetch all files to be concatted
    # for variable_id in list(download_config_dict["variable_ids"].keys()):   
    for variable_id in download_config_dict["env_vars"]:   # ham-fisted approach to allowing overwrite with config_info
        if DO_CROP:
            variable_dir = (
                download_dir
                / "regridded"
                / f"cropped_{utils.lat_lon_string_from_tuples(LATS, LONS).upper()}"
                / variable_id
            )
        else:
            # directory with individual files for single variable
            variable_dir = download_dir / "regridded" / variable_id
            print("variable_dir", variable_dir, flush=True)

        # if not variable_dir.exists():
        #     print(f"{variable_dir} does not exist, skipping", flush=True)
        #     continue

        fps = list(variable_dir.glob("*.nc"))
        if not DO_CROP:
            # if not cropping, determine spatial extent of files (first should be representative of them all: otherwise
            # we have bigger problems)
            min_lat, max_lat, min_lon, max_lon = file_ops.get_min_max_coords_from_xa_d(xa.open_dataset(fps[0]))
            LATS = [min_lat, max_lat]
            LONS = [min_lon, max_lon]
            # print(LATS, LONS)

        # cast year integers to strings encompassing their months
        if YEAR_RANGE:
            oldest_date = str(min(YEAR_RANGE)) + "00"
            newest_date = str(max(YEAR_RANGE) - 1) + "12"
        else:
            oldest_file = min(
                fps, key=lambda filename: int(re.findall(r"\d{4}", str(filename))[0])
            )
            newest_file = max(
                fps, key=lambda filename: int(re.findall(r"\d{4}", str(filename))[0])
            )
            oldest_date = str(oldest_file.name).split("_")[-1].split("-")[0]
            newest_date = (
                str(newest_file.name).split("_")[-1].split("-")[1].split(".")[0]
            )

        # construct name of time-concattenated file
        fname = file_ops.FileName(
            variable_id=variable_id,
            grid_type="latlon",
            fname_type="time_concatted",
            lats=LATS,
            lons=LONS,
            levs=LEVS,
            plevels=source_id_dict["variable_dict"][variable_id]["plevels"],
            date_range=[oldest_date, newest_date],
        ).construct_fname()
        concatted_fp = conc_var_dir / fname

        if concatted_fp.exists():
            print(
                f"\nconcatenated file already exists at {str(concatted_fp)}", flush=True
            )
        else:
            # fetch all the filepaths of the files containing dates between oldest_date and newest_date
            fps_within_date = [
                fp
                for fp in fps
                if oldest_date <= str(fp.name).split("_")[-1].split("-")[0]
                and newest_date
                >= str(fp.name).split("_")[-1].split("-")[1].split(".")[0]
            ]

            if len(fps_within_date) == 0:
                print(
                    f"skipping '{variable_id}' since no files found between {oldest_date} and {newest_date}", flush=True
                )
                # continue
            else:
                if len(fps_within_date) == (YEAR_RANGE[1] - YEAR_RANGE[0]):
                    print(
                        f"\nAll {len(fps_within_date)} expected files found for '{variable_id}' between {oldest_date} and {newest_date} ",  # noqa
                        flush=True,
                    )
                else:
                    print(
                        f"\n{len(fps_within_date)} files found for '{variable_id}' between "
                        f"{oldest_date} and {newest_date} Is this expected, or are there files missing?",
                        flush=True,
                    )

                print(f"concatenating '{variable_id}' files by time ", flush=True)

                concatted = xa.open_mfdataset(fps_within_date)

                # decode time
                concatted = concatted.convert_calendar(
                    "gregorian", dim="time"
                )  # may not be universal for all models
                print(
                    f"saving concatenated file to {concatted_fp} ",
                    flush=True,
                )
                concatted.to_netcdf(concatted_fp)
                num_concatted += 1

    time_concat_tic = time.time() - tic
    print(
        f"\nConcatenating {num_concatted} sets of variable files by time took "
        f"{np.floor(time_concat_tic / 60):.0f}m:{time_concat_tic % 60:.0f}s.\n", flush=True
    )


def merge_cmip_data_by_variables(source_id, year_range, member_id, fp_dir: Path| str=None, download_config_dict=None):
    download_dir = config.cmip6_data_dir / source_id / member_id / "regridded" if fp_dir is None else Path(fp_dir)
    # source_id_dict = file_ops.read_yaml(config.model_info)[source_id]
    download_config_dict = file_ops.read_yaml(config.download_config) if download_config_dict is None else download_config_dict

    DO_CROP = download_config_dict["processing"]["do_crop"]
    LATS = sorted(download_config_dict["lats"])
    LONS = sorted(download_config_dict["lons"])
    # INT_LATS = [int(lat) for lat in LATS]
    # INT_LONS = [int(lon) for lon in LONS]
    LEVS = sorted([abs(val) for val in download_config_dict["levs"]])
    YEAR_RANGE = sorted(year_range)  # TODO: include months option

    # YEAR_RANGE = download_config_dict["experiment_ids"][experiment_id]

    tic = time.time()

    # MERGE VARIABLES
    conc_var_dir = download_dir / "concatted_vars"  # TODO: should I write to this folder or the one above? Don't want it 
    # getting mixed up with the other individual variable files
    if DO_CROP:
        conc_var_dir = Path(
            str(conc_var_dir)
            + (f"_{utils.lat_lon_string_from_tuples(LATS, LONS).upper()}")
        )

    if not Path(conc_var_dir).exists():
        conc_var_dir.mkdir(parents=True, exist_ok=True)

    # select all files in conc_var_dir which have correct YEAR_RANGE
    oldest_date = str(min(YEAR_RANGE)) + "00"
    newest_date = str(max(YEAR_RANGE) - 1) + "12"
    YEAR_RANGE_str = f"{oldest_date}-{newest_date}"
    nc_fps = list(Path(conc_var_dir).glob(f"*{YEAR_RANGE_str}.nc"))
    var_nc_fps = [fp for fp in nc_fps if any(var in str(fp) for var in download_config_dict["env_vars"])]
    variables = [str(fname.name).split("_")[0] for fname in var_nc_fps]
    # sort variables in alphabetical for consistency between files
    variables.sort()

    print(var_nc_fps[0])
    print(xa.open_dataset(var_nc_fps[0]))

    if not DO_CROP:
        # if not cropping, determine spatial extent of files (first should be representative of them all: otherwise
        # we have bigger problems)
        min_lat, max_lat, min_lon, max_lon = file_ops.get_min_max_coords_from_xa_d(xa.open_dataset(var_nc_fps[0]))
        LATS = [min_lat, max_lat]
        LONS = [min_lon, max_lon]

    merged_fname = file_ops.FileName(
        variable_id=variables,
        grid_type="latlon",
        fname_type="var_concatted",
        lats=LATS,
        lons=LONS,
        levs=LEVS,
        plevels=LEVS,  # TODO: Hmm? What's going on here?
        date_range=[oldest_date, newest_date],
    ).construct_fname()

    # merged_fp = download_dir / merged_fname
    merged_fp = conc_var_dir / merged_fname
    if not merged_fp.exists():
        print(
            f"\nmerging variable files and saving to {merged_fp} ",
            flush=True,
        )
        dss = [xa.open_dataset(fp) for fp in var_nc_fps]
        merged = utils.process_xa_d(xa.merge(dss))
        merged.to_netcdf(merged_fp)

        var_concat_tic = time.time() - tic
        print(
            f"\nMerging files by variable took {np.floor(var_concat_tic / 60):.0f}m:{var_concat_tic % 60:.0f}s.", flush=True
        )
    else:
        print(
            f"\nmerged file already exists at {merged_fp}",
            flush=True,
        )


def delete_corrupt_files(source_id, member_id):
    """Some files may fail to regrid, usually due to partial download. This function attempts to remap
    the file to some arbitrary path and deletes any files which fail.

    TODO: any way to speed this up?
    TODO: should also (or another function) attempt to open final files and check if errors are thrown
    TODO: if a regridded file has all time values the same, delete it. Can happen through faulty download
    """
    download_dir = config.cmip6_data_dir / source_id / member_id
    og_grid_dir = download_dir / "og_grid"
    # regrid_dir = download_dir / "regridded" / "umo"

    var_dirs = [entry for entry in og_grid_dir.iterdir() if entry.is_dir()]
    # var_dirs = [og_grid_dir]

    corrupt = []
    legit = []
    for variable_dir in tqdm(var_dirs, total=len(var_dirs)):
        nc_fps = list(variable_dir.glob("*.nc"))
        # check file opens
        for nc_fp in tqdm(
            nc_fps,
            total=len(nc_fps),
            desc=f"Checking for corrupt files in {variable_dir.name} directory",
        ):
            if utils.does_nc_open(nc_fp):
                legit.append(nc_fp)
            else:
                corrupt.append(nc_fp)
                print(f"file {nc_fp} does not open. Removing...", flush=True)
                os.remove(nc_fp)

    # check for and remove duplicate time values
    for nc_fp in tqdm(
        legit,
        desc="Checking for duplicate time values indicating download failure",
    ):
        if utils.does_nc_have_duplicate_coords(nc_fp):
            corrupt.append(nc_fp)
            print(f"file {nc_fp} has duplicated coordinate values. Removing...", flush=True)
            os.remove(nc_fp)

    if len(corrupt) > 0:
        print(f"\n\n{len(corrupt)} corrupt files found and removed:\n", flush=True)
        print("It is recommended to re-run the download process.", flush=True)


def process_cmip6_data(source_id, year_range, member_id):
    tic = time.time()
    print(f"TIME CREATED: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(tic))}", flush=True)

    concat_cmip_files_by_time(source_id, year_range, member_id)
    merge_cmip_data_by_variables(source_id, year_range, member_id)

    dur = time.time() - tic
    print(f"\n\nTOTAL DURATION: {np.floor(dur / 60):.0f}m:{dur % 60:.0f}s\n", flush=True)


def main(
    source_id: str = "EC-Earth3P-HR",
    member_id: str = "r1i1p1f1",    # TODO: not really necessary
    variable_id: str = "tos",
):
    download_cmip_variable_data(
        source_id=source_id, member_id=member_id, variable_id=variable_id
    )
    # TODO: add processing


def generate_bash_commands(source_id_dict: dict = None, download_config_dict: dict = None):
    log_dir = config.logging_dir
    script = "/maps/rt582/cmipper/cmipper/parallelised_download_and_process.py" # TODO make this agnostic of the d

    source_id_dict = file_ops.read_yaml(config.model_info) if source_id_dict is None else source_id_dict
    download_config_dict = file_ops.read_yaml(config.download_config) if download_config_dict is None else download_config_dict

    commands = []
    mkdirs = []
    source_ids = source_id_dict.keys()
        # lim_source_id_dict = utils.limit_model_info_dict(source_id_dict, download_config_dict)
    lim_source_id_dict = utils.extract_matching_subsets(download_config_dict, source_id_dict)
    for source_id in lim_source_id_dict.keys():

        member_ids = lim_source_id_dict[source_id]["member_ids"]
        for member_id in member_ids:
            dl_log_dir = f"{log_dir}/{source_id}/{member_id}"
            mkdirs.append(f"mkdir -p {dl_log_dir}")
            variable_ids = lim_source_id_dict[source_id]["variable_dict"]
            for variable_id in variable_ids:
                log_fn = f"{variable_id}_download.log"
                log_fp = f"{dl_log_dir}/{log_fn}"
                # command = f"python3 {script} --source_id {source_id} --variable_id {variable_id} --member_id {member_id} > {log_fp} 2>&1 &"
                command = f"python3 {script} {source_id} {member_id} {variable_id} > {log_fp} 2>&1 &"
                commands.append(command)

    # Write commands to a bash script
    with open('run_commands.sh', 'w') as file:

        file.write("#!/bin/bash\n\n")
        # file.write(f"mkdir -p {log_dir}\n\n")
        for mkdir in mkdirs:
            file.write(mkdir + "\n")
        file.write("\n")
        for command in commands:
            file.write(command + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download data from CMIP source/member"
    )
    parser.add_argument(
        "source_id", help="Specify CMIP source ID", default="EC-Earth3P-HR"
    )
    parser.add_argument("member_id", help="Specify CMIP member ID", default="r1i1p2f1")
    parser.add_argument("variable_id", help="Specify CMIP variable ID", default="tos")

    args = parser.parse_args()
    print(args.source_id)
    # main(
    #     source_id=args.model_code,
    #     member_id=args.config_fp,
    #     variable_id=args.variable_id,
    # )
    main(
        source_id=args.source_id,
        member_id=args.member_id,
        variable_id=args.variable_id,
    )

# def main():

#     # COMMAND LINE INPUT FROM BASH SCRIPT
#     # ################################################################################
#     parser = argparse.ArgumentParser()

#     # model info
#     source_id = parser.add_argument("--source_id", default="EC-Earth3P-HR", type=str)
#     member_id = parser.add_argument("--member_id", default="r1i1p2f1", type=str)
#     variable_id = parser.add_argument("--variable_id", default="tos", type=str)
#     # TODO: year range as a command line argument
#     # experiment_id = parser.add_argument(
#     #     "--experiment_id", default="hist-1950", type=str
#     # )
#     command = parser.add_argument("--command", default="download", type=str)

#     commandline_args = parser.parse_args()

#     source_id = commandline_args.source_id
#     member_id = commandline_args.member_id
#     variable_id = commandline_args.variable_id
#     # experiment_id = commandline_args.experiment_id
#     command = commandline_args.command
#     # command = "process"
#     # # command = "delete_corrupt_files"
#     # source_id = "EC-Earth3P-HR"
#     # # experiment_id = "hist-1950"
#     year_range = [1950, 2050]
#     # member_id = "r1i1p2f1"
#     # variable_id = "tos"

#     # TODO: refine download/process using limited dict
#     # DOWNLOAD DATA
#     ################################################################################
#     if command == "download":
#         download_cmip_variable_data(source_id, member_id, variable_id)
#     # TODO: do I want to separate these out into different functions/scripts?
#     elif command == "delete_corrupt_files":
#         delete_corrupt_files(source_id, member_id)
#     elif command == "process":
#         process_cmip6_data(source_id, year_range, member_id)


# if __name__ == "__main__":
#     main()
