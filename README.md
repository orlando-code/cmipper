Welcome to `cmipper`, your one-stop shop for downloading, regridding, spatially cropping any CMIP6 data hosted on the Earth System Grid Federation's (ESGF) node!

This is an active project: walkthroughs and improved function documentation are on their way.

## What is CMIP?

The Coupled Model Intercomparison Project (CMIP) is an initiative coordinated by the World Climate Research Programme (WCRP) to improve our understanding of climate change by comparing the output of various climate models. It acts as a central point – and its nodes as repositories – for all the outputs of Earth System Models (ESMs) from academic and industrial organisations around the world. 

- **Purpose**: As the name suggests, CMIP exists to compare the performance of different climate models. It also seeks to identify commonalities and differences among these models to improve their accuracy and reliability.

- **Phases**: CMIP has iterated through several phases (CMIP1, CMIP2, CMIP3, CMIP5, CMIP6, etc.). Each phase tends to include more variables at higher spatio-temporal resolutions than the previous iteration. Data from CMIP6 is the most recent, and we won't see the [results of CMIP7 for another couple of years](https://wcrp-cmip.org/cmip7/).

- **Experiments**: Each phase of CMIP includes a set of standardized experiments which are performed by climate modeling groups around the world. These experiments typically involve historical simulations, future climate projections based on various standardised greenhouse gas emission scenarios, and idealized experiments to test specific aspects of the models.

- **Models**: CMIP involves coupled climate models which aim to simulate interactions between the atmosphere, oceans, land surface, and sea ice.

- **Scenarios**: Future climate projections in CMIP are based on different greenhouse gas emission scenarios or pathways, such as the Representative Concentration Pathways (RCPs) used in CMIP5 and the Shared Socioeconomic Pathways (SSPs) used in CMIP6. These scenarios help in understanding the potential climatic impacts of different levels of greenhouse gas emissions.

- **Applications**: As the gold-standard in terms of understanding global climate sensitivity of climate forecasts, CMIP data is widely used in climate research, most famously the assessment reports of the [Intergovernmental Panel on Climate Change (IPCC)](https://www.ipcc.ch/).

- **Data Availability**: CMIP data is publicly available and used by researchers and policymakers to study climate processes, evaluate model performance, and inform climate policy and adaptation strategies. This is where `cmipper` comes in!

## CMIP data storage
Needless to say, CMIP has created a colossal quantity of data over the years. Data from CMIP5 and CMIP6 is hosted by ESFG on various data nodes.

Happily, the powers that be have just overhauled the site which acts as a gateway to this data, [ESGF's Federated Nodes](https://aims2.llnl.gov/search). Unhappily, this still presents a lot of work to get your files where you want them, particularly since some data is still only downloadable via HTTPS. I hope you like wget bash scripts, for example...


## Welcome to `cmipper`! (Working title, obviously...)

`cmipper` goes above and beyond that provided by ESGF, saving you time, effort, and sleep. It allows you to specify:
- Institution ID e.g. EC-Earth-Consortium
- Source ID e.g. EC-Earth3-Veg
- Member ID e.g. r1i1p1f1
- Variable(s) e.g. mlotst
- Time scale e.g. 1950-2014
- Pressure levels e.g. surface, seafloor, single/range of pressure levels
- Geographic area e.g. 0ºS 10ºS 130ºE 170ºE

...after which you can sit back, relax, and have (only the necessary) data:
- Downloaded
- Regridded to ESGF:4326 if required
- Cropped to your region (with unncessary areas optionally deleted)
- Concatenated by time and variable (as specified).

This all happens in parallel on your local machine, which speeds things up no end (since local processing is not usually the bottleneck)!

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


## DISCLAIMER

`cmipper` is an ongoing project alongside other projects. Here is what's to come: but I can't guarantee when!
- Release as a package via [PyPI](https://pypi.org/)
- test functions added
- More data source information added to `model_info.yaml` file: although you're welcome to add this yourself for your required model(s)
- Dynamic progress of testing on a range of data nodes

## Contributing

With that in mind, if you'd be interested in using – or contributing to/helping maintain – `cmipper`, I'd love to hear from you. You can get in touch with me through my [website](https://orlando-code.github.io/).

