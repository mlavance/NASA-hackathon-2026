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


def forecast_gif(latitude, longitude, buffer_km):
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
