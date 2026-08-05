import streamlit as st
import json
import os
import re
from datetime import datetime, date
import math

# ---------------------------------------------------------------------------
# 1. HELFER-FUNKTIONEN: DATA LOADING & BAND-NORMALISIERUNG
# ---------------------------------------------------------------------------

def normalize_band_name(name: str) -> str:
    """Standardisiert Bandnamen für den Vergleich."""
    clean = name.strip()
    clean = re.sub(r'\s+', ' ', clean)
    return clean

@st.cache_data(ttl=86400)
def load_festival_data():
    """Lädt die gecrawlten Festival-Daten und ermittelt das Änderungsdatum."""
    file_path = "festivals_data.json"
    if not os.path.exists(file_path):
        return [], "Noch keine Daten vorhanden (Scraper muss zuerst ausgeführt werden)"

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        mod_time = os.path.getmtime(file_path)
        last_update_str = datetime.fromtimestamp(mod_time).strftime("%d.%m.%Y um %H:%M Uhr")
        return data, last_update_str
    except Exception as e:
        return [], f"Fehler beim Laden der Datei: {e}"

def parse_price(preis_str: str) -> float:
    """Extrahiert den ersten numerischen Preis aus dem Preistext."""
    if not preis_str or preis_str == "N/A":
        return 0.0
    match = re.search(r'(\d+[\.,]?\d*)', str(preis_str).replace(',', '.'))
    return float(match.group(1)) if match else 0.0

def parse_start_date(datum_str: str):
    """Parses the start date from 'DD.MM.YYYY bis DD.MM.YYYY' or 'DD.MM.YYYY'."""
    if not datum_str or datum_str == "N/A":
        return None
    match = re.search(r'(\d{2}\.\d{2}\.\d{4})', str(datum_str))
    if match:
        try:
            return datetime.strptime(match.group(1), "%d.%m.%Y").date()
        except ValueError:
            return None
    return None

# ---------------------------------------------------------------------------
# 2. SCHNELLE, OFFLINE GEODATEN-BERECHNUNG (OHNE API-BLOCKADEN)
# ---------------------------------------------------------------------------

# Lokales Nachschlagen deutscher PLZ-Leitzonen (Bereiche 0-9) für schnelle Koordinaten
PLZ_ZONE_COORDS = {
    "0": (51.05, 13.73), # Dresden / Sachsen
    "1": (52.52, 13.40), # Berlin / Brandenburg
    "2": (53.55, 9.99),  # Hamburg / Norddeutschland
    "3": (52.37, 9.73),  # Hannover / Niedersachsen
    "4": (51.45, 7.01),  # Essen / NRW
    "5": (50.93, 6.95),  # Köln / Rheinland
    "6": (49.48, 8.46),  # Mannheim / Hessen / RL-Pfalz (68161 fällt exakt hierher!)
    "7": (48.77, 9.18),  # Stuttgart / Baden-Württemberg
    "8": (48.13, 11.57), # München / Bayern
    "9": (49.45, 11.07), # Nürnberg / Nordbayern
}

# Koordinaten-Anker für europäische Nachbarländer
COUNTRY_COORDS = {
    "Deutschland": (51.16, 10.45),
    "Germany": (51.16, 10.45),
    "Österreich": (47.51, 14.55),
    "Austria": (47.51, 14.55),
    "Schweiz": (46.81, 8.22),
    "Switzerland": (46.81, 8.22),
    "Belgien": (50.50, 4.46),
    "Belgium": (50.50, 4.46),
    "Niederlande": (52.13, 5.29),
    "Netherlands": (52.13, 5.29),
    "Polen": (51.91, 19.14),
    "Poland": (51.91, 19.14),
    "Tschechien": (49.81, 15.47),
    "Czech Republic": (49.81, 15.47),
    "Tschechische Republik": (49.81, 15.47),
    "Frankreich": (46.22, 2.21),
    "France": (46.22, 2.21),
    "Spanien": (40.46, -3.74),
    "Spain": (40.46, -3.74),
    "Großbritannien": (55.37, -3.43),
    "United Kingdom": (55.37, -3.43),
    "UK": (55.37, -3.43),
    "Norwegen": (60.47, 8.46),
    "Norway": (60.47, 8.46),
    "Schweden": (60.12, 18.64),
    "Sweden": (60.12, 18.64),
    "Finnland": (61.92, 25.74),
    "Finland": (61.92, 25.74)
}

def get_coordinates(plz: str, land: str = "Deutschland"):
    """
    Berechnet Koordinaten zu 100% lokal, ohne Netzwerk-Requests und ohne Fehler.
    """
    if not plz or str(plz).strip() in ["N/A", "None", ""]:
        # Fallback auf Landeskoordinaten
        return COUNTRY_COORDS.get(land, COUNTRY_COORDS["Deutschland"])

    clean_plz = re.sub(r'[^0-9]', '', str(plz)).strip()
    
    # Wenn deutsche PLZ (5 Stellen oder Zone vorhanden)
    if clean_plz and len(clean_plz) >= 1:
        first_digit = clean_plz[0]
        if first_digit in PLZ_ZONE_COORDS and (not land or land in ["Deutschland", "Germany"]):
            return PLZ_ZONE_COORDS[first_digit]

    # Sonst Land-Mittelpunkt zurückgeben
    return COUNTRY_COORDS.get(land, COUNTRY_COORDS["Deutschland"])

def calculate_distance(coords1, coords2):
    """Berechnet die Entfernung in km via Haversine-Formel (Offline)."""
    if not coords1 or not coords2:
        return None
    lat1, lon1 = coords1
    lat2, lon2 = coords2
    R = 6371.0  # Erdradius in km

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 1)

# ---------------------------------------------------------------------------
# 3. STREAMLIT UI BUILDER
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
    raw_band_map = {}
    for f in festivals:
        for b in f.get("bands", []):
            norm = normalize_band_name(b)
            if norm and norm not in raw_band_map:
                raw_band_map[norm] = b

    sorted_normalized_bands = sorted(raw_band_map.keys(), key=lambda s: s.lower())
    display_bands_map = {norm: raw_band_map[norm] for norm in sorted_normalized_bands}

    # --- SIDEBAR: FILTER & EINSTELLUNGEN ---
    st.sidebar.header("📍 1. Standort & Filter")
    user_plz = st.sidebar.text_input("Deine PLZ (Deutschland/EU):", value="68161")
    
    max_dist_km = st.sidebar.slider("Maximale Entfernung (km):", min_value=10, max_value=2000, value=800, step=10)
    max_price = st.sidebar.slider("Maximaler Preis (€):", min_value=0, max_value=600, value=400, step=10)
    
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

    # --- MATCHING-LOGIK ---
    if st.button("🚀 Festivals auswerten", type="primary") or selected_norm_bands:
        if not selected_norm_bands:
            st.info("Bitte wähle mindestens eine Band aus, um das Matching zu starten.")
        else:
            user_coords = get_coordinates(user_plz, "Deutschland")

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
                f_coords = get_coordinates(f.get("plz"), f.get("land", "Deutschland"))
                f_dist = calculate_distance(user_coords, f_coords)
                
                if f_dist is not None and f_dist > max_dist_km:
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
                    dist_str = f"ca. {item['distance_km']} km" if item['distance_km'] is not None else "N/A"
                    
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
