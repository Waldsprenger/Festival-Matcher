import streamlit as st
import json
import os
import re
from datetime import datetime, date
import math

# ---------------------------------------------------------------------------
# 1. PAGE CONFIG & METAL-THEME CUSTOM CSS
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Festival Matcher 🤘", 
    page_icon="🤘", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS für den Metal-Vibe und das Favoriten-Highlighting
st.markdown("""
<style>
    /* Haupt-Hintergrund & Textfarben */
    .stApp {
        background-color: #121212;
        color: #E0E0E0;
    }
    
    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background-color: #1A1A1A;
        border-right: 1px solid #333333;
    }

    /* Überschriften */
    h1, h2, h3 {
        color: #D32F2F !important;
        font-family: 'Trebuchet MS', sans-serif;
        text-shadow: 1px 1px 2px #000000;
    }

    /* Badges für Prozentzahlen */
    .badge-high {
        background-color: #2E7D32;
        color: #FFFFFF;
        padding: 4px 10px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 1.1em;
    }
    .badge-mid {
        background-color: #E65100;
        color: #FFFFFF;
        padding: 4px 10px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 1.1em;
    }
    .badge-low {
        background-color: #C62828;
        color: #FFFFFF;
        padding: 4px 10px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 1.1em;
    }

    /* Favoriten Band Badge (Goldener Hintergrund ohne Stern) */
    .fav-band-badge {
        background-color: #FFD700;
        color: #000000;
        padding: 2px 8px;
        border-radius: 4px;
        font-weight: bold;
        display: inline-block;
        margin: 2px;
        border: 1px solid #FFA000;
    }

    /* Normale Band Badge */
    .normal-band-badge {
        background-color: #333333;
        color: #E0E0E0;
        padding: 2px 8px;
        border-radius: 4px;
        display: inline-block;
        margin: 2px;
        border: 1px solid #555555;
    }

    /* Primary Button Customization */
    div.stButton > button[kind="primary"] {
        background-color: #B71C1C;
        color: white;
        border: none;
        font-weight: bold;
        letter-spacing: 1px;
        transition: all 0.3s ease;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: #D32F2F;
        box-shadow: 0 0 10px #D32F2F;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 2. HELFER-FUNKTIONEN: DATA LOADING & BAND-NORMALISIERUNG
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
        return 9999.0  # Fallback für Sortierung
    match = re.search(r'(\d+[\.,]?\d*)', str(preis_str).replace(',', '.'))
    return float(match.group(1)) if match else 9999.0

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
# 3. GEODATEN-BERECHNUNG (OFFLINE & SCHNELL)
# ---------------------------------------------------------------------------

PLZ_ZONE_COORDS = {
    "0": (51.05, 13.73), "1": (52.52, 13.40), "2": (53.55, 9.99),
    "3": (52.37, 9.73),  "4": (51.45, 7.01),  "5": (50.93, 6.95),
    "6": (49.48, 8.46),  "7": (48.77, 9.18),  "8": (48.13, 11.57),
    "9": (49.45, 11.07),
}

COUNTRY_COORDS = {
    "Deutschland": (51.16, 10.45), "Germany": (51.16, 10.45),
    "Österreich": (47.51, 14.55), "Austria": (47.51, 14.55),
    "Schweiz": (46.81, 8.22), "Switzerland": (46.81, 8.22),
    "Belgien": (50.50, 4.46), "Belgium": (50.50, 4.46),
    "Niederlande": (52.13, 5.29), "Netherlands": (52.13, 5.29),
    "Polen": (51.91, 19.14), "Poland": (51.91, 19.14),
    "Tschechien": (49.81, 15.47), "Czech Republic": (49.81, 15.47),
    "Frankreich": (46.22, 2.21), "France": (46.22, 2.21),
    "Spanien": (40.46, -3.74), "Spain": (40.46, -3.74),
    "Großbritannien": (55.37, -3.43), "United Kingdom": (55.37, -3.43),
    "Norwegen": (60.47, 8.46), "Schweden": (60.12, 18.64), "Finnland": (61.92, 25.74)
}

def get_coordinates(plz: str, land: str = "Deutschland"):
    if not plz or str(plz).strip() in ["N/A", "None", ""]:
        return COUNTRY_COORDS.get(land, COUNTRY_COORDS["Deutschland"])

    clean_plz = re.sub(r'[^0-9]', '', str(plz)).strip()
    if clean_plz and len(clean_plz) >= 1:
        first_digit = clean_plz[0]
        if first_digit in PLZ_ZONE_COORDS and (not land or land in ["Deutschland", "Germany"]):
            return PLZ_ZONE_COORDS[first_digit]

    return COUNTRY_COORDS.get(land, COUNTRY_COORDS["Deutschland"])

def calculate_distance(coords1, coords2):
    if not coords1 or not coords2:
        return 9999.0
    lat1, lon1 = coords1
    lat2, lon2 = coords2
    R = 6371.0

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 1)

# ---------------------------------------------------------------------------
# 4. STREAMLIT UI BUILDER
# ---------------------------------------------------------------------------

st.title("🤘 METAL & ROCK FESTIVAL MATCHING")
st.markdown("Finde heraus, welches Festival deinen Lineup-Geschmack am besten trifft!")

festivals, last_update = load_festival_data()

if not festivals:
    st.warning("⚠️ Keine Festival-Daten gefunden. Bitte führe zuerst den Scraper aus.")
else:
    # Band-Liste vorbereiten
    raw_band_map = {}
    for f in festivals:
        for b in f.get("bands", []):
            norm = normalize_band_name(b)
            if norm and norm not in raw_band_map:
                raw_band_map[norm] = b

    sorted_normalized_bands = sorted(raw_band_map.keys(), key=lambda s: s.lower())
    display_bands_map = {norm: raw_band_map[norm] for norm in sorted_normalized_bands}

    # --- SIDEBAR ---
    st.sidebar.header("📍 1. Standort & Kriterien")
    user_plz = st.sidebar.text_input("Deine PLZ (Deutschland/EU):", value="", placeholder="z. B. 68161")
    
    max_dist_km = st.sidebar.slider("Max. Entfernung (km):", min_value=10, max_value=2000, value=1000, step=20)
    max_price = st.sidebar.slider("Max. Preis (€):", min_value=0, max_value=600, value=500, step=10)
    
    today = date.today()
    start_date_filter = st.sidebar.date_input("Festivals ab Datum:", value=today)

    st.sidebar.header("🎯 2. Band-Gewichtung")
    st.sidebar.markdown("Bands in deiner Favoriten-Liste zählen **doppelt (2x)** und werden **gold hinterlegt**.")

    # --- HAUPTBEREICH: BANDAUSWAHL ---
    st.subheader("🎵 Wähle deine Bands aus")
    
    selected_norm_bands = st.multiselect(
        "Deine Wunschbands:",
        options=sorted_normalized_bands,
        format_func=lambda x: display_bands_map[x],
        placeholder="Wähle Bands aus..."
    )

    double_weighted_norm_bands = []
    if selected_norm_bands:
        double_weighted_norm_bands = st.multiselect(
            "Favoriten (doppelt gewichtet & gold hinterlegt):",
            options=selected_norm_bands,
            format_func=lambda x: display_bands_map[x],
            placeholder="Wähle deine absoluten Favoriten..."
        )

    # --- MATCHING LOGIK & SORTIERUNG ---
    if st.button("🚀 FESTIVALS AUSWERTEN", type="primary") or selected_norm_bands:
        if not selected_norm_bands:
            st.info("Bitte wähle mindestens eine Band aus, um die Auswertung zu starten.")
        else:
            user_coords = get_coordinates(user_plz, "Deutschland") if user_plz else None

            total_possible_score = sum(2 if b in double_weighted_norm_bands else 1 for b in selected_norm_bands)
            results = []

            for f in festivals:
                # 1. Datum Filter
                f_date = parse_start_date(f.get("datum", ""))
                if f_date and f_date < start_date_filter:
                    continue

                # 2. Preis Filter
                f_price = parse_price(f.get("preis", ""))
                if f_price != 9999.0 and f_price > max_price:
                    continue

                # 3. Entfernung Filter
                f_coords = get_coordinates(f.get("plz"), f.get("land", "Deutschland"))
                f_dist = calculate_distance(user_coords, f_coords) if user_coords else 9999.0
                
                if user_coords and f_dist != 9999.0 and f_dist > max_dist_km:
                    continue

                # 4. Band Scoring & Favoriten-Markierung
                f_bands_norm = {normalize_band_name(b) for b in f.get("bands", [])}
                
                matched_score = 0
                matched_bands_html = []

                for b in selected_norm_bands:
                    if b in f_bands_norm:
                        is_fav = b in double_weighted_norm_bands
                        weight = 2 if is_fav else 1
                        matched_score += weight
                        
                        band_display_name = display_bands_map[b]
                        if is_fav:
                            matched_bands_html.append(f'<span class="fav-band-badge">{band_display_name}</span>')
                        else:
                            matched_bands_html.append(f'<span class="normal-band-badge">{band_display_name}</span>')

                match_percentage = round((matched_score / total_possible_score) * 100, 1)

                if match_percentage > 0:
                    results.append({
                        "details": f,
                        "match_percentage": match_percentage,
                        "matched_count": len(matched_bands_html),
                        "matched_bands_html": matched_bands_html,
                        "distance_km": f_dist if f_dist != 9999.0 else None,
                        "price_val": f_price if f_price != 9999.0 else None
                    })

            # SORTIERUNG: 1. Match % (absteigend), 2. Entfernung (aufsteigend), 3. Preis (aufsteigend)
            results.sort(key=lambda x: (
                -x["match_percentage"],
                x["distance_km"] if x["distance_km"] is not None else 99999,
                x["price_val"] if x["price_val"] is not None else 99999
            ))

            # --- ERGEBNISSE ANZEIGEN ---
            st.markdown("---")
            st.subheader(f"📊 Auswertung ({len(results)} passende Festivals)")

            if not results:
                st.warning("Keine Festivals für deine Filter- und Bandkriterien gefunden.")
            else:
                for item in results:
                    f = item["details"]
                    match_pct = item["match_percentage"]
                    
                    # Farbliches Badge für Prozentzahl
                    if match_pct >= 75:
                        badge_html = f'<span class="badge-high">{match_pct}% MATCH</span>'
                    elif match_pct >= 50:
                        badge_html = f'<span class="badge-mid">{match_pct}% MATCH</span>'
                    else:
                        badge_html = f'<span class="badge-low">{match_pct}% MATCH</span>'

                    dist_str = f"ca. {item['distance_km']} km" if item['distance_km'] is not None else "N/A"
                    price_str = f"{item['price_val']} €" if item['price_val'] is not None else f.get('preis', 'N/A')

                    with st.expander(f"🎸 {f['name']} — {match_pct}% Match ({item['matched_count']} Bands)", expanded=True):
                        st.markdown(f"### {f['name']} &nbsp; {badge_html}", unsafe_allow_html=True)
                        st.markdown("<br>", unsafe_allow_html=True)

                        col1, col2 = st.columns([1.2, 2])
                        
                        with col1:
                            st.info(f"""
                            📅 **Datum:** {f.get('datum', 'N/A')}  
                            💰 **Preis:** {price_str}  
                            📍 **Ort:** {f.get('location', 'N/A')}, {f.get('plz', '')} {f.get('ort', 'N/A')} ({f.get('land', '')})  
                            🚗 **Entfernung:** {dist_str}
                            """)
                            
                            if f.get("webseite") and f.get("webseite") != "N/A":
                                st.markdown(f"👉 [**Zur offiziellen Festival-Website**]({f['webseite']})")

                        with col2:
                            st.markdown("🎯 **Gefundene Bands:**")
                            bands_html_str = " ".join(item["matched_bands_html"])
                            st.markdown(bands_html_str, unsafe_allow_html=True)
                            st.markdown("<br>", unsafe_allow_html=True)
                            
                            with st.popover("📜 Vollständiges Lineup anzeigen"):
                                st.write(", ".join(f.get("bands", [])))

# --- FOOTER ---
st.markdown("<br><hr>", unsafe_allow_html=True)
st.markdown(
    f"<div style='text-align: center; color: #777777; font-size: 0.85em;'>"
    f"Festival-Datenbank Stand: <b>{last_update}</b> | Automatisch aktualisiert via GitHub Actions 🤘<br>"
    f"<i>Hinweis: Alle Angaben zu Preisen, Terminen und Lineups sind ohne Gewähr. Für die Vollständigkeit und Aktualität "
    f"der Daten wird keine Haftung übernommen; sie entsprechen dem jeweiligen Stand von <a href='https://www.festivalticker.de/' "
    f"target='_blank' style='color: #888888;'>Festivalticker.de</a>.</i>"
    f"</div>",
    unsafe_allow_html=True
)
