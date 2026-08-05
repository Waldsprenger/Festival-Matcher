import streamlit as st
import json
import os
import re
from datetime import datetime, date
import math
import folium
from streamlit_folium import st_folium

# ---------------------------------------------------------------------------
# 1. PAGE CONFIG & METAL-THEME CUSTOM CSS
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Festival Matcher 🤘", 
    page_icon="🤘", 
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stApp {
        background-color: #121212;
        color: #E0E0E0;
    }
    
    section[data-testid="stSidebar"] {
        background-color: #1A1A1A;
        border-right: 1px solid #333333;
    }

    h1, h2, h3 {
        color: #D32F2F !important;
        font-family: 'Trebuchet MS', sans-serif;
        text-shadow: 1px 1px 2px #000000;
    }

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

    .normal-band-badge {
        background-color: #333333;
        color: #E0E0E0;
        padding: 2px 8px;
        border-radius: 4px;
        display: inline-block;
        margin: 2px;
        border: 1px solid #555555;
    }

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
# 2. HELFER-FUNKTIONEN
# ---------------------------------------------------------------------------

def normalize_band_name(name: str) -> str:
    clean = name.strip()
    clean = re.sub(r'\s+', ' ', clean)
    return clean

@st.cache_data(ttl=86400)
def load_festival_data():
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
    if not preis_str or preis_str == "N/A":
        return 9999.0
    match = re.search(r'(\d+[\.,]?\d*)', str(preis_str).replace(',', '.'))
    return float(match.group(1)) if match else 9999.0

def parse_start_date(datum_str: str):
    if not datum_str or datum_str == "N/A":
        return None
    match = re.search(r'(\d{2}\.\d{2}\.\d{4})', str(datum_str))
    if match:
        try:
            return datetime.strptime(match.group(1), "%d.%m.%Y").date()
        except ValueError:
            return None
    return None

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

def get_dynamic_zoom(radius_km: float) -> int:
    """Berechnet dynamisch das ideale Zoom-Level basierend auf dem Radius in km."""
    if radius_km <= 50:
        return 9
    elif radius_km <= 150:
        return 8
    elif radius_km <= 300:
        return 7
    elif radius_km <= 600:
        return 6
    elif radius_km <= 1200:
        return 5
    else:
        return 4

# ---------------------------------------------------------------------------
# 3. STREAMLIT UI BUILDER
# ---------------------------------------------------------------------------

st.title("🤘 METAL & ROCK FESTIVAL MATCHING")
st.markdown("Finde heraus, welches Festival deinen Lineup-Geschmack am besten trifft!")

festivals, last_update = load_festival_data()

if not festivals:
    st.warning("⚠️ Keine Festival-Daten gefunden. Bitte führe zuerst den Scraper aus.")
else:
    raw_band_map = {}
    for f in festivals:
        for b in f.get("bands", []):
            norm = normalize_band_name(b)
            if norm and norm not in raw_band_map:
                raw_band_map[norm] = b

    sorted_normalized_bands = sorted(raw_band_map.keys(), key=lambda s: s.lower())
    display_bands_map = {norm: raw_band_map[norm] for norm in sorted_normalized_bands}

    # --- SIDEBAR: FILTER ---
    st.sidebar.header("📍 1. Standort & Kriterien")
    
    # PLZ Beispiel auf 12345 geändert
    user_plz = st.sidebar.text_input(
        "Deine PLZ:", 
        value="", 
        placeholder="z. B. 12345",
        help="Gib deine Postleitzahl ein, um Entfernungen zu den Festivals zu berechnen."
    )
    
    country_filter = st.sidebar.selectbox(
        "Länderauswahl:",
        options=["Alle Länder", "Deutschland", "Österreich", "Schweiz", "Belgien", "Niederlande", "Tschechien", "Frankreich", "Polen", "Spanien", "Großbritannien"],
        index=0,
        help="Filtert Ergebnisse gezielt nach dem Austragungsland."
    )

    max_dist_km = st.sidebar.slider(
        "Max. Entfernung (km):", 
        min_value=10, 
        max_value=2000, 
        value=800, 
        step=20,
        help="Bestimmt den maximalen Umkreis ab deinem Standort."
    )
    
    max_price = st.sidebar.slider(
        "Max. Preis (€):", 
        min_value=0, 
        max_value=600, 
        value=500, 
        step=10,
        help="Filtert Festivals, deren Ticketpreis über diesem Budget liegt."
    )
    
    today = date.today()
    start_date_filter = st.sidebar.date_input(
        "Festivals ab Datum:", 
        value=today,
        help="Wähle ein Startdatum. Wenn du ein Datum in der Vergangenheit wählst, werden auch bereits abgelaufene Festivals angezeigt."
    )

    if start_date_filter < today:
        st.sidebar.warning("⚠️ **Hinweis:** Du hast ein Datum in der Vergangenheit gewählt. Es werden auch abgelaufene Festivals angezeigt.")

    st.sidebar.header("🎯 2. Band-Gewichtung")

    # --- HAUPTBEREICH: BANDAUSWAHL & MAP ---
    st.subheader("🎵 Wähle deine Bands aus")
    
    selected_norm_bands = st.multiselect(
        "Deine Wunschbands:",
        options=sorted_normalized_bands,
        format_func=lambda x: display_bands_map[x],
        placeholder="Wähle Bands aus...",
        help="Ausgewählte Bands fließen in die Match-Prozentzahl ein."
    )

    double_weighted_norm_bands = []
    if selected_norm_bands:
        double_weighted_norm_bands = st.multiselect(
            "Favoriten (doppelt gewichtet & gold hinterlegt):",
            options=selected_norm_bands,
            format_func=lambda x: display_bands_map[x],
            placeholder="Wähle deine absoluten Favoriten...",
            help="Favoriten geben die doppelte Punkteanzahl im Algorithmus!"
        )

    # --- VISUELLE RADIUS-KARTE MIT DYNAMISCHEM ZOOM ---
    if user_plz:
        user_coords = get_coordinates(user_plz, "Deutschland")
        if user_coords:
            with st.expander("🗺️ Standort & Entfernungsradius auf der Karte anzeigen", expanded=False):
                # Dynamisches Zoom-Level anhand der ausgewählten Kilometer berechnen
                dynamic_zoom = get_dynamic_zoom(max_dist_km)
                
                m = folium.Map(location=user_coords, zoom_start=dynamic_zoom, tiles="CartoDB dark_matter")
                folium.Marker(
                    location=user_coords,
                    popup="Dein Standort",
                    icon=folium.Icon(color="red", icon="home")
                ).add_to(m)
                folium.Circle(
                    radius=max_dist_km * 1000,
                    location=user_coords,
                    color="#D32F2F",
                    fill=True,
                    fill_opacity=0.15,
                    popup=f"Radius: {max_dist_km} km"
                ).add_to(m)
                st_folium(m, width=900, height=350)

    # --- MATCHING LOGIK & SORTIERUNG ---
    if st.button("🚀 FESTIVALS AUSWERTEN", type="primary") or selected_norm_bands:
        if not selected_norm_bands:
            st.info("Bitte wähle mindestens eine Band aus, um die Auswertung zu starten.")
        else:
            user_coords = get_coordinates(user_plz, "Deutschland") if user_plz else None

            total_possible_score = sum(2 if b in double_weighted_norm_bands else 1 for b in selected_norm_bands)
            results = []

            for f in festivals:
                # 0. Länder Filter
                f_land = f.get("land", "")
                if country_filter != "Alle Länder":
                    if country_filter.lower() not in f_land.lower():
                        continue

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

# ---------------------------------------------------------------------------
# 4. FOOTER & RECHTLICHE HINWEISE
# ---------------------------------------------------------------------------

st.markdown("<br><hr>", unsafe_allow_html=True)

col_f1, col_f2 = st.columns([3, 1])

with col_f1:
    st.markdown(
        f"<div style='color: #777777; font-size: 0.85em;'>"
        f"Festival-Datenbank Stand: <b>{last_update}</b> | Automatisch aktualisiert via GitHub Actions 🤘<br>"
        f"<i>Hinweis: Alle Angaben zu Preisen, Terminen und Lineups sind ohne Gewähr (Datenquelle: Festivalticker.de). "
        f"Diese Anwendung steht in keiner Verbindung zu den genannten Festivals oder Veranstaltern.</i>"
        f"</div>",
        unsafe_allow_html=True
    )

with col_f2:
    with st.popover("⚖️ Impressum & Datenschutz"):
        st.markdown("### Impressum")
        st.markdown("""
        **Diensteanbieter gemäß § 5 DDG:**  
        [Dein Name / Name deines Projekts]  
        [Musterstraße 1]  
        [12345 Musterstadt]  
        **E-Mail:** [deine-email@beispiel.de]  
        """)
        
        st.markdown("---")
        st.markdown("### Datenschutzerklärung")
        st.markdown("""
        Beim Aufruf dieser Anwendung werden durch das Hosting über Streamlit / Snowflake technische Protokolldaten 
        (z. B. IP-Adresse, Browserversion, Zeitpunkt) verarbeitet.  
        Diese Anwendung verwendet ausschließlich **technisch notwendige Session-Cookies** (§ 25 Abs. 2 TDDDG). 
        Es findet kein Tracking oder Analyse durch Dritte statt.
        """)
        
        st.markdown("---")
        st.markdown("### Nutzungsbedingungen")
        st.markdown("""
        1. **Zweck:** Kostenloses Werkzeug zum Abgleich eigener Musikvorlieben mit Festival-Lineups.  
        2. **Keine Garantie:** Ergebnisse und Verlinkungen stellen keine Kaufberatung oder Garantie dar.  
        3. **Haftungsausschluss:** Für Richtigkeit, Verfügbarkeit oder Absagen von Festivals wird keine Haftung übernommen.
        """)
