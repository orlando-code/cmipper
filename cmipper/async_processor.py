# general
import asyncio
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pathlib import Path
import yaml

# custom
from cmipper import processing

# Load configuration for data processing
with open('/maps/rt582/cmipper/tmp/data_processing.yaml', 'r') as file:
    data_processing_config = yaml.safe_load(file)

select_level = data_processing_config["select_level"]
do_regrid = data_processing_config["do_regrid"]
output_grid = data_processing_config["output_grid"]
remap_method = data_processing_config["remap_method"]

# Set up directories
raw_data_dir = Path('/maps/rt582/cmipper/.esgpull/data/')
processed_data_dir = Path('/maps/rt582/cmipper/data/test/')

# Function to handle file processing steps asynchronously
async def process_file(file_path):
    # Step 1: extract level and overwrite downloaded
    if select_level is not None:
        print(f"\n\t\tProcessing {file_path} for pressure level selection...")
        level_subset = processing.extract_dataset_level(file_path=file_path, select_level=select_level)
        
        # Handle permission issue by saving to a temporary file first, then moving it
        temp_path = file_path.with_suffix('.tmp')
        level_subset.to_netcdf(temp_path)
        temp_path.rename(file_path)  # Rename the temporary file to the original path

    # Step 2: regrid and save in processed_data_dir
    rel_path = file_path.relative_to(raw_data_dir)
    output_path = processed_data_dir / rel_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    if do_regrid:
        print(f"\n\t\tRegridding and saving to {output_path}...")
        regrid = processing.reproject_xa_d(xa_d=level_subset, ds_fp=file_path, output_grid=output_grid, remap_method=remap_method)
        regrid.to_netcdf(output_path)

# Event handler to trigger file processing on file creation
class DownloadHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.nc'):
            asyncio.run(process_file(Path(event.src_path)))


# Function to start the observer
def start_observer():
    event_handler = DownloadHandler()
    observer = Observer()
    observer.schedule(event_handler, path=raw_data_dir, recursive=True)
    observer.start()
    print("Observer started, monitoring for new files...")

    try:
        while True:
            asyncio.sleep(1)  # Keep the observer running
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    start_observer()