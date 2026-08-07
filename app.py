import html
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderServiceError

# ==========================================
# 0. PFAD-KONFIGURATION
# ==========================================
BASE_DIR = Path(__file__).parent.resolve()
JSON_PATH = BASE_DIR / "festivals.json"

# ==========================================
# 1. SEITEN-KONFIGURATION & ROCK-DESIGN (CSS)
# ==========================================
st.set_page_config(
    page_title="Festival-Matcher",
    page_icon="🎸",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .stApp {
        background-color: #121212;
        color: #E0E0E0;
    }
    h1, h2, h3, h4, h5, h6 {
        color: #FF2A2A !important;
        font-family: 'Impact', 'Trebuchet MS', sans-serif;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .stButton>button {
        background-color: #A00000;
        color: #FFFFFF;
        font-weight: bold;
        border: 2px solid #FF2A2A;
        border-radius: 4px;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #FF2A2A;
        color: #000000;
        border-color: #FFFFFF;
        box-shadow: 0 0 10px #FF2A2A;
    }
    .festival-card {
        background-color: #1E1E1E;
        border: 1px solid #333333;
        border-left: 5px solid #FF2A2A;
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 5px;
    }
    .match-score {
        font-size: 24px;
        font-weight: bold;
        color: #00FF66;
    }
    .footer-text {
        font-size: 12px;
        color: #888888;
        border-top: 1px solid #333;
        padding-top: 10px;
        margin-top: 30px;
    }
    .weight-card {
        background-color: #1A1A1A;
        border: 1px solid #333;
        padding: 10px;
        border-radius: 6px;
        text-align: center;
        margin-bottom: 10px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def normalize_band_key(name: str) -> str:
    """Normalisiert Bandnamen für den Vergleich."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


# ==========================================
# 2. HILFSFUNKTIONEN & CACHING
# ==========================================
@st.cache_data(ttl="24h", show_spinner=False)
def load_data():
    if not JSON_PATH.exists():
        return [], "Unbekannt"

    mod_time = os.path.getmtime(JSON_PATH)
    last_updated = datetime.fromtimestamp(mod_time).strftime("%d.%m.%Y %H:%M Uhr")

    try:
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return [], last_updated

    # Zusätzlicher Laufzeit-Filter für doppelte Bandnamen
    global_band_map = {}
    for f in data:
        for b in f.get("lineup", []):
            key = normalize_band_key(b)
            if key not in global_band_map:
                global_band_map[key] = b
            else:
                # Wähle die bevorzugte Schreibweise (Großbuchstaben präferiert)
                existing = global_band_map[key]
                if sum(1 for c in b if c.isupper()) > sum(1 for c in existing if c.isupper()):
                    global_band_map[key] = b

    processed = []
    for f in data:
        if f.get("abgesagt", False):
            continue

        preis_str = f.get("preis", "")
        p_val = 0.0
        if preis_str:
            match = re.search(r"(\d+([.,]\d+)?)", preis_str.replace(".", ""))
            if match:
                p_val = float(match.group(1).replace(",", "."))

        datum_str = f.get("datum", "")
        s_date = None
        is_one_day = True

        if datum_str:
            match_d = re.search(r"(\d{2}\.\d{2}\.\d{4})", datum_str)
            if match_d:
                try:
                    s_date = datetime.strptime(match_d.group(1), "%d.%m.%Y").date()
                except ValueError:
                    s_date = None
            if "-" in datum_str or " bis " in datum_str.lower():
                is_one_day = False

        item = f.copy()
        
        # Harmonisiere Lineup anhand der Map
        clean_lineup = []
        seen = set()
        for b in f.get("lineup", []):
            canon = global_band_map.get(normalize_band_key(b), b)
            if canon not in seen:
                seen.add(canon)
                clean_lineup.append(canon)

        item["lineup"] = clean_lineup
        item["preis_num"] = p_val
        item["start_datum"] = s_date
        item["is_one_day"] = is_one_day
        processed.append(item)

    return processed, last_updated


@st.cache_data(ttl="7d", show_spinner=False)
def get_user_coordinates(plz, land="Deutschland"):
    if not plz:
        return None, None
    try:
        geolocator = Nominatim(user_agent="rock_festival_matcher_app_v8")
        location = geolocator.geocode(f"{plz}, {land}", timeout=5)
        if location:
            return location.latitude, location.longitude
    except (GeocoderServiceError, Exception):
        pass
    return None, None


# ==========================================
# 3. DATEN LADEN & SESSION STATE INIT
# ==========================================
processed_data, last_updated_time = load_data()

if not processed_data:
    st.error("Keine Daten gefunden! Bitte stelle sicher, dass eine gültige 'festivals.json' im Ordner liegt.")
    st.stop()

all_countries = sorted(list(set([f.get("land") for f in processed_data if f.get("land") is not None])))
all_genres = sorted(
    list(set([g for f in processed_data for g in f.get("obergruppen_genre", []) if g]))
)

if "max_distance" not in st.session_state:
    st.session_state.max_distance = 500

if "max_price" not in st.session_state:
    st.session_state.max_price = 500

if "selected_min_date" not in st.session_state:
    st.session_state.selected_min_date = datetime.now().date()


def sync_dist_input():
    st.session_state.max_distance = st.session_state.dist_input

def sync_dist_slider():
    st.session_state.max_distance = st.session_state.dist_slider

def sync_price_input():
    st.session_state.max_price = st.session_state.price_input

def sync_price_slider():
    st.session_state.max_price = st.session_state.price_slider

def set_date_to_today():
    st.session_state.selected_min_date = datetime.now().date()
    st.rerun()


# ==========================================
# 4. SIDEBAR - FILTER & EINSTELLUNGEN
# ==========================================
st.sidebar.title("🤘 FESTIVAL FILTER")

user_plz = st.sidebar.text_input(
    "Deine PLZ:",
    value="12345",
    key="input_user_plz",
    help="Gib deine Postleitzahl ein, um Entfernungen zu den Festivals zu berechnen."
)

st.sidebar.markdown("**Max. Entfernung (km):**")
col_dist_input, col_dist_slider = st.sidebar.columns([1, 2])
with col_dist_input:
    st.number_input(
        "KM Input", 
        min_value=0, 
        max_value=2000, 
        step=50, 
        value=st.session_state.max_distance,
        label_visibility="collapsed",
        key="dist_input",
        on_change=sync_dist_input
    )
with col_dist_slider:
    st.slider(
        "Entfernung Slider",
        min_value=0,
        max_value=2000,
        step=50,
        value=st.session_state.max_distance,
        label_visibility="collapsed",
        key="dist_slider",
        on_change=sync_dist_slider
    )
max_distance = st.session_state.max_distance

st.sidebar.markdown("**Max. Preis (€):**")
col_price_input, col_price_slider = st.sidebar.columns([1, 2])
with col_price_input:
    st.number_input(
        "EUR Input",
        min_value=0,
        max_value=1000,
        step=10,
        value=st.session_state.max_price,
        label_visibility="collapsed",
        key="price_input",
        on_change=sync_price_input
    )
with col_price_slider:
    st.slider(
        "Preis Slider",
        min_value=0,
        max_value=1000,
        step=10,
        value=st.session_state.max_price,
        label_visibility="collapsed",
        key="price_slider",
        on_change=sync_price_slider
    )
max_price = st.session_state.max_price

selected_countries = st.sidebar.multiselect(
    "Länder:",
    options=all_countries,
    default=all_countries,
    key="multiselect_countries"
)

col_date_picker, col_date_btn = st.sidebar.columns([3, 1])
with col_date_picker:
    min_date = st.date_input(
        "Festival-Start ab:",
        value=st.session_state.selected_min_date,
        key="selected_min_date"
    )
with col_date_btn:
    st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
    st.button("📅 Heute", on_click=set_date_to_today)

show_one_day = st.sidebar.toggle(
    "Eintagesfestivals anzeigen",
    value=True,
    key="toggle_one_day_festivals"
)

selected_genres = st.sidebar.multiselect(
    "Genres einschränken:",
    options=all_genres,
    default=[],
    key="multiselect_genres"
)

# ==========================================
# 5. ERSTE FILTERUNG DER DATENBASIS
# ==========================================
country_param = selected_countries[0] if selected_countries else "Deutschland"
user_lat, user_lon = get_user_coordinates(user_plz, country_param)

filtered_festivals = []
for f in processed_data:
    if selected_countries and f.get("land") not in selected_countries:
        continue
    if f["preis_num"] > max_price:
        continue
    if f["start_datum"] and min_date and f["start_datum"] < min_date:
        continue
    if not show_one_day and f.get("is_one_day", True):
        continue
    if selected_genres:
        f_genres = f.get("obergruppen_genre", [])
        if not any(g in f_genres for g in selected_genres):
            continue

    f_lat, f_lon = f.get("lat"), f.get("lon")
    if user_lat is not None and user_lon is not None and f_lat and f_lon:
        dist = geodesic((user_lat, user_lon), (f_lat, f_lon)).km
        f["entfernung_km"] = round(dist, 1)
    else:
        f["entfernung_km"] = 99999.0

    if f["entfernung_km"] <= max_distance:
        filtered_festivals.append(f)

# Extraktion der verfügbaren Bands (vollständig dedupliziert)
available_bands = sorted(
    list(set([band for f in filtered_festivals for band in f.get("lineup", []) if band])),
    key=lambda x: x.lower()
)

# ==========================================
# 6. HEADER & BAND-AUSWAHL
# ==========================================
st.title("🎸 FESTIVAL-MATCHER")

st.subheader("🎤 Wähle deine Lieblings-Bands")

selected_bands = st.multiselect(
    "Suche & wähle Bands:",
    options=available_bands,
    key="multiselect_bands"
)

band_weights = {}
if selected_bands:
    st.write("⚡ **Schalte um auf 2x Gewichtung für Prioritäts-Bands:**")
    num_cols = max(1, min(len(selected_bands), 4))
    cols = st.columns(num_cols)
    for idx, band in enumerate(selected_bands):
        col = cols[idx % num_cols]
        with col:
            st.markdown(f"<div class='weight-card'><b>{html.escape(band)}</b></div>", unsafe_allow_html=True)
            double_weight = st.toggle(
                "2x Gewichtung", 
                key=f"weight_{band}"
            )
            band_weights[band] = 2.0 if double_weight else 1.0

# ==========================================
# 7. MATCHING-ALGORITHMUS & FINAL FILTERING
# ==========================================
scored_festivals = []
total_user_weight = sum(band_weights.values())

for f in filtered_festivals:
    f_bands = f.get("lineup", [])
    f_bands_lower = [b.lower() for b in f_bands]

    if total_user_weight > 0:
        matched_weight = sum(
            [weight for band, weight in band_weights.items() if band.lower() in f_bands_lower]
        )
        score_pct = round((matched_weight / total_user_weight) * 100, 1)
    else:
        score_pct = 0.0

    if score_pct > 0.0:
        f_copy = f.copy()
        f_copy["match_score"] = score_pct
        scored_festivals.append(f_copy)

scored_festivals = sorted(
    scored_festivals,
    key=lambda x: (-x["match_score"], x["entfernung_km"], x["preis_num"]),
)

# ==========================================
# 8. KARTEN-ANZEIGE
# ==========================================
with st.expander("🗺️ Radius-Karte anzeigen", expanded=True):
    if user_lat is not None and user_lon is not None:
        m = folium.Map(location=[user_lat, user_lon])

        folium.Circle(
            radius=max_distance * 1000,
            location=[user_lat, user_lon],
            color="#FF2A2A",
            fill=True,
            fill_color="#FF2A2A",
            fill_opacity=0.08,
            popup=f"Suchradius: {max_distance} km",
        ).add_to(m)

        folium.Marker(
            [user_lat, user_lon],
            popup=f"Dein Standort ({html.escape(user_plz)})",
            icon=folium.Icon(color="red", icon="home"),
        ).add_to(m)

        for f in scored_festivals:
            if f.get("lat") and f.get("lon"):
                f_name_clean = html.escape(f["name"])
                f_ort_clean = html.escape(f.get("ort", ""))
                score_val = f["match_score"]

                folium.Marker(
                    [f["lat"], f["lon"]],
                    popup=f"<b>{f_name_clean}</b><br>{f_ort_clean}<br>Match: {score_val}%<br>{f['entfernung_km']} km",
                    icon=folium.Icon(color="black", icon="music"),
                ).add_to(m)

        lat_delta = max_distance / 111.0
        cos_lat = max(0.1, math.cos(math.radians(user_lat)))
        lon_delta = max_distance / (111.0 * cos_lat)
        
        south = max(-85.0, user_lat - lat_delta)
        north = min(85.0, user_lat + lat_delta)
        west = max(-180.0, user_lon - lon_delta)
        east = min(180.0, user_lon + lon_delta)

        m.fit_bounds([[south, west], [north, east]])

        st_folium(m, width="100%", height=500, returned_objects=[])
    else:
        st.warning("Konnte Standort für die eingegebene PLZ nicht bestimmen.")

# ==========================================
# 9. ERGEBNIS-ANZEIGE MIT AUFKLAPPBAREM LINEUP
# ==========================================
st.subheader(f"📊 Ergebnis: {len(scored_festivals)} Festivals gefunden")

if not selected_bands:
    st.info("Wähle oben deine Lieblings-Bands aus, um Matches anzuzeigen.")
elif not scored_festivals:
    st.info("Keine Festivals mit Übereinstimmungen gefunden. Passe deine Filter oder Band-Auswahl an!")
else:
    for f in scored_festivals:
        f_bands = f.get("lineup", [])
        f_bands_lower = [b.lower() for b in f_bands]

        matching_bands_formatted = []
        for b in selected_bands:
            if b.lower() in f_bands_lower:
                escaped_b = html.escape(b)
                if band_weights.get(b) == 2.0:
                    matching_bands_formatted.append(f'<span style="color: #FF2A2A; font-weight: bold;">⚡ {escaped_b} (2x)</span>')
                else:
                    matching_bands_formatted.append(escaped_b)

        dist_display = (
            f"{f['entfernung_km']} km"
            if f["entfernung_km"] < 99999.0
            else "Unbekannt"
        )

        st.markdown(
            f"""
            <div class="festival-card">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <h2>{html.escape(f['name'])}</h2>
                    <div class="match-score">{f['match_score']}% Match</div>
                </div>
                <p><strong>📅 Datum:</strong> {html.escape(str(f.get('datum', 'k.A.')))} | 
                   <strong>💰 Preis:</strong> {html.escape(str(f.get('preis', 'k.A.')))} | 
                   <strong>📍 Ort:</strong> {html.escape(str(f.get('ort', 'k.A.')))} ({html.escape(str(f.get('land', '')))}) | 
                   <strong>🚗 Entfernung:</strong> {dist_display}</p>
                <p><strong>🌐 Webseite:</strong> <a href="{html.escape(f.get('webseite', '#'))}" target="_blank" style="color: #FF2A2A;">{html.escape(f.get('webseite', 'Keine Seite'))}</a></p>
                <p><strong>🎸 Match-Bands:</strong> {', '.join(matching_bands_formatted)}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.expander(f"📋 Vollständiges Lineup für {f['name']} anzeigen ({len(f_bands)} Bands)", expanded=False):
            if f_bands:
                sorted_bands = sorted(f_bands, key=lambda x: x.lower())
                st.write(", ".join([f"**{b}**" if b.lower() in [sb.lower() for sb in selected_bands] else b for b in sorted_bands]))
            else:
                st.write("Kein Lineup verfügbar.")

# ==========================================
# 10. RECHTLICHE HINWEISE & IMPRESSUM
# ==========================================
st.markdown("---")

st.markdown(
    f"""
    <div class="footer-text">
        <p><strong>Datenaktualität & Haftungsausschluss:</strong><br>
        Letzte Aktualisierung der Festivaldaten: <u>{html.escape(last_updated_time)}</u>.<br>
        Es besteht keinerlei Gewährleistung für die Korrektheit, Vollständigkeit oder Aktualität der Daten.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.expander("⚖️ Impressum & Rechtliche Hinweise"):
    st.markdown(
        """
    ### Impressum
    **Angaben gemäß § 5 DDG:**  
    Arne Waldsperger  
    N7 2a  
    68161 Mannheim  

    **Kontakt:**  
    E-Mail: waldsprenger@gmail.com  

    ---
    ### Haftungsausschluss (Disclaimer)

    **Haftung für Inhalte**  
    Als Diensteanbieter sind wir gemäß § 7 Abs.1 TMG für eigene Inhalte auf diesen Seiten nach den allgemeinen Gesetzen verantwortlich.

    **Haftung für Links**  
    Unser Angebot enthält Links zu externen Websites Dritter, auf deren Inhalte wir keinen Einfluss haben.
    """
    )
