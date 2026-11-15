import base64
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import streamlit as st

R_SCRIPT = Path(__file__).with_name("weather.r").resolve()
GIF_PATH = Path("forecast_output") / "temperature_forecast.gif"


def forecast_gif(north, west, south, east):
    rscript = shutil.which("Rscript")
    if rscript is None or not R_SCRIPT.is_file():
        raise ValueError("Install Rscript and place weather.r next to streamlit_app.py.")

    try:
        username = st.secrets["METEOMATICS_USER"]
        password = st.secrets["METEOMATICS_PASSWORD"]
    except (FileNotFoundError, KeyError):
        raise ValueError("Add the Meteomatics credentials in Streamlit Secrets.") from None

    env = {
        **os.environ,
        "WEATHER_WEB": "1",
        "WEATHER_NORTH": f"{north:.5f}",
        "WEATHER_WEST": f"{west:.5f}",
        "WEATHER_SOUTH": f"{south:.5f}",
        "WEATHER_EAST": f"{east:.5f}",
        "METEOMATICS_USER": username,
        "METEOMATICS_PASSWORD": password,
    }

    with TemporaryDirectory() as folder:
        try:
            subprocess.run(
                [rscript, "--vanilla", str(R_SCRIPT)],
                cwd=folder,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            raise ValueError("Forecast generation timed out. Please try again.") from None
        except subprocess.CalledProcessError as error:
            output = error.stderr or ""
            for status in (400, 401, 403, 404, 429, 500, 502, 503, 504):
                if f"HTTP {status}" in output:
                    raise ValueError(f"Meteomatics returned HTTP {status}.") from None
            raise ValueError(
                "weather.r stopped before creating the animation. "
                "Check that httr2, ggplot2, and magick are installed for Rscript."
            ) from None

        path = Path(folder) / GIF_PATH
        if not path.is_file():
            raise ValueError("weather.r did not create the expected GIF.")
        return path.read_bytes()


def show_gif(data, filename, alt):
    encoded = base64.b64encode(data).decode("ascii")
    st.markdown(
        f'<img src="data:image/gif;base64,{encoded}" alt="{alt}" '
        'style="display:block;width:100%;max-width:720px;height:auto;">',
        unsafe_allow_html=True,
    )
    st.download_button("Download GIF", data, filename, "image/gif", key=filename)


def weather_section():
    st.header("Air temperature forecast")
    st.caption("Enter the northwest and southeast corners in decimal degrees.")
    with st.form("forecast_area"):
        left, right = st.columns(2)
        with left:
            north = st.number_input("North latitude", -89.0, 89.0, value=None, format="%.5f")
            west = st.number_input("West longitude", -180.0, 180.0, value=None, format="%.5f")
        with right:
            south = st.number_input("South latitude", -89.0, 89.0, value=None, format="%.5f")
            east = st.number_input("East longitude", -180.0, 180.0, value=None, format="%.5f")
        submitted = st.form_submit_button("Generate forecast", type="primary")

    if submitted:
        bounds = (north, west, south, east)
        if any(value is None for value in bounds):
            st.error("Enter all four coordinates.")
        elif round(north, 5) <= round(south, 5) or round(east, 5) <= round(west, 5):
            st.error("North must be greater than south, and east must be greater than west.")
        else:
            try:
                with st.spinner("Fetching forecast grids and rendering the animation…"):
                    gif = forecast_gif(*bounds)
                st.session_state["weather_result"] = gif, bounds
            except ValueError as error:
                st.error(str(error))

    if "weather_result" in st.session_state:
        gif, (north, west, south, east) = st.session_state["weather_result"]
        st.caption(f"Displayed forecast bounds · NW ({north:.5f}, {west:.5f}) · SE ({south:.5f}, {east:.5f})")
        show_gif(gif, "temperature_forecast.gif", "Seven-day temperature forecast")


def ndvi_section():
    st.header("Vegetation history (NDVI)")
    st.caption("NDVI shows vegetation greenness. This animation uses monthly Sentinel-2 imagery.")
    with st.form("ndvi_area"):
        left, right = st.columns(2)
        with left:
            latitude = st.number_input("Center latitude", -80.0, 84.0, value=None, format="%.5f")
        with right:
            longitude = st.number_input("Center longitude", -180.0, 180.0, value=None, format="%.5f")
        buffer_km = st.number_input("Distance from center to each edge (km)", 0.5, 5.0, 2.0, 0.5)
        submitted = st.form_submit_button("Generate NDVI animation", type="primary")

    if submitted:
        if latitude is None or longitude is None:
            st.error("Enter a center latitude and longitude.")
        else:
            try:
                from ndvi_gif import create_gif

                with st.spinner("Loading Sentinel-2 imagery and rendering monthly maps…"):
                    gif, scenes = create_gif(longitude, latitude, buffer_km)
                st.session_state["ndvi_result"] = gif, scenes, latitude, longitude, buffer_km
            except ValueError as error:
                st.error(str(error))
            except Exception:
                st.error("NDVI generation failed. Check the Streamlit logs for details.")
                import logging

                logging.exception("NDVI generation failed")

    if "ndvi_result" in st.session_state:
        gif, scenes, latitude, longitude, buffer_km = st.session_state["ndvi_result"]
        st.caption(f"Displayed NDVI · {latitude:.5f}, {longitude:.5f} · {buffer_km:g} km buffer · {scenes} source scenes")
        show_gif(gif, "ndvi_monthly.gif", "Monthly Sentinel-2 vegetation greenness")


st.set_page_config(page_title="Weather and Vegetation Explorer", layout="wide")
st.title("Weather and Vegetation Explorer")
weather, vegetation = st.columns(2, gap="large")
with weather:
    weather_section()
with vegetation:
    ndvi_section()
