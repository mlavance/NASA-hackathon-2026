import base64
import logging
import math
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import streamlit as st

R_SCRIPT = Path(__file__).with_name("weather.r").resolve()
GIF_PATH = Path("forecast_output") / "temperature_forecast.gif"


def forecast_gif(latitude, longitude, buffer_km, regional_view):
    rscript = shutil.which("Rscript")
    if not R_SCRIPT.is_file():
        raise ValueError("Add weather.r next to combined_apps.py in GitHub. The filename is case-sensitive.")
    if rscript is None:
        raise ValueError("Rscript was not found. On Streamlit Cloud, add r-base to packages.txt and rebuild the app.")

    try:
        username = st.secrets["METEOMATICS_USER"]
        password = st.secrets["METEOMATICS_PASSWORD"]
    except (FileNotFoundError, KeyError):
        raise ValueError("Add the Meteomatics credentials in Streamlit Secrets.") from None

    env = {
        **os.environ,
        "WEATHER_WEB": "1",
        "WEATHER_LATITUDE": str(latitude),
        "WEATHER_LONGITUDE": str(longitude),
        "WEATHER_BUFFER_KM": str(buffer_km),
        "WEATHER_REGION_BUFFER_KM": str(100 if regional_view else buffer_km),
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

            for package in ("httr2", "ggplot2", "magick"):
                if "there is no package called" in output and package in output:
                    raise ValueError(
                        f"R is missing {package}. Add r-cran-{package} to packages.txt "
                        "and rebuild the app on Streamlit Cloud."
                    ) from None

            # Show R's error message without request headers or credentials.
            basic_auth = base64.b64encode(f"{username}:{password}".encode()).decode()
            for secret in (basic_auth, password, username):
                if secret:
                    output = output.replace(secret, "[redacted]")
            lines = [
                line.strip() for line in output.splitlines()
                if line.lstrip().startswith(("Error", "!"))
                and "authorization" not in line.lower()
            ]
            detail = " ".join(lines[-3:])[:500]
            message = "weather.r stopped before creating the animation."
            if detail:
                message = f"{message} {detail}"
            else:
                message = f"{message} R exited with status {error.returncode}."
            raise ValueError(message) from None

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
    st.download_button(
        "Download GIF", data, filename, "image/gif", key=filename, type="primary"
    )


def validate_location(latitude, longitude, buffer_km):
    if latitude is None or longitude is None:
        raise ValueError("Enter a center latitude and longitude.")

    # Match the bounding box in ndvi_gif.create_gif.
    delta_lat = buffer_km / 111.32
    delta_lon = buffer_km / (111.32 * math.cos(math.radians(latitude)))
    if (
        longitude - delta_lon < -180
        or longitude + delta_lon > 180
        or latitude - delta_lat < -80
        or latitude + delta_lat > 84
    ):
        raise ValueError(
            "Choose an area between 80°S and 84°N that does not cross the date line."
        )


st.set_page_config(page_title="Earth’s Next Season", layout="wide")
st.title("Earth’s Next Season")
st.caption("A project for NASA Space Apps Challenge 2026 by Micheal La Vance and Shaina Mishra")
st.write(
    'The Earth’s Next Season toolset is a web application that shows two animated maps for the same areas: the vegetation map and the forecasted future air temperature '
    'for the region. The weather map uses the Meteomatics API to show forecast air temperature every six hours for seven days. Each frame reports the percentage '
    'of grid cells with valid forecasts at or below 0°C. The vegetation map uses Sentinel-2 imagery from Microsoft Planetary Computer to show monthly changes '
    'in the Normalized Difference Vegetation Index (NDVI), a measure of vegetation greenness, over roughly the previous year. Users can view the animations side '
    'by side and download either as a GIF.'
)

with st.form("shared_location"):
    lat_column, lon_column, buffer_column = st.columns(3)
    with lat_column:
        latitude = st.number_input("Center latitude", -80.0, 84.0, value=42.75, format="%.5f")
    with lon_column:
        longitude = st.number_input("Center longitude", -180.0, 180.0, value=-84.55, format="%.5f")
    with buffer_column:
        buffer_km = st.number_input("Buffer from center (km)", 0.5, 5.0, 2.0, 0.5)
    regional_view = st.checkbox(
        "Show a wider weather map (up to 100 km from center)", value=True,
        help="Turn this off to use the exact same map area for weather and vegetation.",
    )
    submitted = st.form_submit_button("Generate Animations", type="primary")

if submitted:
    try:
        validate_location(latitude, longitude, buffer_km)
    except ValueError as error:
        st.error(str(error))
        submitted = False
    else:
        st.session_state["location"] = latitude, longitude, buffer_km
        st.session_state.pop("weather_result", None)
        st.session_state.pop("ndvi_result", None)

if "location" in st.session_state:
    lat, lon, distance = st.session_state["location"]
    st.caption(f"Selected area · {lat:.5f}, {lon:.5f} · {distance:g} km buffer")

weather, vegetation = st.columns(2, gap="large")
with weather:
    st.header("Air Temperature Forecast")
    st.caption("Meteomatics air temperature at 0.002 km above ground, every six hours for seven days.")
    if submitted:
        try:
            with st.spinner("Fetching Meteomatics forecasts and rendering the animation…"):
                st.session_state["weather_result"] = forecast_gif(
                    latitude, longitude, buffer_km, regional_view
                )
        except ValueError as error:
            st.error(str(error))
    if "location" in st.session_state and "weather_result" in st.session_state:
        show_gif(
            st.session_state["weather_result"],
            "temperature_forecast.gif",
            "Seven-day temperature forecast",
        )

with vegetation:
    st.header("Vegetation History (NDVI)")
    st.caption("Monthly Sentinel-2 imagery showing vegetation greenness.")
    if submitted:
        try:
            from ndvi_gif import create_gif

            with st.spinner("Loading Sentinel-2 imagery and rendering the animation…"):
                st.session_state["ndvi_result"] = create_gif(longitude, latitude, buffer_km)
        except ValueError as error:
            st.error(str(error))
        except Exception:
            logging.exception("NDVI generation failed")
            st.error("NDVI generation failed. Check the Streamlit logs for details.")
    if "location" in st.session_state and "ndvi_result" in st.session_state:
        gif, scene_count = st.session_state["ndvi_result"]
        show_gif(gif, "ndvi_monthly.gif", "Monthly Sentinel-2 vegetation greenness")
        st.caption(f"{scene_count} source scenes")
