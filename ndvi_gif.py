import datetime as dt
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import odc.stac
import planetary_computer
import pystac_client
import rioxarray
import xarray as xr
from matplotlib.animation import FuncAnimation, PillowWriter
from rioxarray.exceptions import MissingCRS


def create_gif(LON, LAT, BUFFER):
    # function to create bounding box
    # def create_bbox(lon, lat, buffer_km):
    #     """
    #     Creates a bounding box from a center point and a buffer distance in km.
    #     Note: Uses a flat-earth approximation, which is fine for small/medium regions.
    #     """
    #     # 1 degree of latitude is approximately 111.32 km everywhere
    #     delta_lat = buffer_km / 111.32
        
    #     # 1 degree of longitude shrinks as you move away from the equator
    #     delta_lon = buffer_km / (111.32 * math.cos(math.radians(lat)))
        
    #     min_lon = lon - delta_lon
    #     max_lon = lon + delta_lon
    #     min_lat = lat - delta_lat
    #     max_lat = lat + delta_lat
        
    #     return [min_lon, min_lat, max_lon, max_lat]

    # Example usage:
    # bbox = bbox_from_center(-83.22, 42.60, buffer_km=10) # 10km radius

    # teesting values
    # LON = -83.22
    # LAT = 42.6
    # BUFFER = 5

    delta_lat = BUFFER / 111.32
    delta_lon = BUFFER / (111.32 * math.cos(math.radians(LAT)))

    # BBOX = create_bbox(LON,LAT,BUFFER)

    BBOX = [LON - delta_lon, LAT - delta_lat, LON + delta_lon, LAT + delta_lat]

    # Use the past year (from today back 365 days).
    TODAY = dt.date.today()
    START_DATE = TODAY - dt.timedelta(days=365)
    END_DATE = TODAY

    # Optional: limit to scenes with less than, say, 20% cloud cover.
    MAX_CLOUD_COVER = 20.0

    # resolution in meters
    RESOLUTION = 10

    # opening connection
    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,  # adds SAS tokens automatically
    )

    # search over time period
    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=BBOX,
        datetime=f"{START_DATE.isoformat()}/{END_DATE.isoformat()}",
        query={"eo:cloud_cover": {"lt": MAX_CLOUD_COVER}},
        sortby="+eo:cloud_cover",  # least cloudy first
    )

    items = list(search.items())
    print(f"Found {len(items)} scenes between {START_DATE} and {END_DATE}.")

    if not items:
        raise SystemExit("No scenes found. Try relaxing the cloud cover or date range.")


    # Getting red and nir bands
    ds = odc.stac.load(
        items,
        bands=["B04", "B08"],
        crs="EPSG:32617",  # UTM zone for the example region; choose your local UTM
        resolution=RESOLUTION,
        bbox=BBOX,
        groupby="solar_day",  # mosaic scenes from the same day
        chunks={"x": 2048, "y": 2048},  # adjust for your memory
    )

    # Sentinel-2 L2A surface-reflectance values are scaled by 10,000.
    # Convert to float and normalise to [0, 1].
    red = ds["B04"].astype("float32") / 10_000.0
    nir = ds["B08"].astype("float32") / 10_000.0


    ndvi = (nir - red) / (nir + red + 1e-8)

    # remove negative values
    # ndvi = ndvi.where(ndvi >= 0)  # keep only positive NDVI values

    ndvi_median = ndvi.median(dim="time", skipna=True)

    # sanity check via display
    # fig, ax = plt.subplots(figsize=(10, 8))
    # ndvi_median.plot(
    #     ax=ax,
    #     cmap="RdYlGn",
    #     vmin=-0.2,
    #     vmax=0.8,
    #     cbar_kwargs={"label": "NDVI"},
    # )
    # ax.set_title(f"Median NDVI  |  {START_DATE} to {END_DATE}")
    # ax.set_axis_off()
    # plt.tight_layout()
    # plt.show()




    # setup

    ndvi_monthly = ndvi.resample(time="MS").median(skipna=True)
    ndvi_monthly = ndvi_monthly.compute()          # materialise (usually small)
    ndvi_monthly = ndvi_monthly.interpolate_na(dim="time", method="linear")

    ndvi_np = ndvi_monthly.values                  # shape (12, y, x)
    times   = ndvi_monthly.time.values

    # creating color scale
    x = ndvi_monthly.x.values
    y = ndvi_monthly.y.values
    extent = [float(x.min()), float(x.max()), float(y.min()), float(y.max())]

    VMIN, VMAX = -0.2, 0.8


    CMAP = plt.get_cmap("YlGn").copy()
    CMAP.set_bad(color='#d3d3d3') 
    # CMAP = plt.get_cmap("RdYlGn").copy() # old color scale with reds on negative values
    # CMAP.set_bad(color='#d3d3d3') 

    # --- 3. Set up the figure once, update pixels per frame -------------------
    fig, ax = plt.subplots(figsize=(6, 6), dpi=90)
    ax.set_axis_off()
    im = ax.imshow(
        np.ma.masked_invalid(ndvi_np[0]),
        cmap=CMAP, vmin=VMIN, vmax=VMAX,
        extent=extent, origin="upper", interpolation="nearest",
    )
    cb = fig.colorbar(im, ax=ax, shrink=0.8, label="NDVI")
    # ax.set_xlabel("Easting (m)") #removing 
    # ax.set_ylabel("Northing (m)")

    def update(i):
        im.set_data(np.ma.masked_invalid(ndvi_np[i]))
        ax.set_title(f"NDVI  |  {np.datetime_as_string(times[i], unit='M')}")
        return (im,)

    ani = FuncAnimation(fig, update, frames=len(times), blit=False)

    # save gif
    ani.save(
        "ndvi_monthly.gif",
        writer=PillowWriter(fps=1),   # 2 frames/sec → each frame shown 500 ms
    )
    plt.close(fig)
    print("Saved ndvi_monthly.gif (12 frames, looping)")

