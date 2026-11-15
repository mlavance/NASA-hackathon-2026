import base64
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import streamlit as st

R_SCRIPT = Path(__file__).resolve().parent / "weather.r"
GIF_PATH = Path("forecast_output") / "temperature_forecast.gif"

st.title("Air Temperature Forecast")
st.write(
    "Enter the northwest and southeast corners of your forecast area "
    "in decimal degrees. Use negative longitudes for locations west of Greenwich."
)

with st.form("forecast_area"):
    left, right = st.columns(2)
    with left:
        north = st.number_input("North latitude", -89.0, 89.0, 48.5, format="%.5f")
        west = st.number_input("West longitude", -180.0, 180.0, -90.6, format="%.5f")
    with right:
        south = st.number_input("South latitude", -89.0, 89.0, 41.5, format="%.5f")
        east = st.number_input("East longitude", -180.0, 180.0, -82.0, format="%.5f")

    generate = st.form_submit_button("Generate forecast", type="primary")

if generate:
    rscript = shutil.which("Rscript")

    if round(north, 5) <= round(south, 5) or round(west, 5) >= round(east, 5):
        st.error("North must be greater than south, and east must be greater than west.")
    elif rscript is None or not R_SCRIPT.is_file():
        st.error("The server needs Rscript installed and weather.r next to streamlit_app.py.")
    else:
        try:
            env = {
                **os.environ,
                "WEATHER_WEB": "1",
                "WEATHER_NORTH": str(north),
                "WEATHER_WEST": str(west),
                "WEATHER_SOUTH": str(south),
                "WEATHER_EAST": str(east),
                "METEOMATICS_USER": st.secrets["METEOMATICS_USER"],
                "METEOMATICS_PASSWORD": st.secrets["METEOMATICS_PASSWORD"],
            }

            with st.spinner("Fetching forecast data and rendering the GIF…"):
                with TemporaryDirectory() as work_dir:
                    subprocess.run(
                        [rscript, "--vanilla", str(R_SCRIPT)],
                        cwd=work_dir,
                        env=env,
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        check=True,
                        timeout=600,
                    )
                    gif = (Path(work_dir) / GIF_PATH).read_bytes()

            st.session_state["forecast"] = (gif, north, west, south, east)

        except (KeyError, FileNotFoundError) as error:
            if isinstance(error, KeyError):
                st.error("Add your Meteomatics credentials in Streamlit Secrets.")
            else:
                st.error("The forecast GIF was not created at the expected path.")
        except subprocess.TimeoutExpired:
            st.error("Forecast generation timed out. Please try again.")
        except subprocess.CalledProcessError:
            st.error(
                "weather.r could not complete the forecast. Check the deployed R "
                "packages, your Meteomatics credentials, and access for this region."
            )

if "forecast" in st.session_state:
    gif, saved_north, saved_west, saved_south, saved_east = st.session_state["forecast"]
    st.caption(
        f"Displayed forecast bounds: NW ({saved_north:.5f}, {saved_west:.5f}) | "
        f"SE ({saved_south:.5f}, {saved_east:.5f})"
    )
    encoded = base64.b64encode(gif).decode("ascii")
    st.markdown(
        f'<img src="data:image/gif;base64,{encoded}" '
        'alt="Animated air temperature forecast" '
        'style="display:block;width:100%;max-width:720px;height:auto;">',
        unsafe_allow_html=True,
    )
    st.download_button(
        "Download GIF", gif, "temperature_forecast.gif", "image/gif"
    )