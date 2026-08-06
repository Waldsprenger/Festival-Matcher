import html
import json
import os
import re
from datetime import datetime
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium
from geopy.distance import geodesic
from geopy.geocoders import Nominatim

# ==========================================
# 1. SEITEN-KONFIGURATION & ROCK-DESIGN (CSS)
# ==========================================
st.set_page_config(
    page_title="Festival Matcher | Rock-Edition",
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
        margin-bottom: 15px;
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
    </style>
    """,
    unsafe_allow_html=True,
)


# ==========================================
# 2. HILFSFUNKTIONEN & GEODATEN-CACHE
# ==========================================
@st.cache_data(ttl="1h")
def load_data():
  if not os.path.exists("festivals.json"):
    return [], "Unbekannt"

  mod_time = os.path.getmtime("festivals.json")
  last_updated = datetime.fromtimestamp(mod_time).strftime("%d.%m.%Y %H:%M Uhr")

  with open("festivals.json", "r", encoding="utf-8") as f:
    data = json.load(f)
  return data, last_updated


@st.cache_data
def get_user_coordinates(plz_text, land="Deutschland"):
  """Sichere Ermittlung der User-Koordinaten mit Fallbacks."""
  if not plz_text:
    return None, None

  plz_clean = str(plz_text).strip()
  geolocator = Nominatim(user_agent="rock_festival_matcher_user_v4")

  # Versuche 1: Suche nach "PLZ, Land"
  try:
    loc = geolocator.geocode(f"{plz_clean}, {land}", timeout=4)
    if loc:
      return loc.latitude, loc.longitude
  except Exception:
    pass

  # Versuch 2: Suche nur nach der PLZ
  try:
    loc = geolocator.geocode(plz_clean, timeout=4)
    if loc:
      return loc.latitude, loc.longitude
  except Exception:
    pass

  return None, None


def parse_price(preis_str):
  if not preis_str:
    return 0.0
  match = re.search(r"(\d+([.,]\d+)?)", preis_str.replace(".", ""))
  if match:
    return float(match.group(1).replace(",", "."))
  return 0.0


def parse_start_date(datum_str):
  if not datum_str:
    return None
  match = re.search(r"(\d{2}\.\d{2}\.\d{4})", datum_str)
  if match:
    try:
      return datetime.strptime(match.group(1), "%d.%m.%Y").date()
    except ValueError:
      return None
  return None


# ==========================================
# 3. DATEN LADEN & VORBEREITEN
# ==========================================
raw_data, last_updated_time = load_data()

if not raw_data:
  st.error(
      "Keine Daten gefunden! Bitte stelle sicher, dass 'festivals.json' im"
      " Ordner liegt."
  )
  st.stop()

processed_data = []
for f in raw_data:
  p_val = parse_price(f.get("preis", ""))
  s_date = parse_start_date(f.get("datum", ""))

  item = f.copy()
  item["preis_num"] = p_val
  item["start_datum"] = s_date
  processed_data.append(item)

all_countries = sorted(
    list(set([f["land"] for f in processed_data if f.get("land")]))
)
all_genres = sorted(
    list(
        set([
            g
            for f in processed_data
            for g in f.get("obergruppen_genre", [])
            if g
        ])
    )
)
max_price_in_data = (
    max([f["preis_num"] for f in processed_data])
    if processed_data
    else 500.0
)

# ==========================================
# 4. SIDEBAR - FILTER & EINSTELLUNGEN
# ==========================================
st.sidebar.title("🤘 FESTIVAL FILTER")

# Gültige Beispiel-PLZ Mannheim als Standard setzen
user_plz = st.sidebar.text_input(
    "Deine PLZ:",
    value="68161",
    help="Gib deine gültige Postleitzahl ein (z. B. 68161).",
)

max_distance = st.sidebar.slider(
    "Max. Entfernung (km):",
    min_value=10,
    max_value=1000,
    value=500,  # Auf 500km erhöht als robuster Standard
    step=10,
    help="Grenzt die Festival-Suche auf einen maximalen Radius um deine PLZ ein.",
)

max_price = st.sidebar.slider(
    "Max. Preis (€):",
    min_value=0,
    max_value=int(max_price_in_data) + 50,
    value=int(max_price_in_data) + 50,
    step=10,
    help="Filtert Festivals bis zu diesem Ticketpreis.",
)

selected_countries = st.sidebar.multiselect(
    "Länder:",
    options=all_countries,
    default=all_countries,
    help="Wähle die Länder aus, in denen du ein Festival besuchen möchtest.",
)

min_date = st.sidebar.date_input(
    "Festival-Start ab:",
    value=datetime.today().date(),
    help="Es werden nur Festivals angezeigt, die an oder nach diesem Datum starten.",
)

selected_genres = st.sidebar.multiselect(
    "Genres einschränken:",
    options=all_genres,
    default=[],
    help=(
        "Filtert Festivals nach Musikrichtungen und schränkt die auswählbaren"
        " Bands ein."
    ),
)

# ==========================================
# 5. GEODATEN & GEFILTERTE DATENBASIS
# ==========================================
user_lat, user_lon = get_user_coordinates(
    user_plz,
    selected_countries[0] if len(selected_countries) == 1 else "Deutschland",
)

filtered_festivals = []
for f in processed_data:
  if f.get("land") not in selected_countries:
    continue
  if f["preis_num"] > max_price:
    continue
  if f["start_datum"] and f["start_datum"] < min_date:
    continue
  if selected_genres:
    f_genres = f.get("obergruppen_genre", [])
    if not any(g in f_genres for g in selected_genres):
      continue

  # Koordinaten aus der festivals.json nehmen
  f_lat, f_lon = f.get("lat"), f.get("lon")

  if user_lat and user_lon and f_lat and f_lon:
    dist = geodesic((user_lat, user_lon), (f_lat, f_lon)).km
    f["entfernung_km"] = round(dist, 1)
  else:
    # Falls der Standort vom User nicht auflösbar war oder das Festival keine Koord. hat
    f["entfernung_km"] = 0.0 if not (user_lat and user_lon) else 9999.0

  # Nur nach Distanz filtern, wenn User-Koordinaten gefunden wurden
  if (user_lat and user_lon and f["entfernung_km"] <= max_distance) or not (
      user_lat and user_lon
  ):
    filtered_festivals.append(f)

# ==========================================
# 6. KARTEN-ANZEIGE (FOLIUM)
# ==========================================
st.title("🎸 ROCK YOUR FESTIVAL MATCH")

with st.expander("🗺️ Radius-Karte anzeigen", expanded=True):
  if user_lat and user_lon:
    m = folium.Map(location=[user_lat, user_lon], zoom_start=6)

    folium.Circle(
        radius=max_distance * 1000,
        location=[user_lat, user_lon],
        color="#FF2A2A",
        fill=True,
        fill_color="#FF2A2A",
        fill_opacity=0.1,
        popup=f"Suchradius: {max_distance} km",
    ).add_to(m)

    folium.Marker(
        [user_lat, user_lon],
        popup=f"Dein Standort ({user_plz})",
        icon=folium.Icon(color="red", icon="home"),
    ).add_to(m)

    for f in filtered_festivals:
      if f.get("lat") and f.get("lon"):
        f_name_clean = html.escape(f["name"])
        f_ort_clean = html.escape(f.get("ort", ""))

        folium.Marker(
            [f["lat"], f["lon"]],
            popup=(
                f"<b>{f_name_clean}</b><br>{f_ort_clean}<br>{f['entfernung_km']}"
                " km"
            ),
            icon=folium.Icon(color="black", icon="music"),
        ).add_to(m)

    st_folium(m, width="100%", height=350)
  else:
    st.warning(
        f"Konnte keinen genauen Standort für die PLZ '{user_plz}' ermitteln."
        " Zeige alle Festivals ohne Distanzbegrenzung."
    )

# ==========================================
# 7. BAND-AUSWAHL & GEWICHTUNG
# ==========================================
st.subheader("🎤 Wähle deine Lieblings-Bands")

available_bands = sorted(
    list(
        set([
            band
            for f in filtered_festivals
            for band in f.get("lineup", [])
            if band
        ])
    )
)

selected_bands = st.multiselect(
    "Suche & wähle Bands (unbegrenzt):",
    options=available_bands,
    help=(
        "Wähle Bands aus dem verfügbaren Pool aus. Es stehen nur Bands aus den"
        " gefilterten Festivals zur Auswahl."
    ),
)

band_weights = {}
if selected_bands:
  st.write("🔥 **Band-Gewichtung (Doppelte Gewichtung möglich):**")
  cols = st.columns(min(len(selected_bands), 4))
  for idx, band in enumerate(selected_bands):
    col = cols[idx % 4]
    double_weight = col.checkbox(f"2x: {band}", key=f"weight_{band}")
    band_weights[band] = 2.0 if double_weight else 1.0

# ==========================================
# 8. MATCHING-ALGORITHMUS & SORTIERUNG
# ==========================================
scored_festivals = []
total_user_weight = sum(band_weights.values())

for f in filtered_festivals:
  f_bands = f.get("lineup", [])

  if total_user_weight > 0:
    matched_weight = sum(
        [weight for band, weight in band_weights.items() if band in f_bands]
    )
    score_pct = round((matched_weight / total_user_weight) * 100, 1)
  else:
    score_pct = 0.0

  f_copy = f.copy()
  f_copy["match_score"] = score_pct
  scored_festivals.append(f_copy)

scored_festivals = sorted(
    scored_festivals,
    key=lambda x: (-x["match_score"], x["entfernung_km"], x["preis_num"]),
)

# ==========================================
# 9. ERGEBNIS-ANZEIGE
# ==========================================
st.subheader(f"📊 Ergebnis: {len(scored_festivals)} Festivals gefunden")

if not scored_festivals:
  st.info("Keine Festivals entsprechen deinen Kriterien. Passe die Filter an!")
else:
  for f in scored_festivals:
    matching_bands = [
        b for b in selected_bands if b in f.get("lineup", [])
    ]
    dist_display = (
        f"{f['entfernung_km']} km"
        if f["entfernung_km"] < 9999.0 and f["entfernung_km"] > 0
        else "N/A"
    )

    st.markdown(
        f"""
        <div class="festival-card">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h2>{f['name']}</h2>
                <div class="match-score">{f['match_score']}% Match</div>
            </div>
            <p><strong>📅 Datum:</strong> {f.get('datum', 'k.A.')} | 
               <strong>💰 Preis:</strong> {f.get('preis', 'k.A.')} | 
               <strong>📍 Ort:</strong> {f.get('ort', 'k.A.')} ({f.get('land', '')}) | 
               <strong>🚗 Entfernung:</strong> {dist_display}</p>
            <p><strong>🌐 Webseite:</strong> <a href="{f.get('webseite', '#')}" target="_blank" style="color: #FF2A2A;">{f.get('webseite', 'Keine Seite')}</a></p>
            <p><strong>🎸 Match-Bands:</strong> {', '.join(matching_bands) if matching_bands else 'Keine Übereinstimmung'}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ==========================================
# 10. RECHTLICHE HINWEISE & IMPRESSUM
# ==========================================
st.markdown("---")

st.markdown(
    f"""
    <div class="footer-text">
        <p><strong>Datenaktualität & Haftungsausschluss:</strong><br>
        Letzte Aktualisierung der Festivaldaten: <u>{last_updated_time}</u>.<br>
        Die Daten wurden über <a href="https://www.festivalticker.de" target="_blank" style="color: #aaa;">festivalticker.de</a> bezogen. 
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
    Als Diensteanbieter sind wir gemäß § 7 Abs.1 TMG für eigene Inhalte auf diesen Seiten nach den allgemeinen Gesetzen verantwortlich. Nach §§ 8 bis 10 TMG sind wir als Diensteanbieter jedoch nicht verpflichtet, übermittelte oder gespeicherte fremde Informationen zu überwachen oder nach Umständen zu forschen, die auf eine rechtswidrige Tätigkeit hinweisen.

    **Haftung für Links**  
    Unser Angebot enthält Links zu externen Websites Dritter, auf deren Inhalte wir keinen Einfluss haben. Deshalb können wir für diese fremden Inhalte auch keine Gewähr übernehmen. Für die Inhalte der verlinkten Seiten ist stets der jeweilige Anbieter oder Betreiber der Seiten verantwortlich.
    """
  )
