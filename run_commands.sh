#!/bin/bash

mkdir -p /maps/rt582/cmipper/logs/HadGEM3-GC31-MM/r1i1p1f3

python3 /maps/rt582/cmipper/cmipper/parallelised_download_and_process.py HadGEM3-GC31-MM r1i1p1f3 tos > /maps/rt582/cmipper/logs/HadGEM3-GC31-MM/r1i1p1f3/tos_download.log 2>&1 &
python3 /maps/rt582/cmipper/cmipper/parallelised_download_and_process.py HadGEM3-GC31-MM r1i1p1f3 wfo > /maps/rt582/cmipper/logs/HadGEM3-GC31-MM/r1i1p1f3/wfo_download.log 2>&1 &
python3 /maps/rt582/cmipper/cmipper/parallelised_download_and_process.py HadGEM3-GC31-MM r1i1p1f3 vo > /maps/rt582/cmipper/logs/HadGEM3-GC31-MM/r1i1p1f3/vo_download.log 2>&1 &
python3 /maps/rt582/cmipper/cmipper/parallelised_download_and_process.py HadGEM3-GC31-MM r1i1p1f3 so > /maps/rt582/cmipper/logs/HadGEM3-GC31-MM/r1i1p1f3/so_download.log 2>&1 &
python3 /maps/rt582/cmipper/cmipper/parallelised_download_and_process.py HadGEM3-GC31-MM r1i1p1f3 uo > /maps/rt582/cmipper/logs/HadGEM3-GC31-MM/r1i1p1f3/uo_download.log 2>&1 &
python3 /maps/rt582/cmipper/cmipper/parallelised_download_and_process.py HadGEM3-GC31-MM r1i1p1f3 mlotst > /maps/rt582/cmipper/logs/HadGEM3-GC31-MM/r1i1p1f3/mlotst_download.log 2>&1 &
python3 /maps/rt582/cmipper/cmipper/parallelised_download_and_process.py HadGEM3-GC31-MM r1i1p1f3 thetao > /maps/rt582/cmipper/logs/HadGEM3-GC31-MM/r1i1p1f3/thetao_download.log 2>&1 &
python3 /maps/rt582/cmipper/cmipper/parallelised_download_and_process.py HadGEM3-GC31-MM r1i1p1f3 rsdo > /maps/rt582/cmipper/logs/HadGEM3-GC31-MM/r1i1p1f3/rsdo_download.log 2>&1 &
python3 /maps/rt582/cmipper/cmipper/parallelised_download_and_process.py HadGEM3-GC31-MM r1i1p1f3 hfds > /maps/rt582/cmipper/logs/HadGEM3-GC31-MM/r1i1p1f3/hfds_download.log 2>&1 &
