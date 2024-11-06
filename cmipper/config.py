from pathlib import Path


def get_cmipper_module_dir():
    return Path(__file__).resolve().parent


def get_repo_dir():
    return get_cmipper_module_dir().parent


# Define global filepaths used throughout
################################################################################

REPO_DIR = get_repo_dir()
DATA_DIR = REPO_DIR / "data"
ESGPULL_DIR = REPO_DIR / ".esgpull"
ESGPULL_DATA_DIR = ESGPULL_DIR / "data"
LOGGING_DIR = REPO_DIR / "logs"
MODEL_INFO = REPO_DIR / "model_info.yaml"
DOWNLOAD_CONFIG = REPO_DIR / "download_config.yaml"
TEST_DATA_DIR = DATA_DIR / "test"
TMP_DIR = REPO_DIR / "tmp"

CMIP6_DATA_DIR = DATA_DIR / "env_vars" / "cmip6"

# TODO: automate creation of example figures and videos from downloads. But who has the time?
# figure_folder = "figures"
# video_folder = "videos"
