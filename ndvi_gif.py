import datetime as dt
import io
import math
import os
import tempfile

import matplotlib
import numpy as np

matplotlib.use("Agg")          
import matplotlib.pyplot as plt
import odc.stac
import planetary_computer
import pystac_client
from matplotlib.animation import FuncAnimation, PillowWriter


def create_gif(LON, LAT, BUFFER):
    delta_lat = BUFFER / 111.32
    delta_lon = BUFFER / (111.32 * math.cos(math.radians(LAT)))
    BBOX = [LON - delta_lon, LAT - delta_lat, LON + delta_lon, LAT + delta_lat]

    TODAY      = dt.date.today()
    START_DATE = TODAY - dt.timedelta(days=365)
    END_DATE   = TODAY
    MAX_CLOUD_COVER = 20.0
    RESOLUTION = 10

    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )
    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=BBOX,
        datetime=f"{START_DATE.isoformat()}/{END_DATE.isoformat()}",
        query={"eo:cloud_cover": {"lt": MAX_CLOUD_COVER}},
        sortby="+eo:cloud_cover",
    )
    items = list(search.items())
    if not items:
        # NOTE: don't use SystemExit in Streamlit — raise a real exception
        raise ValueError(
            "No scenes found. Try relaxing the cloud cover or date range."
        )

    ds = odc.stac.load(
        items,
        bands=["B04", "B08"],
        crs="EPSG:32617",
        resolution=RESOLUTION,
        bbox=BBOX,
        groupby="solar_day",
        chunks={"x": 2048, "y": 2048},
    )
    red = ds["B04"].astype("float32") / 10_000.0
    nir = ds["B08"].astype("float32") / 10_000.0
    ndvi = (nir - red) / (nir + red + 1e-8)

    ndvi_monthly = ndvi.resample(time="MS").median(skipna=True)
    ndvi_monthly = ndvi_monthly.compute()
    ndvi_monthly = ndvi_monthly.interpolate_na(dim="time", method="linear")

    ndvi_np = ndvi_monthly.values
    times   = ndvi_monthly.time.values

    x = ndvi_monthly.x.values
    y = ndvi_monthly.y.values
    extent = [float(x.min()), float(x.max()), float(y.min()), float(y.max())]
    VMIN, VMAX = -0.2, 0.8

    CMAP = plt.get_cmap("YlGn").copy()
    CMAP.set_bad(color="#d3d3d3")

    fig, ax = plt.subplots(figsize=(6, 6), dpi=90)
    ax.set_axis_off()
    im = ax.imshow(
        np.ma.masked_invalid(ndvi_np[0]),
        cmap=CMAP, vmin=VMIN, vmax=VMAX,
        extent=extent, origin="upper", interpolation="nearest",
    )
    fig.colorbar(im, ax=ax, shrink=0.8, label="NDVI")

    def update(i):
        im.set_data(np.ma.masked_invalid(ndvi_np[i]))
        ax.set_title(f"NDVI  |  {np.datetime_as_string(times[i], unit='M')}")
        return (im,)

    ani = FuncAnimation(fig, update, frames=len(times), blit=False)

    # >>> write to a temp file, then read it back into memory <<<
    fd, tmp_path = tempfile.mkstemp(suffix=".gif")
    os.close(fd)                      # Windows: must close before ani.save reopens it
    try:
        ani.save(tmp_path, writer=PillowWriter(fps=1))
        with open(tmp_path, "rb") as f:
            gif_bytes = f.read()
    finally:
        os.unlink(tmp_path)           # always clean up, even on error
        plt.close(fig)

    return gif_bytes, len(items)