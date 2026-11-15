
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
    st.download_button("Download GIF", data, filename, "image/gif", key=filename)


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

with st.form("shared_location"):
    lat_column, lon_column, buffer_column = st.columns(3)
    with lat_column:
        latitude = st.number_input("Center latitude", -80.0, 84.0, value=42.75, format="%.5f")
    with lon_column:
        longitude = st.number_input("Center longitude", -180.0, 180.0, value=-84.55, format="%.5f")
    with buffer_column:
        buffer_km = st.number_input("Buffer from center (km)", 0.5, 5.0, 2.0, 0.5)
    submitted = st.form_submit_button("Generate both animations", type="primary")

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
    st.header("Air temperature forecast")
    if submitted:
        try:
            with st.spinner("Fetching Meteomatics forecasts and rendering the animation…"):
                st.session_state["weather_result"] = forecast_gif(latitude, longitude, buffer_km)
        except ValueError as error:
            st.error(str(error))
    if "location" in st.session_state and "weather_result" in st.session_state:
        show_gif(
            st.session_state["weather_result"],
            "temperature_forecast.gif",
            "Seven-day temperature forecast",
        )

with vegetation:
    st.header("Vegetation history (NDVI)")
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
        st.caption(f"{scene_count} source scenes")
        show_gif(gif, "ndvi_monthly.gif", "Monthly Sentinel-2 vegetation greenness")
