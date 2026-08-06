import datetime
import json
import math
import re
from urllib.parse import quote_plus
import folium
import numpy as np
import pandas as pd
from geopy.geocoders import Nominatim
import streamlit as st
from streamlit_folium import st_folium

# Streamlit Konfiguration
st.set_page_config(
    page_title="Festival-Finder Deutschland 2026",
    page_icon="⛺",
    layout="wide",
)

# Custom CSS für Design und Anabstand
st.markdown(
    """
    <style>
    .stApp {
        background-color: #0e1117;
        color: #ffffff;
    }
    .stButton>button {
        background-color: #ff4b4b;
        color: white;
        border-radius: 8px;
        font-weight: bold;
    }
    .metric-card {
        background-color: #1f2937;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #374151;
        text-align: center;
    }
    </style>
""",
    unsafe_allow_html=True,
)


@st.cache_data
def load_coords_cache():
    try:
        with open("coords_cache.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


@st.cache_data
def load_data():
    coords_cache = load_coords_cache()
    try:
        with open("festivals.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        st.error(f"Fehler beim Laden der Festivaldaten: {e}")
        return pd.DataFrame()

    processed_data = []
    for f in data:
        lat = f.get("lat")
        lon = f.get("lon")

        # Fallback: Falls lat/lon null sind, aus coords_cache.json ermitteln
        if lat is None or lon is None:
            plz = str(f.get("plz", "")).strip()
            land = f.get("land", "Deutschland").strip()
            ort = f.get("ort", "").strip()

            cache_key = f"{plz}_{land}"
            if cache_key in coords_cache:
                lat, lon = coords_cache[cache_key]
            else:
                alt_cache_key = f"{plz}_{ort}_{land}"
                if alt_cache_key in coords_cache:
                    lat, lon = coords_cache[alt_cache_key]

        item = {
            "name": f.get("name", "Unbekannt"),
            "genre": f.get("genre", "Diverse"),
            "ort": f.get("ort", "Unbekannt"),
            "plz": f.get("plz", ""),
            "land": f.get("land", "Deutschland"),
            "startdatum": f.get("startdatum", ""),
            "enddatum": f.get("enddatum", ""),
            "lat": lat,
            "lon": lon,
            "webseite": f.get("webseite", "#"),
            "besucher": f.get("besucher", 0),
        }
        processed_data.append(item)

    df = pd.DataFrame(processed_data)
    if not df.empty:
        df["startdatum_dt"] = pd.to_datetime(df["startdatum"], errors="coerce")
        df["enddatum_dt"] = pd.to_datetime(df["enddatum"], errors="coerce")
    return df


def haversine_distance(lat1, lon1, lat2, lon2):
    if any(v is None or math.isnan(v) for v in [lat1, lon1, lat2, lon2]):
        return 99999.0
    R = 6371.0  # Erdradius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# Hauptanwendungslogik
df = load_data()

st.title("⛺ Festival-Finder 2026")
st.write(
    "Finde Musikfestivals in deiner Nähe und erstelle deine Sommerplanung!"
)

# Sidebar Filter
st.sidebar.header("Filter-Optionen")
search_plz = st.sidebar.text_input("Deine PLZ / Ort (für Distanzsuche):", "")
max_dist = st.sidebar.slider("Maximaler Umkreis (km):", 10, 500, 150)

all_genres = (
    sorted(list(set(df["genre"].dropna().unique()))) if not df.empty else []
)
selected_genres = st.sidebar.multiselect(
    "Genre-Filter:", all_genres, default=[]
)

# Geocoding des Heimatorts
user_lat, user_lon = None, None
if search_plz:
    geolocator = Nominatim(user_agent="festival_finder_app_2026")
    try:
        location = geolocator.geocode(f"{search_plz}, Germany")
        if location:
            user_lat, user_lon = location.latitude, location.longitude
            st.sidebar.success(f"Standort gefunden: {location.address}")
        else:
            st.sidebar.warning(
                "PLZ/Ort nicht gefunden. Zeige ungefilterte Distanzen."
            )
    except Exception:
        st.sidebar.error("Geocoding-Dienst nicht erreichbar.")

# Distanzberechnung
if not df.empty:
    if user_lat and user_lon:
        df["entfernung_km"] = df.apply(
            lambda r: round(
                haversine_distance(user_lat, user_lon, r["lat"], r["lon"]), 1
            ),
            axis=1,
        )
    else:
        df["entfernung_km"] = 0.0

# Daten filtern
filtered_df = df.copy()
if selected_genres:
    filtered_df = filtered_df[filtered_df["genre"].isin(selected_genres)]
if user_lat and user_lon:
    filtered_df = filtered_df[filtered_df["entfernung_km"] <= max_dist]

# Sortierung
filtered_df = filtered_df.sort_values(by="startdatum_dt")

# Layout Ergebnisse
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader(f"Gefundene Festivals ({len(filtered_df)})")
    for _, row in filtered_df.iterrows():
        with st.expander(f"🎪 {row['name']} ({row['ort']})"):
            st.write(f"**Datum:** {row['startdatum']} bis {row['enddatum']}")
            st.write(f"**Genre:** {row['genre']}")
            if user_lat and user_lon:
                st.write(f"**Entfernung:** {row['entfernung_km']} km")
            st.write(f"**Webseite:** [{row['webseite']}]({row['webseite']})")

with col2:
    st.subheader("Karte")
    if not filtered_df.empty:
        map_center = (
            [user_lat, user_lon]
            if user_lat
            else [
                filtered_df["lat"].dropna().mean(),
                filtered_df["lon"].dropna().mean(),
            ]
        )
        m = folium.Map(location=map_center, zoom_start=6)

        if user_lat and user_lon:
            folium.Marker(
                [user_lat, user_lon],
                popup="Dein Standort",
                icon=folium.Icon(color="red", icon="home"),
            ).add_to(m)

        for _, row in filtered_df.iterrows():
            if pd.notnull(row["lat"]) and pd.notnull(row["lon"]):
                folium.Marker(
                    [row["lat"], row["lon"]],
                    popup=f"{row['name']} ({row['ort']})",
                    tooltip=row["name"],
                ).add_to(m)

        st_folium(m, width=400, height=500)

# Impressum
st.markdown("---")
with st.expander("Impressum"):
    st.write("Angaben gemäß § 5 TMG")
    st.write("Arne Waldsperger")
    st.write("E-Mail: waldsprenger@gmail.com")
