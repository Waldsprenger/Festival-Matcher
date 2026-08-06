import html
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://www.festivalticker.de"

START_URLS = [
    "https://www.festivalticker.de/alle-festivals/",
    "https://www.festivalticker.de/festivals-2027/",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

MAX_WORKERS = 5
CACHE_FILE = "plz_cache.json"

# Synchronization Primitives
cache_lock = threading.Lock()
geo_lock = threading.Lock()
thread_local = threading.local()

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

COMPILED_GENRE_PATTERNS = {
    main_cat: [
        re.compile(r"(?:^|[^a-zA-Z0-9])" + re.escape(kw) + r"(?:$|[^a-zA-Z0-9])", re.IGNORECASE)
        for kw in keywords
    ]
    for main_cat, keywords in GENRE_MAPPING.items()
}

# ==========================================
# HELPER: BANDNAME & LINEUP CLEANING
# ==========================================
def clean_band_name(raw_name: str) -> str:
    """Entfernt Uhrzeiten, Genres in Klammern und störende Zeichen."""
    name = raw_name.strip()
    if not name:
        return ""

    # Entferne Uhrzeiten am Anfang/Ende (z.B. "18:00 Uhr", "19.30 Uhr", "21:15")
    name = re.sub(r"^\s*\d{1,2}[:.]\d{2}\s*(?:Uhr)?\s*", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s*\d{1,2}[:.]\d{2}\s*(?:Uhr)?\s*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^\s*\d{1,2}\s*Uhr\s*", "", name, flags=re.IGNORECASE)

    # Entferne Genre-Klammern am Ende z.B. "(Punk Rock)" oder "(Metal)"
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)

    # Entferne evtl. verbliebene führende Aufzählungspunkte / Bindestriche
    name = re.sub(r"^[\s\-\•\*\–\—]+", "", name)
    
    return name.strip()


def parse_lineup(soup: BeautifulSoup) -> List[str]:
    """Extrahiert das Lineup sauber, auch bei Zeilenumbrüchen und ohne Uhrzeiten/Genres."""
    lineup = []
    
    # Suche nach dem Bands-Container auf festivalticker.de
    bands_td = None
    for td in soup.find_all(["td", "div"]):
        text = td.get_text(strip=True)
        if text.startswith("Bands:") or "Bands:" in text:
            bands_td = td
            break

    if bands_td:
        # Ersetze <br> durch Zeilenumbrüche vor der Text-Extraktion
        for br in bands_td.find_all("br"):
            br.replace_with("\n")
            
        full_text = bands_td.get_text()
        # Entferne das Label "Bands:"
        full_text = re.sub(r"^.*?Bands:\s*", "", full_text, flags=re.IGNORECASE | re.DOTALL)

        # Splitte nach Zeilenumbrüchen und Kommata
        raw_items = re.split(r"[\n\r;,]+", full_text)
        for item in raw_items:
            cleaned = clean_band_name(item)
            if cleaned and len(cleaned) > 1 and cleaned not in lineup:
                lineup.append(cleaned)
    else:
        # Fallback: Suche nach band-spezifischen Links oder Aufzählungs-Tags
        for a_tag in soup.select("a[href*='/bands/']"):
            cleaned = clean_band_name(a_tag.get_text())
            if cleaned and cleaned not in lineup:
                lineup.append(cleaned)

    return lineup


def check_is_cancelled(soup: BeautifulSoup) -> bool:
    """
    Prüft, ob das Festival abgesagt wurde.
    Bedingung: Durchgestrichener Text UND eine Variation von 'abgesagt' auf der Seite.
    """
    page_text = soup.get_text().lower()
    has_cancelled_word = bool(re.search(r"abgesagt|absage|fällt aus|cancel", page_text))
    
    # Prüfe auf durchgestrichene HTML-Elemente
    has_line_through = bool(
        soup.find(class_=re.compile(r"line-through", re.I)) or
        soup.find(["del", "s", "strike"])
    )

    return has_cancelled_word and has_line_through


# ==========================================
# LEVENSHTEIN & DEDUPLIZIERUNG
# ==========================================
def levenshtein_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def normalize_band_name(name: str) -> str:
    name_clean = re.sub(r"[^\w\s]", "", name, flags=re.UNICODE)
    return " ".join(name_clean.lower().split())


def deduplicate_festival_lineups(festivals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    all_bands = [band for f in festivals for band in f.get("lineup", []) if band]
    
    normalized_groups = {}
    for original_name in all_bands:
        norm = normalize_band_name(original_name)
        if norm not in normalized_groups:
            normalized_groups[norm] = []
        normalized_groups[norm].append(original_name)

    canonical_names = {}
    for norm, original_list in normalized_groups.items():
        best_name = max(original_list, key=lambda x: (sum(1 for c in x if c.isupper()), -len(x)))
        canonical_names[norm] = best_name

    distinct_norms = list(canonical_names.keys())
    mapping = {}

    for i in range(len(distinct_norms)):
        norm_i = distinct_norms[i]
        if norm_i in mapping:
            continue

        target_norm = norm_i
        for j in range(i + 1, len(distinct_norms)):
            norm_j = distinct_norms[j]
            if norm_j in mapping:
                continue

            dist = levenshtein_distance(norm_i, norm_j)
            max_len = max(len(norm_i), len(norm_j))

            if (max_len <= 5 and dist <= 1) or (max_len > 5 and dist <= 2):
                mapping[norm_j] = canonical_names[target_norm]

        mapping[norm_i] = canonical_names[target_norm]

    final_mapping = {
        original_name: mapping.get(normalize_band_name(original_name), original_name)
        for original_name in all_bands
    }

    for f in festivals:
        if "lineup" in f and f["lineup"]:
            new_lineup = []
            for band in f["lineup"]:
                canonical = final_mapping.get(band, band)
                if canonical not in new_lineup:
                    new_lineup.append(canonical)
            f["lineup"] = new_lineup

    return festivals

def load_plz_cache() -> Dict[str, Any]:
    """Lädt den PLZ Cache threadsicher aus der Datei."""
    with cache_lock:
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Fehler beim Laden des Cache: {e}")
                return {}
        return {}


def save_plz_cache() -> None:
    """Speichert den globalen Cache threadsicher ab."""
    with cache_lock:
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(PLZ_CACHE, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Fehler beim Speichern des Cache: {e}")


# Cache und Geolocator nach Funktionsdefinitionen initialisieren
PLZ_CACHE: Dict[str, Any] = load_plz_cache()
geolocator = Nominatim(user_agent="my_festival_scraper_app_v1.0 (waldsprenger@gmail.com)")


def get_thread_session() -> requests.Session:
    """Erstellt eine thread-spezifische Session zur sicheren Wiederverwendung."""
    if not hasattr(thread_local, "session"):
        session = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update(HEADERS)
        thread_local.session = session
    return thread_local.session


def get_coordinates_safe(plz: str, land: str = "Deutschland", ort: str = "") -> Tuple[Optional[float], Optional[float]]:
    if not plz and not ort:
        return None, None

    plz_str = str(plz).strip() if plz else ""
    if plz_str and len(plz_str) < 5 and plz_str.isdigit():
        plz_str = plz_str.zfill(5)

    land_str = str(land).strip() if land else "Deutschland"
    ort_str = str(ort).strip() if ort else ""

    cache_key = f"{plz_str}_{ort_str}_{land_str}"

    # Cache Prüfung vor Lock-Erwerb
    with cache_lock:
        if cache_key in PLZ_CACHE:
            c = PLZ_CACHE[cache_key]
            return c.get("lat"), c.get("lon")

    # Geocoding synchronisieren & Rate Limit einhalten
    with geo_lock:
        # Re-Check im Lock
        with cache_lock:
            if cache_key in PLZ_CACHE:
                c = PLZ_CACHE[cache_key]
                return c.get("lat"), c.get("lon")

        time.sleep(1.2)  # Nominatim Rate-Limit
        try:
            query = f"{plz_str} {ort_str}, {land_str}".strip()
            location = geolocator.geocode(query, timeout=10)

            if not location and ort_str:
                time.sleep(1.2)
                location = geolocator.geocode(f"{ort_str}, {land_str}", timeout=10)

            lat, lon = (location.latitude, location.longitude) if location else (None, None)

            with cache_lock:
                PLZ_CACHE[cache_key] = {"lat": lat, "lon": lon}

            return lat, lon

        except (GeocoderTimedOut, GeocoderServiceError) as e:
            print(f"Temporärer Geocoding-Fehler für {cache_key}: {e}. Nicht gecacht.")
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


def map_genres_to_main_categories(subgenres: List[str]) -> List[str]:
    matched_main_genres = set()
    for sub in subgenres:
        sub_clean = sub.lower().strip()
        for main_cat, patterns in COMPILED_GENRE_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(sub_clean):
                    matched_main_genres.add(main_cat)
                    break
    return sorted(list(matched_main_genres)) or ["Sonstige / Mixed"]


def get_all_festival_links(start_urls: List[str]) -> List[str]:
    festival_links = set()
    session = get_thread_session()

    for url in start_urls:
        print(f"[+] Lade Übersichtsseite: {url}")
        try:
            response = session.get(url, timeout=15)
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


def parse_festival_page(url: str) -> Dict[str, Any]:
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

    session = get_thread_session()

    try:
        full_url = urljoin(BASE_URL, url)
        time.sleep(0.1)
        response = session.get(full_url, timeout=10)
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
    website_label = soup.find(lambda tag: getattr(tag, "name", None) == "strong" and "Website:" in tag.get_text())
    if website_label:
        tr_parent = website_label.find_parent("tr")
        if tr_parent:
            for a_tag in tr_parent.find_all("a", href=True):
                href = a_tag["href"].strip()
                if is_valid_official_website(href):
                    data["webseite"] = href
                    break

    # Fallback Schema.org/JSON-LD
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
    bands_strong = soup.find(lambda tag: getattr(tag, "name", None) == "strong" and "Bands:" in tag.get_text())
    if bands_strong:
        parent_td = bands_strong.find_parent("td")
        raw_bands = ""

        if parent_td:
            parent_tr = parent_td.find_parent("tr")
            next_tr = parent_tr.find_next_sibling("tr") if parent_tr else None

            if next_tr and next_tr.get_text().strip():
                raw_bands = clean_text(next_tr.get_text())
            else:
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
                try:
                    data = future.result()
                    if data["name"]:
                        results.append(data)
                    print(f"[{completed_count}/{total_links}] Gescrapt: {data['name'] or 'Unbekannt'}")
                except Exception as exc:
                    print(f"[{completed_count}/{total_links}] Fehler bei der Verarbeitung: {exc}")

                if completed_count % 10 == 0:
                    save_plz_cache()

    except KeyboardInterrupt:
        print("\n[!] Abbruch durch Benutzer. Sichere bisherige Daten...")
    finally:
        save_plz_cache()
        output_filename = "festivals.json"
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=4)

        print(
            f"\n[✔] Fertig! {len(results)} Festivals in '{output_filename}' "
            f"gespeichert ({round(time.time() - start_time, 2)}s)."
        )


if __name__ == "__main__":
    main()
