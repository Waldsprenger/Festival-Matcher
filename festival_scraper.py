import json
import os
import re
import time
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

CACHE_FILE = "plz_cache.json"

def load_plz_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Fehler beim Laden des Cache: {e}")
            return {}
    return {}

def save_plz_cache(cache):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"[!] Fehler beim Speichern des Cache: {e}")

PLZ_CACHE = load_plz_cache()

# Nominatim Geocoder initialisieren
geolocator = Nominatim(user_agent="festival_finder_app_v2")

def clean_text(text):
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def extract_plz_ort(text):
    if not text:
        return None, None
    
    # 1. Deutsche/Österreichische PLZ (5 Stellen)
    match = re.search(r'\b(\d{5})\s+([^,\n\r]+)', text)
    if match:
        return match.group(1).strip(), clean_text(match.group(2))
    
    # 2. Schweizer PLZ (4 Stellen)
    match_ch = re.search(r'\b(\d{4})\s+([^,\n\r]+)', text)
    if match_ch:
        return match_ch.group(1).strip(), clean_text(match_ch.group(2))
        
    return None, clean_text(text)

def get_coordinates_safe(plz, land, ort):
    plz_str = clean_text(str(plz)) if plz else ""
    ort_str = clean_text(str(ort)) if ort else ""
    land_str = clean_text(str(land)) if land else "Deutschland"

    cache_key = f"{plz_str}_{ort_str}_{land_str}"
    
    if cache_key in PLZ_CACHE:
        val = PLZ_CACHE[cache_key]
        if isinstance(val, dict):
            return val.get("lat"), val.get("lon")
        elif isinstance(val, (list, tuple)) and len(val) == 2:
            return val[0], val[1]

    # Strikte Pause zur Einhaltung der Nominatim Nützenrichtlinien (Max 1 Req/Sek)
    time.sleep(1.1)

    # Suchversuche (vom Spezifischen zum Allgemeinen)
    queries = []
    if plz_str and ort_str:
        queries.append(f"{plz_str} {ort_str}, {land_str}")
    if ort_str:
        queries.append(f"{ort_str}, {land_str}")
    if plz_str:
        queries.append(f"{plz_str}, {land_str}")

    for query in queries:
        try:
            location = geolocator.geocode(query, timeout=10)
            if location:
                PLZ_CACHE[cache_key] = {"lat": location.latitude, "lon": location.longitude}
                return location.latitude, location.longitude
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            print(f"    [!] Geocoding-Timeout/Fehler bei '{query}': {e}")
            time.sleep(2)
        except Exception as e:
            print(f"    [!] Unerwarteter Geocoding-Fehler bei '{query}': {e}")

    # Falls nichts gefunden wurde -> None eintragen & im Cache vermerken
    PLZ_CACHE[cache_key] = {"lat": None, "lon": None}
    return None, None

def scrape_festival_checker():
    print("[+] 1. Starte Web-Scraping von Festival-Checker...")
    url = "https://www.festival-checker.de/festivals/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"[!] Fehler beim Laden der Webseite: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    festival_cards = soup.find_all("div", class_="festival-card") 
    
    if not festival_cards:
        festival_cards = soup.find_all("article")

    print(f"    -> {len(festival_cards)} potenzielle Festival-Karten gefunden.")

    results = []

    for card in festival_cards:
        try:
            name_el = card.find(["h2", "h3", "h4"], class_=re.compile(r'title|name', re.I)) or card.find(["h2", "h3", "h4"])
            if not name_el:
                continue
            name = clean_text(name_el.text)
            
            link_el = card.find("a", href=True)
            link = link_el["href"] if link_el else ""

            date_el = card.find(class_=re.compile(r'date|zeit', re.I))
            datum_str = clean_text(date_el.text) if date_el else ""

            loc_el = card.find(class_=re.compile(r'location|ort|place', re.I))
            location_raw = clean_text(loc_el.text) if loc_el else ""

            genre_el = card.find(class_=re.compile(r'genre|style|category', re.I))
            genre = clean_text(genre_el.text) if genre_el else "Verschiedenes"

            plz, ort = extract_plz_ort(location_raw)

            land = "Deutschland"
            if "Österreich" in location_raw or "Austria" in location_raw:
                land = "Österreich"
            elif "Schweiz" in location_raw or "Switzerland" in location_raw:
                land = "Schweiz"

            results.append({
                "name": name,
                "link": link,
                "datum_raw": datum_str,
                "location_raw": location_raw,
                "plz": plz,
                "ort": ort,
                "land": land,
                "genre": genre,
                "lat": None,
                "lon": None
            })
        except Exception as e:
            continue

    print(f"[+] Scraping abgeschlossen. {len(results)} Festivals verarbeitet.")
    return results

def main():
    results = scrape_festival_checker()
    if not results:
        print("[!] Keine Festivals gefunden.")
        return

    output_filename = "festivals.json"
    print(f"\n[+] 2. Ermittle Geokoordinaten für {len(results)} Festivals...")

    for idx, item in enumerate(results, 1):
        name = item.get("name")
        print(f"[{idx}/{len(results)}] Verarbeite: {name} ({item.get('ort') or 'Unbekannter Ort'})")
        
        lat, lon = get_coordinates_safe(item.get("plz"), item.get("land", "Deutschland"), item.get("ort"))
        item["lat"] = lat
        item["lon"] = lon

        # Fortlaufendes Speichern (verhindert Datenverlust bei Abbruch)
        save_plz_cache(PLZ_CACHE)
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=4)

    print("\n[✔] Fertig! Festivals und Geokoordinaten wurden erfolgreich gespeichert.")

if __name__ == "__main__":
    main()
