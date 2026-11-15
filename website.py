import streamlit as st

import ndvi_gif as ng

sat_init_1, sat_init_2, sat_init_3 = st.columns(3)

default_lon = -83.22
default_lat = 42.6

# default_lon = -77.01635
# default_lat = 38.88293


st.session_state.setdefault("lati", default_lat)
st.session_state.setdefault("long",  default_lon)
st.session_state.setdefault("dist",  5)


with sat_init_1:
    lat = st.number_input("Latitude",  value=default_lat, format="%.5f")
with sat_init_2:
    long = st.number_input("Longitude", value= default_lon, format="%.5f")
with sat_init_3:
    buffer = st.number_input("Range (km)", min_value=1, value=5, step=1)

if st.button("Create GIF, takes a minute or two"):
    try:
        with st.spinner("Fetching Sentinel-2 imagery and building GIF…"):
            gif_bytes, n_scenes = ng.create_gif(long, lat, buffer)
        st.session_state["gif"]       = gif_bytes
        st.session_state["n_scenes"]  = n_scenes
    except ValueError as e: 
        st.session_state.pop("gif", None)
        st.session_state.pop("n_scenes", None)
        st.error(str(e))
    except Exception as e:
        st.session_state.pop("gif", None)
        st.error(f"Something went wrong: {e}")

if "gif" in st.session_state:
    st.caption(f"Built from {st.session_state['n_scenes']} scenes")
    st.image(st.session_state["gif"])
    st.download_button(
        "Download GIF",
        st.session_state["gif"],
        file_name="ndvi_monthly.gif",
        mime="image/gif",
    )