import streamlit as st
import json
import os
import re
from datetime import datetime, date
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

# ---------------------------------------------------------------------------
# 1. HELFER-FUNKTIONEN: DATA LOADING, BAND-NORMALISIERUNG & GEODATEN
# ---------------------------------------------------------------------------

def normalize_band_name(name: str) -> str:
    """Standardisiert Bandnamen für den Vergleich (z. B. 'A Day To Remember' == 'A Day to Remember')."""
    clean = name.strip()
    clean = re.sub(r'\s+', ' ', clean)
    return clean

@st.cache_data(ttl=86400)
def load_festival_data():
    """Lädt die gecrawlten Festival-Daten und ermittelt das Änderungsdatum.
    Stürzt bei fehlender Datei nicht ab, sondern gibt leere Daten zurück."""
    file_path = "festivals_data.json"
    if not os.path.exists(file_path):
        return [], "Noch keine Daten vorhanden (Scraper muss zuerst ausgeführt werden)"

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Letztes Änderungsdatum der Datei ermitteln
        mod_time = os.path.getmtime(file_path)
        last_update_str = datetime.fromtimestamp(mod_time).strftime("%d.%m.%Y um %H:%M Uhr")
        return data, last_update_str
    except Exception as e:
        return [], f"Fehler beim Laden der Datei: {e}"

@st.cache_data(ttl=86400)
def get_coordinates(plz: str, land: str = "Deutschland"):
    """Ermittelt Breiten- und Längengrad zu einer PLZ (mit Caching & Fallback)."""
    if not plz or plz == "N/A":
        return None

    # PLZ bereinigen (nur Zahlen/Buchstaben)
    clean_plz = re.sub(r'[^a-zA-Z0-9]', '', str(plz)).strip()
    if not clean_plz:
        return None

    # Versuche 1: Nominatim mit eindeutigem User-Agent und expliziten Parametern
    try:
        # Ein eindeutiger User-Agent verhindert, dass Nominatim die Anfrage blockiert
        geolocator = Nominatim(user_agent="festival_matcher_app_waldsprenger_v2")
        
        # Gezielte Abfrage über Structured Query oder Suchstring
        query = f"{clean_plz}, {land}"
        location = geolocator.geocode(query, timeout=5)
        
        if location:
            return (location.latitude, location.longitude)
        
        # Falls mit Land nicht gefunden, nur nach der PLZ suchen
        location_fallback = geolocator.geocode(clean_plz, timeout=5)
        if location_fallback:
            return (location_fallback.latitude, location_fallback.longitude)

    except Exception:
        pass

    # Versuche 2: Fallback über die kostenlose Open-Meteo Geocoding API (sehr schnell & zuverlässig)
    try:
        url = f"https://geocoding-api.open-meteo.com/v1/search?name={clean_plz}&count=1&language=de&format=json"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if "results" in data and len(data["results"]) > 0:
                lat = data["results"][0]["latitude"]
                lon = data["results"][0]["longitude"]
                return (lat, lon)
    except Exception:
        pass

    return None

def parse_price(preis_str: str) -> float:
    """Extrahiert den ersten numerischen Preis aus dem Preistext."""
    if not preis_str or preis_str == "N/A":
        return 0.0
    match = re.search(r'(\d+[\.,]?\d*)', preis_str.replace(',', '.'))
    return float(match.group(1)) if match else 0.0

def parse_start_date(datum_str: str):
    """Parses the start date from 'DD.MM.YYYY bis DD.MM.YYYY' or 'DD.MM.YYYY'."""
    if not datum_str or datum_str == "N/A":
        return None
    match = re.search(r'(\d{2}\.\d{2}\.\d{4})', datum_str)
    if match:
        try:
            return datetime.strptime(match.group(1), "%d.%m.%Y").date()
        except ValueError:
            return None
    return None

# ---------------------------------------------------------------------------
# 2. STREAMLIT UI BUILDER
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Festival Matcher & Finder", page_icon="🤘", layout="wide")

st.title("🤘 Metal & Rock Festival Matcher")
st.markdown("Finde das perfekte Festival basierend auf deinen Lieblingsbands, deinem Standort und deinem Budget!")

# Daten laden
festivals, last_update = load_festival_data()

if not festivals:
    st.warning("⚠️ Keine Festival-Daten gefunden. Stellen Sie sicher, dass der GitHub Scraper gelaufen ist und `festivals_data.json` im Hauptverzeichnis liegt.")
else:
    # --- ALLE BANDS SAMMELN & BEREINIGEN ---
    raw_band_map = {}  # Key: normalisierter Name, Value: Schöner Originalname
    for f in festivals:
        for b in f.get("bands", []):
            norm = normalize_band_name(b)
            if norm and norm not in raw_band_map:
                raw_band_map[norm] = b

    sorted_normalized_bands = sorted(raw_band_map.keys(), key=lambda s: s.lower())
    display_bands_map = {norm: raw_band_map[norm] for norm in sorted_normalized_bands}

    # --- SIDEBAR: FILTER & EINSTELLUNGEN ---
    st.sidebar.header("📍 1. Standort & Filter")
    user_plz = st.sidebar.text_input("Deine PLZ (Deutschland/EU):", value="70173")
    
    max_dist_km = st.sidebar.slider("Maximale Entfernung (km):", min_value=10, max_value=1500, value=500, step=10)
    max_price = st.sidebar.slider("Maximaler Preis (€):", min_value=0, max_value=500, value=350, step=10)
    
    today = date.today()
    start_date_filter = st.sidebar.date_input("Festival ab Datum:", value=today)

    st.sidebar.header("🎯 2. Band-Gewichtung")
    st.sidebar.markdown("Standard-Bands haben einfaches Gewicht (**1x**). Bands in der Favoriten-Liste zählen **doppelt (2x)**.")

    # --- HAUPTBEREICH: BAND-AUSWAHL ---
    st.subheader("🎵 Wähle deine Bands aus")
    
    selected_norm_bands = st.multiselect(
        "Suche und wähle Bands aus:",
        options=sorted_normalized_bands,
        format_func=lambda x: display_bands_map[x]
    )

    double_weighted_norm_bands = []
    if selected_norm_bands:
        double_weighted_norm_bands = st.multiselect(
            "⭐ Diese ausgewählten Bands doppelt gewichten (Favoriten):",
            options=selected_norm_bands,
            format_func=lambda x: display_bands_map[x]
        )

    # --- GEODATEN BERECHNEN ---
    user_coords = get_coordinates(user_plz)
    if not user_coords and user_plz:
        st.warning(f"PLZ '{user_plz}' konnte nicht verortet werden. Distanzfilter wird ignoriert.")

    # --- MATCHING-LOGIK ---
    if st.button("🚀 Festivals auswerten", type="primary") or selected_norm_bands:
        if not selected_norm_bands:
            st.info("Bitte wähle mindestens eine Band aus, um das Matching zu starten.")
        else:
            # Maximal mögliche Punkte berechnen
            total_possible_score = sum(2 if b in double_weighted_norm_bands else 1 for b in selected_norm_bands)

            results = []

            for f in festivals:
                # 1. Datums-Filter
                f_date = parse_start_date(f.get("datum", ""))
                if f_date and f_date < start_date_filter:
                    continue

                # 2. Preis-Filter
                f_price = parse_price(f.get("preis", ""))
                if f_price > 0 and f_price > max_price:
                    continue

                # 3. Entfernungs-Filter
                f_dist = None
                if user_coords and f.get("plz") != "N/A":
                    f_coords = get_coordinates(f.get("plz"), f.get("land", "Deutschland"))
                    if f_coords:
                        f_dist = round(geodesic(user_coords, f_coords).km, 1)
                        if f_dist > max_dist_km:
                            continue

                # 4. Band-Score berechnen
                f_bands_norm = {normalize_band_name(b) for b in f.get("bands", [])}
                
                matched_score = 0
                matched_bands_display = []

                for b in selected_norm_bands:
                    if b in f_bands_norm:
                        weight = 2 if b in double_weighted_norm_bands else 1
                        matched_score += weight
                        matched_bands_display.append(display_bands_map[b])

                match_percentage = round((matched_score / total_possible_score) * 100, 1)

                if match_percentage > 0:
                    results.append({
                        "details": f,
                        "match_percentage": match_percentage,
                        "matched_count": len(matched_bands_display),
                        "matched_bands": matched_bands_display,
                        "distance_km": f_dist,
                        "price_val": f_price
                    })

            # Ergebnisse nach Prozentualer Übereinstimmung absteigend sortieren
            results.sort(key=lambda x: x["match_percentage"], reverse=True)

            # --- ERGEBNIS-ANZEIGE ---
            st.markdown("---")
            st.subheader(f"📊 Auswertung ({len(results)} passende Festivals gefunden)")

            if not results:
                st.warning("Keine Festivals gefunden, die zu deinen Filterkriterien und Bandauswahlen passen.")
            else:
                for item in results:
                    f = item["details"]
                    match_pct = item["match_percentage"]
                    dist_str = f"{item['distance_km']} km" if item['distance_km'] is not None else "N/A"
                    
                    with st.expander(f"**{f['name']}** — Match: **{match_pct}%** ({item['matched_count']} Bands)", expanded=(match_pct >= 50)):
                        col1, col2 = st.columns([1, 2])
                        
                        with col1:
                            st.write(f"📅 **Datum:** {f.get('datum', 'N/A')}")
                            st.write(f"💰 **Preis:** {f.get('preis', 'N/A')}")
                            st.write(f"📍 **Ort:** {f.get('location', 'N/A')}, {f.get('plz', '')} {f.get('ort', 'N/A')} ({f.get('land', '')})")
                            st.write(f"🚗 **Entfernung:** {dist_str}")
                            
                            if f.get("webseite") and f.get("webseite") != "N/A":
                                st.markdown(f"🔗 [Zur offiziellen Website]({f['webseite']})")

                        with col2:
                            st.write("🎯 **Gefundene Bands:**")
                            st.write(", ".join(item["matched_bands"]))
                            
                            with st.popover("Gesamtes Lineup anzeigen"):
                                st.write(", ".join(f.get("bands", [])))

# --- FUSSZEILE ---
st.markdown("<br><hr>", unsafe_allow_html=True)
st.markdown(
    f"<div style='text-align: center; color: gray; font-size: 0.85em;'>"
    f"Festival-Datenbank Stand: <b>{last_update}</b> | Automatisch aktualisiert via GitHub Actions"
    f"</div>",
    unsafe_allow_html=True
)
