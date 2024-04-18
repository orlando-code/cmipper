import importlib
import inspect
from pathlib import Path
import os


def get_cmipper_module_dir():
    cmipper_module = importlib.import_module("cmipper")
    cmipper_dir = Path(inspect.getabsfile(cmipper_module)).parent
    return (cmipper_dir / "..").resolve()


"""
Defines globals used throughout the codebase.
"""

###############################################################################
# Folder structure naming system
###############################################################################

data_folder = "data"

cmip6_data_folder = os.path.join(data_folder, "env_vars", "cmip6")
static_cmip6_data_folder = os.path.join(
    cmip6_data_folder, "EC-Earth3P-HR/r1i1p2f1_latlon"
)

# figure_folder = "figures"
# video_folder = "videos"
