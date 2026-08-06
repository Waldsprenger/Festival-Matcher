from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import threading
import time
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderServiceError, GeocoderTimedOut
import requests

BASE_URL = "https://www.festivalticker.de"

# Liste aller Startseiten, die gescrapt werden sollen
START_URLS = [
    "https://www.festivalticker.de/alle-festivals/",
    "https://www.festivalticker.de/festivals-2027/"
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

MAX_WORKERS = 5
CACHE_FILE = "plz_cache.json"
cache_lock = threading.Lock()
geo_lock = threading.Lock()  # Sperre für Nominatim Rate-Limiting

# Blacklist von Domains/Begriffen, die KEINE offiziellen Festivalwebseiten sind
WEBSITE_BLACKLIST = [
    "festivalticker.de",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "spotify.com",
    "donnerwetter.de",
    "wetter.de",
    "wetteronline.de",
    "wetter.com",
    "google.com",
    "wikipedia.org",
]

# Vollständige Genre-Liste
GENRE_MAPPING = {
    "Metal": [
        "metal", "heavy metal", "death metal", "black metal", "thrash metal",
        "power metal", "metalcore", "nu metal", "gothic metal", "doom metal",
        "pagan metal", "folk metal", "alternative metal"
    ],
    "Rock": [
        "rock", "hard rock", "punk rock", "indie rock", "alternative rock",
        "garage rock", "stoner rock", "post rock", "psychedelic rock",
        "deutschrock", "folk rock"
    ],
    "Punk & Hardcore": [
        "punk", "pop punk", "skatepunk", "hardcore", "post-hardcore",
        "indie punk", "garage punk", "crust", "screamo"
    ],
    "Electronic / Electro": [
        "electro", "electronic", "techno", "house", "deephouse", "techhouse",
        "psytrance", "trance", "dubstep", "drum and bass", "dnb", "edm",
        "electro pop", "brasstechno", "electronica", "gabber", "hardstyle"
    ],
    "Hip Hop / Rap": [
        "hip hop", "hiphop", "rap", "trap", "deutschrap", "urban", "rapcore"
    ],
    "Pop & Indie": ["pop", "indie", "indie pop", "synth pop", "alternative pop"],
    "Reggae & Ska": ["reggae", "ska", "dub", "dancehall", "skacore"],
    "Gothic & Wave": [
        "gothic", "darkwave", "ebm", "industrial", "wave", "post punk"
    ],
    "Folk & World": ["folk", "mittelalter", "worldmusic", "weltmusik", "country"],
    "Jazz & Blues": ["jazz", "blues", "funk", "soul"],
}

# Pre-compile Genre-Regexes für optimale Performance
COMPILED_GENRE_PATTERNS = {
    main_cat: [
        re.compile(r"(?:^|[^a-zA-Z0-9])" + re.escape(kw) + r"(?:$|[^a-zA-Z0-9])", re.IGNORECASE)
        for kw in keywords
    ]
    for main_cat, keywords in GENRE_MAPPING.items()
}


def load_plz_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Fehler beim Laden des Cache: {e}")
            return {}
    return {}


def save_plz_cache(cache):
    with cache_lock:
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Fehler beim Speichern des Cache: {e}")


PLZ_CACHE = load_plz_cache()
geolocator = Nominatim(user_agent="my_festival_scraper_app_v1.0 (waldsprenger@gmail.com)")


def get_coordinates_safe(plz: str, land: str = "Deutschland", ort: str = ""):
    if not plz and not ort:
        return None, None

    plz_str = str(plz).strip() if plz else ""
    if plz_str and len(plz_str) < 5 and plz_str.isdigit():
        plz_str = plz_str.zfill(5)

    land_str = str(land).strip() if land else "Deutschland"
    ort_str = str(ort).strip() if ort else ""

    cache_key = f"{plz_str}_{ort_str}_{land_str}"

    with cache_lock:
        if cache_key in PLZ_CACHE:
            c = PLZ_CACHE[cache_key]
            return c.get("lat"), c.get("lon")

    with geo_lock:
        with cache_lock:
            if cache_key in PLZ_CACHE:
                c = PLZ_CACHE[cache_key]
                return c.get("lat"), c.get("lon")

        time.sleep(1.5)
        try:
            query = f"{plz_str} {ort_str}, {land_str}".strip()
            location = geolocator.geocode(query, timeout=10)

            if not location and ort_str:
                time.sleep(1.5)
                location = geolocator.geocode(f"{ort_str}, {land_str}", timeout=10)

            lat, lon = (location.latitude, location.longitude) if location else (None, None)

            with cache_lock:
                PLZ_CACHE[cache_key] = {"lat": lat, "lon": lon}

            return lat, lon

        except (GeocoderTimedOut, GeocoderServiceError, requests.RequestException) as e:
            print(f"Temporärer Netz-/Geocoding-Fehler für {cache_key}: {e}. Nicht gecacht.")
            return None, None
        except Exception as e:
            print(f"Unerwarteter Geocoding Fehler für {cache_key}: {e}")
            return None, None


def clean_text(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def clean_band_name(name: str) -> str:
    if not name:
        return ""
    pattern = r"\s*[\, \-]*\b(und\s+weitere|und\s+viele\s+mehr|u\.a\.|u\.v\.m\.|und\s+viele\s+weitere)\b.*$"
    cleaned = re.sub(pattern, "", name, flags=re.IGNORECASE).strip()
    if cleaned.lower() in ["und weitere", "und viele mehr", "u.a.", "u.v.m.", "und viele weitere"]:
        return ""
    return cleaned


def map_genres_to_main_categories(subgenres: list[str]) -> list[str]:
    matched_main_genres = set()
    for sub in subgenres:
        sub_clean = sub.lower().strip()
        for main_cat, patterns in COMPILED_GENRE_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(sub_clean):
                    matched_main_genres.add(main_cat)
                    break
    return sorted(list(matched_main_genres)) or ["Sonstige / Mixed"]


def get_all_festival_links(start_urls: list[str]) -> list[str]:
    festival_links = set()

    for url in start_urls:
        print(f"[+] Lade Übersichtsseite: {url}")
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            response.raise_for_status()
            response.encoding = response.apparent_encoding
        except requests.RequestException as e:
            print(f"[-] Fehler beim Laden der Übersicht ({url}): {e}")
            continue

        soup = BeautifulSoup(response.text, "html.parser")

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "/festivals/" in href and not any(
                sub in href for sub in ["/genre/", "/programm/", "/neuer-kommentar/", "/news/", "/fotos/", "/suche/", "/archiv/"]
            ):
                full_url = urljoin(BASE_URL, href)
                festival_links.add(full_url)

    print(f"[+] Insgesamt {len(festival_links)} eindeutige Festival-Links gefunden.\n")
    return list(festival_links)


def is_valid_official_website(url: str) -> bool:
    """Prüft, ob eine URL die tatsächliche offizielle Website ist."""
    if not url or not url.startswith("http"):
        return False
    
    url_lower = url.lower()
    
    for bad_domain in WEBSITE_BLACKLIST:
        if bad_domain in url_lower:
            return False
            
    return True


def parse_festival_page(url: str) -> dict:
    data = {
        "name": "",
        "datum": "",
        "preis": "",
        "obergruppen_genre": [],
        "stile": [],
        "location": "",
        "plz": "",
        "ort": "",
        "land": "",
        "webseite": "",
        "lineup": [],
        "lat": None,
        "lon": None,
    }

    try:
        full_url = urljoin(BASE_URL, url)
        time.sleep(0.1)
        response = requests.get(full_url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
    except Exception as e:
        print(f"[-] Fehler bei URL {url}: {e}")
        return data

    soup = BeautifulSoup(response.text, "html.parser")

    # 1. Festival Name
    h2 = soup.find("h2")
    if h2:
        raw_name = clean_text(h2.get_text())
        data["name"] = re.sub(r"^\d+\.\s*", "", raw_name)

    # 2. Datum
    page_text = clean_text(soup.get_text())
    date_match_multi = re.search(r"Vom:\s*(\d{2}\.\d{2}\.\d{4})\s*bis:\s*(\d{2}\.\d{2}\.\d{4})", page_text)
    date_match_single = re.search(r"Am:\s*(\d{2}\.\d{2}\.\d{4})", page_text)

    if date_match_multi:
        data["datum"] = f"{date_match_multi.group(1)} - {date_match_multi.group(2)}"
    elif date_match_single:
        data["datum"] = date_match_single.group(1)

    # 3. Preis
    for element in soup.find_all(["td", "strong", "b"]):
        if element.get_text().strip() == "Preis:":
            base_td = element if element.name == "td" else element.find_parent("td")
            if base_td:
                val_td = base_td.find_next_sibling("td")
                if val_td:
                    raw_preis = clean_text(val_td.get_text())
                    if len(raw_preis) < 100 and not any(bad in raw_preis.lower() for bad in ["gewinne", "wetter", "radar"]):
                        data["preis"] = raw_preis
                        break
                else:
                    raw_preis = clean_text(base_td.get_text()).replace("Preis:", "").strip()
                    if raw_preis and len(raw_preis) < 100 and not any(bad in raw_preis.lower() for bad in ["gewinne", "wetter"]):
                        data["preis"] = raw_preis
                        break

    # 4. Genre / Stil
    for element in soup.find_all(["td", "strong", "b"]):
        if element.get_text().strip() == "Stil:":
            base_td = element if element.name == "td" else element.find_parent("td")
            if base_td:
                val_td = base_td.find_next_sibling("td")
                if val_td:
                    raw_stil = clean_text(val_td.get_text())
                    if not any(bad in raw_stil.lower() for bad in ["gewinne", "wetter", "radar", "festivalplaner"]):
                        if "..." in raw_stil:
                            raw_stil = raw_stil.split("...")[0]
                        raw_stil = re.sub(r"\b(mehr|close)\b", "", raw_stil, flags=re.IGNORECASE)
                        subgenres = [s.strip() for s in raw_stil.split(",") if s.strip()]

                        if subgenres:
                            data["stile"] = subgenres
                            data["obergruppen_genre"] = map_genres_to_main_categories(subgenres)
                            break

    # 5. Location, PLZ, Ort, Land
    location_div = soup.find("div", class_="location")
    if location_div:
        for tr in location_div.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) >= 2:
                label = clean_text(tds[0].get_text()).replace(":", "")
                val = clean_text(tds[1].get_text())
                if "Location" in label:
                    data["location"] = val
                elif "Plz" in label:
                    data["plz"] = val
                elif "Ort" in label:
                    data["ort"] = val
                elif "Land" in label:
                    data["land"] = val

    # 6. Webseite
    # Suche das strong-Tag 'Website:'
    website_label = soup.find(lambda tag: tag.name == "strong" and "Website:" in tag.get_text())
    if website_label:
        # Finde die umschließende <tr> Zeile
        tr_parent = website_label.find_parent("tr")
        if tr_parent:
            # Suche alle Links in dieser Zeile
            for a_tag in tr_parent.find_all("a", href=True):
                href = a_tag["href"].strip()
                if is_valid_official_website(href):
                    data["webseite"] = href
                    break

    # Fallback: Falls keine Website im HTML-Table gefunden wurde, Schema.org/JSON-LD versuchen
    if not data["webseite"]:
        script_ld = soup.find("script", type="application/ld+json")
        if script_ld and script_ld.string:
            try:
                ld_data = json.loads(script_ld.string)
                url_candidate = ld_data.get("url")
                if url_candidate and is_valid_official_website(url_candidate):
                    data["webseite"] = url_candidate
            except Exception:
                pass

    # 7. Lineup / Bands
    bands_strong = soup.find(lambda tag: tag.name == "strong" and "Bands:" in tag.get_text())
    if bands_strong:
        parent_td = bands_strong.find_parent("td")
        raw_bands = ""

        parent_tr = parent_td.find_parent("tr") if parent_td else None
        next_tr = parent_tr.find_next_sibling("tr") if parent_tr else None

        if next_tr and next_tr.get_text().strip():
            raw_bands = clean_text(next_tr.get_text())
        elif parent_td:
            raw_bands = clean_text(parent_td.get_text()).replace("Bands:", "")

        if "zum kompletten Programm" in raw_bands:
            raw_bands = raw_bands.split("zum kompletten Programm")[0]

        if "," in raw_bands:
            raw_list = [b.strip() for b in raw_bands.split(",") if b.strip()]
            cleaned_list = [clean_band_name(b) for b in raw_list]
            data["lineup"] = [b for b in cleaned_list if b]
        elif raw_bands.strip():
            single_band = clean_band_name(raw_bands.strip())
            if single_band:
                data["lineup"] = [single_band]

    # Geocoding
    lat, lon = get_coordinates_safe(data.get("plz"), data.get("land", "Deutschland"), data.get("ort"))
    data["lat"] = lat
    data["lon"] = lon

    return data


def main():
    start_time = time.time()
    links = get_all_festival_links(START_URLS)

    if not links:
        print("Keine Links gefunden.")
        return

    results = []
    print(f"[+] Starte Scraping & Geocoding mit {MAX_WORKERS} Threads...")

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_url = {executor.submit(parse_festival_page, url): url for url in links}
            completed_count = 0
            total_links = len(links)

            for future in as_completed(future_to_url):
                completed_count += 1
                data = future.result()
                if data["name"]:
                    results.append(data)
                print(f"[{completed_count}/{total_links}] Gescrapt: {data['name'] or 'Unbekannt'}")

                if completed_count % 10 == 0:
                    save_plz_cache(PLZ_CACHE)

    except KeyboardInterrupt:
        print("\n[!] Abbruch durch Benutzer. Sichere bisherige Daten...")
    finally:
        save_plz_cache(PLZ_CACHE)
        output_filename = "festivals.json"
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=4)

        print(
            f"\n[✔] Fertig! {len(results)} Festivals in '{output_filename}' "
            f"gespeichert ({round(time.time() - start_time, 2)}s)."
        )


if __name__ == "__main__":
    main()