import re
import json
import html as html_lib
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

# ---------------------------------------------------------------------------
# 1. FESTIVAL-MAPPING MIT DEN EXAKTEN URLS
# ---------------------------------------------------------------------------

FESTIVAL_URL_MAP = {
    "Aalborg Metal Festival": "https://www.festivalticker.de/festivals/aalborg_metalfestival/",
    "Alcatraz Festival": "https://www.festivalticker.de/festivals/alcatraz_festival/",
    "Amphi Festival": "https://www.festivalticker.de/festivals/amphi_festival/",
    "Azkena Rock Festival": "https://www.festivalticker.de/festivals/azkena_rock/",
    "Baden in Blut Festival": "https://www.festivalticker.de/festivals/baden_in_blut/",
    "Bang Your Head!!!": "https://www.festivalticker.de/festivals/rvbang_festival/",
    "Barcelona Rock Fest": "https://www.festivalticker.de/festivals/rock_fest_barcelona/",
    "Basinfirefest": "https://www.festivalticker.de/festivals/basinfirefest/",
    "Best Kept Secret Festival": "https://www.festivalticker.de/festivals/best_kept_secret/",
    "Bloodstock Open Air": "https://www.festivalticker.de/festivals/bloodstock_open_air/",
    "Bochum Total": "https://www.festivalticker.de/festivals/bochum_total/",
    "Brutal Assault": "https://www.festivalticker.de/festivals/brutal_assault/",
    "Castle Party Festival": "https://www.festivalticker.de/festivals/castle_party_festival/",
    "Chronical Moshers Open Air": "https://www.festivalticker.de/festivals/chronical_moshers_open_air/",
    "Copenhell": "https://www.festivalticker.de/festivals/copenhell/",
    "Damnation Festival": "https://www.festivalticker.de/festivals/damnation_festival/",
    "Dark Easter Metal Meeting": "https://www.festivalticker.de/festivals/dark_easter_metal_meeting/",
    "Deichbrand Festival": "https://www.festivalticker.de/festivals/deichbrand/",
    "Desertfest Berlin": "https://www.festivalticker.de/festivals/desertfest/",
    "Dong Open Air": "https://www.festivalticker.de/festivals/dong_open_air/",
    "Download Festival": "https://www.festivalticker.de/festivals/download_festival/",
    "Dynamo Metalfest": "https://www.festivalticker.de/festivals/dynamo_metal_fest/",
    "Eindhoven Metal Meeting": "https://www.festivalticker.de/festivals/eindhoven_metal_meeting/",
    "Electric Picnic": "https://www.festivalticker.de/festivals/electric_picnic/",
    "EXIT Festival": "https://www.festivalticker.de/festivals/exit_festival/",
    "Frequency Festival": "https://www.festivalticker.de/festivals/fm4_frequency/",
    "Full Force": "https://www.festivalticker.de/festivals/with_full_force/",
    "Full Metal Cruise": "https://www.festivalticker.de/festivals/full_metal_cruise_2/",
    "Gefle Metal Festival": "https://www.festivalticker.de/festivals/gefle_metal_festival/",
    "Glastonbury Festival": "https://www.festivalticker.de/festivals/glastonbury_festival/",
    "Graspop Metal Meeting": "https://www.festivalticker.de/festivals/graspop_metal_meeting/",
    "Greenfield Festival": "https://www.festivalticker.de/festivals/greenfield_festival/",
    "Headbangers Open Air": "https://www.festivalticker.de/festivals/headbangers_open_air/",
    "Hellfest Open Air": "https://www.festivalticker.de/festivals/hellfest/",
    "Highfield Festival": "https://www.festivalticker.de/festivals/highfield/",
    "HRH Metal": "https://www.festivalticker.de/festivals/hrh_metal/",
    "Hurricane Festival": "https://www.festivalticker.de/festivals/hurricane/",
    "In Flammen Open Air": "https://www.festivalticker.de/festivals/in_flammen_open_air/",
    "Isle of Wight Festival": "https://www.festivalticker.de/festivals/isle_of_wight_festival/",
    "Keep It True Festival": "https://www.festivalticker.de/festivals/keep_it_true/",
    "Leeds Festival": "https://www.festivalticker.de/festivals/carling_weekend_leeds/",
    "Lowlands": "https://www.festivalticker.de/festivals/lowlands/",
    "M'era Luna": "https://www.festivalticker.de/festivals/mera_luna/",
    "Mahagoni Festival": "https://www.festivalticker.de/festivals/mahagoni_festival/",
    "Mammothfest": "https://www.festivalticker.de/festivals/mammothfest/",
    "Masters of Rock": "https://www.festivalticker.de/festivals/masters_of_rock/",
    "Metal Frenzy Open Air": "https://www.festivalticker.de/festivals/metal_frenzy_open_air/",
    "MetalGate Czech Death Fest": "https://www.festivalticker.de/festivals/metalgate/",
    "Metalacker Tennenbronn": "https://www.festivalticker.de/festivals/metalacker_tennenbronn/",
    "Metalfest Open Air Plzeň": "https://www.festivalticker.de/festivals/metalfest_open_air_cz/",
    "Metalhead Meeting": "https://www.festivalticker.de/festivals/metalhead_meeting/",
    "Metalmania": "https://www.festivalticker.de/festivals/metal_menia_open_air/",
    "Motocultor Festival": "https://www.festivalticker.de/festivals/motocultor_festival/",
    "Mystic Festival": "https://www.festivalticker.de/festivals/mysticfestival/",
    "Neuborn Open Air Festival": "https://www.festivalticker.de/festivals/neuborn_open_air/",
    "Nord Open Air": "https://www.festivalticker.de/festivals/nord_open_air/",
    "Nova Rock Festival": "https://www.festivalticker.de/festivals/nova_rock/",
    "Obscene Extreme": "https://www.festivalticker.de/festivals/obscene_extreme/",
    "Open Air St. Gallen": "https://www.festivalticker.de/festivals/open_air_st_gallen/",
    "Party.San Metal Open Air": "https://www.festivalticker.de/festivals/partysan_open_air/",
    "Pinkpop": "https://www.festivalticker.de/festivals/pinkpop/",
    "Pol'and'Rock Festival": "https://www.festivalticker.de/festivals/haltestelle_woodstock/",
    "Primavera Sound": "https://www.festivalticker.de/festivals/primavera_sound/",
    "Prophecy Fest": "https://www.festivalticker.de/festivals/prophecy_fest/",
    "Protzen Open Air": "https://www.festivalticker.de/festivals/protzen_open_air/",
    "Provinssi": "https://www.festivalticker.de/festivals/provinssirock/",
    "Ragnarök Festival": "https://www.festivalticker.de/festivals/ragnaroek_festival/",
    "Reading Festival": "https://www.festivalticker.de/festivals/carling_weekend_reading/",
    "Reload Festival": "https://www.festivalticker.de/festivals/reloadfestival/",
    "Resurrection Fest": "https://www.festivalticker.de/festivals/resurrection_fest/",
    "Roadburn Festival": "https://www.festivalticker.de/festivals/roadburn_festival/",
    "Rock Hard Festival": "https://www.festivalticker.de/festivals/rock_hard_festival/",
    "Rock Wave Festival": "https://www.festivalticker.de/festivals/rockwave_festival_2/",
    "Rock Werchter": "https://www.festivalticker.de/festivals/rock_werchter/",
    "Rock am Ring": "https://www.festivalticker.de/festivals/rock_am_ring/",
    "Rock en Seine": "https://www.festivalticker.de/festivals/rock_en_seine/",
    "Rock for People": "https://www.festivalticker.de/festivals/rock_for_people/",
    "Rock im Park": "https://www.festivalticker.de/festivals/rock_im_park/",
    "Rock in Rio Lisboa": "https://www.festivalticker.de/festivals/rock_in_rio_lisboa/",
    "Rock unter den Eichen": "https://www.festivalticker.de/festivals/rock_unter_den_eichen/",
    "Rockharz Open Air": "https://www.festivalticker.de/festivals/rock_harz_open_air/",
    "Roskilde Festival": "https://www.festivalticker.de/festivals/roskilde_festival/",
    "Slam Dunk Festival": "https://www.festivalticker.de/festivals/slam_dunk_festival_hatfield/",
    "SonicBlast Fest": "https://www.festivalticker.de/festivals/sonic_blast_festival/",
    "Southside Festival": "https://www.festivalticker.de/festivals/southside-festival/",
    "Stoned from the Underground": "https://www.festivalticker.de/festivals/stoned_from_the_underground/",
    "Summer Breeze Open Air": "https://www.festivalticker.de/festivals/summer_breeze/",
    "Sweden Rock Festival": "https://www.festivalticker.de/festivals/sweden_rock/",
    "SWR Barroselas Metalfest": "https://www.festivalticker.de/festivals/swr_barroselas_metalfest/",
    "Tons of Rock": "https://www.festivalticker.de/festivals/tons_of_rock/",
    "Turock Open Air": "https://www.festivalticker.de/festivals/turock_open_air/",
    "Tuska Open Air": "https://www.festivalticker.de/festivals/tuska_festival/",
    "Vodafone Paredes de Coura": "https://www.festivalticker.de/festivals/paredes_de_coura_festival/",
    "Wacken Open Air": "https://www.festivalticker.de/festivals/wacken_open_air/",
    "Way Out West": "https://www.festivalticker.de/festivals/way_out_west/",
    "Zwarte Cross": "https://www.festivalticker.de/festivals/zwarte_cross/"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

# ---------------------------------------------------------------------------
# 2. EXTRAKTIONS-LOGIK (DATUM, PREIS, PLZ, ORT, WEBSEITE, BANDS)
# ---------------------------------------------------------------------------

def scrape_festival_details(festival_name: str, url: str) -> dict:
    data = {
        "name": festival_name,
        "url_ticker": url,
        "datum": "N/A",
        "preis": "N/A",
        "location": "N/A",
        "plz": "N/A",
        "ort": "N/A",
        "land": "N/A",
        "webseite": "N/A",
        "bands": []
    }

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return data

        raw_html = html_lib.unescape(resp.text)
        # HTML Normalisierung: Ersetzt Umbrüche/Tabs & non-breaking spaces durch reguläre Leerzeichen
        html = re.sub(r'[\xa0\t\r\n]+', ' ', raw_html)

        # --- 1. DATUM ---
        m_datum = re.search(r'Vom:\s*([\d\.]+)\s*bis:\s*([\d\.]+)', html, re.IGNORECASE)
        if m_datum:
            data["datum"] = f"{m_datum.group(1)} bis {m_datum.group(2)}"
        else:
            m_datum_single = re.search(r'Am:\s*([\d\.]+)', html, re.IGNORECASE)
            if m_datum_single:
                data["datum"] = m_datum_single.group(1)

        # --- 2. PREIS ---
        m_preis = re.search(r'<strong>\s*Preis:\s*</strong>\s*</td>\s*<td[^>]*>(.*?)</td>', html, re.IGNORECASE)
        if m_preis:
            cleaned_preis = re.sub(r'<[^>]+>', '', m_preis.group(1)).strip()
            data["preis"] = cleaned_preis if cleaned_preis else "N/A"

        # --- 3. LOCATION, PLZ, ORT, LAND ---
        m_loc_block = re.search(r'<div\s+class=["\']location["\']>(.*?)</div>', html, re.IGNORECASE)
        if m_loc_block:
            loc_html = m_loc_block.group(1)
            
            m_loc = re.search(r'<strong>\s*Location:\s*</strong>\s*</td>\s*<td[^>]*>(.*?)</td>', loc_html, re.IGNORECASE)
            if m_loc: data["location"] = re.sub(r'<[^>]+>', '', m_loc.group(1)).strip()
            
            m_plz = re.search(r'<strong>\s*Plz:\s*</strong>\s*</td>\s*<td[^>]*>(.*?)</td>', loc_html, re.IGNORECASE)
            if m_plz:
                plz_val = re.sub(r'<[^>]+>', '', m_plz.group(1)).strip()
                data["plz"] = plz_val if plz_val else "N/A"

            m_ort = re.search(r'<strong>\s*Ort:\s*</strong>\s*</td>\s*<td[^>]*>(.*?)</td>', loc_html, re.IGNORECASE)
            if m_ort: data["ort"] = re.sub(r'<[^>]+>', '', m_ort.group(1)).strip()

            m_land = re.search(r'<strong>\s*Land:\s*</strong>\s*</td>\s*<td[^>]*>(.*?)</td>', loc_html, re.IGNORECASE)
            if m_land: data["land"] = re.sub(r'<[^>]+>', '', m_land.group(1)).strip()

        # --- 4. OFFIZIELLE WEBSEITE ---
        m_web = re.search(r'<strong>\s*Website:\s*</strong>\s*</td>\s*<td[^>]*>\s*<a\s+[^>]*href=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if m_web:
            data["webseite"] = m_web.group(1).strip()

        # --- 5. BANDS (VARIANTE A & B) ---
        bands_text = ""
        m_bands_same = re.search(r'<strong>\s*Bands:\s*</strong>\s*(?:<br\s*/?>)*(.*?)\s*</td>', html, re.IGNORECASE)
        if m_bands_same and m_bands_same.group(1).strip():
            bands_text = m_bands_same.group(1)
        else:
            m_bands_next = re.search(r'<strong>\s*Bands:\s*</strong>.*?</tr>\s*<tr>\s*<td[^>]*>(?:<br\s*/?>)*(.*?)(?:<br\s*/?>)*</td>', html, re.IGNORECASE)
            if m_bands_next:
                bands_text = m_bands_next.group(1)

        if bands_text:
            cleaned_bands = re.sub(r'<[^>]+>', '', bands_text).strip()
            if cleaned_bands:
                data["bands"] = [b.strip() for b in cleaned_bands.split(",") if b.strip()]

    except Exception as e:
        print(f"Fehler bei {festival_name} ({url}): {e}")

    return data

# ---------------------------------------------------------------------------
# 3. MULTITHREADING PIPELINE & EXPORT
# ---------------------------------------------------------------------------

def run_scraper(max_workers: int = 12):
    results = []

    print(f"[1/2] Starte Scraper für {len(FESTIVAL_URL_MAP)} zugewiesene Festivals mit {max_workers} Threads...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(scrape_festival_details, name, url): name 
            for name, url in FESTIVAL_URL_MAP.items()
        }
        
        for future in as_completed(futures):
            res = future.result()
            results.append(res)
            print(f"✓ {res['name']:<30} | Datum: {res['datum']:<23} | PLZ: {res['plz']:<8} | Bands: {len(res['bands'])}")

    print(f"\n[2/2] Abgeschlossen. {len(results)} Festivals verarbeitet.")

    # JSON Export (Ideal für Streamlit)
    with open("festivals_data.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # CSV Export
    df = pd.DataFrame(results)
    df["bands_str"] = df["bands"].apply(lambda b: ", ".join(b))
    df.to_csv("festivals_data.csv", index=False, encoding="utf-8-sig")

    print("-> Daten gespeichert in 'festivals_data.json' & 'festivals_data.csv'")

if __name__ == "__main__":
    run_scraper(max_workers=12)
