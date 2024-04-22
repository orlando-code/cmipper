Welcome to `cmipper`, your one-stop (almost) shop for downloading, regridding, spatially cropping (those files get biiiiiig) any data produced as part of CMIP!

More information, function documentation, and walkthroughs coming soon. Watch this space!

## What is CMIP?
Some information and history about CMIP will go here. Perhaps a link to a longer blog post about its role in research and policy...

The Coupled Model Intercomparison Project (CMIP)...

## CMIP data storage
Needless to say, the CMIP has created a colossal quantity of data over the years. (insert fun quantification here). All this data is hosted on ESFG, which has various data nodes.

Schematic would be useful here.

Happily, the powers that be have just overhauled the site which acts as a gateway to this data, [ESGF's Federated Nodes](https://aims2.llnl.gov/search). Unhappily, this still presents a lot of work to get your files where you want them. I hope you like wget bash scripts, for example...

## Welcome to CMIPPER! (Working title, obviously...)

CMIPPER goes above and beyond that provided by ESGF, saving you time, effort, and sleep. Here's what it looks like:

Directory structure

Walk through each file



## Setting up the virtual environment
There aren't a great deal of required packages. The bare necessities are stored in the `requirements.txt` and `environment.yml` files for `pip` and `conda` users respectively. Read on to learn how to install them!


### Conda
```
conda env create --file environment.yml
```

### Pip
```
conda create --name <new_environment_name> --file requirements.txt
```

## Downloading your data
If a download process is interrupted, e.g. you want to change your download parameters, it's good to shut down the previous instance. This can be achieved through the following command in whatever terminal you're using: `pkill -9 -f <path_to_download_script.py>` (that'll be `pkill -9 -f cmipper cmipper/parallelised_download_and_process.py` if you haven't messed with the file structure).
