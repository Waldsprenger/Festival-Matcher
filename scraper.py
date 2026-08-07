import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup
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

cache_lock = threading.Lock()
geo_lock = threading.Lock()
thread_local = threading.local()

WEBSITE_BLACKLIST = [
    "festivalticker.de", "facebook.com", "instagram.com", "twitter.com",
    "x.com", "youtube.com", "youtu.be", "tiktok.com", "spotify.com",
    "donnerwetter.de", "wetter.de", "wetteronline.de", "wetter.com",
    "google.com", "wikipedia.org"
]

GENRE_MAPPING = {
    "Metal": ["metal", "heavy metal", "death metal", "black metal", "thrash metal", "power metal", "metalcore", "nu metal", "gothic metal", "doom metal", "pagan metal", "folk metal", "alternative metal"],
    "Rock": ["rock", "hard rock", "punk rock", "indie rock", "alternative rock", "garage rock", "stoner rock", "post rock", "psychedelic rock", "deutschrock", "folk rock"],
    "Punk & Hardcore": ["punk", "pop punk", "skatepunk", "hardcore", "post-hardcore", "indie punk", "garage punk", "crust", "screamo"],
    "Electronic / Electro": ["electro", "electronic", "techno", "house", "deephouse", "techhouse", "psytrance", "trance", "dubstep", "drum and bass", "dnb", "edm", "electro pop", "brasstechno", "electronica", "gabber", "hardstyle"],
    "Hip Hop / Rap": ["hip hop", "hiphop", "rap", "trap", "deutschrap", "urban", "rapcore"],
    "Pop & Indie": ["pop", "indie", "indie pop", "synth pop", "alternative pop"],
    "Reggae & Ska": ["reggae", "ska", "dub", "dancehall", "skacore"],
    "Gothic & Wave": ["gothic", "darkwave", "ebm", "industrial", "wave", "post punk"],
    "Folk & World": ["folk", "mittelalter", "worldmusic", "weltmusik", "country"],
    "Jazz & Blues": ["jazz", "blues", "funk", "soul"],
}

COMPILED_GENRE_PATTERNS = {
    main_cat: [
        re.compile(r"(?<![a-zA-Z0-9])" + re.escape(kw) + r"(?![a-zA-Z0-9])", re.IGNORECASE)
        for kw in keywords
    ]
    for main_cat, keywords in GENRE_MAPPING.items()
}


def load_plz_cache() -> Dict[str, Any]:
    with cache_lock:
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}


PLZ_CACHE: Dict[str, Any] = load_plz_cache()


def save_plz_cache() -> None:
    with cache_lock:
        try:
            cache_copy = dict(PLZ_CACHE)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache_copy, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Fehler beim Speichern des Cache: {e}")


geolocator = Nominatim(user_agent="my_festival_scraper_app_v2.0 (waldsprenger@gmail.com)")


def get_thread_session() -> requests.Session:
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

    with cache_lock:
        if cache_key in PLZ_CACHE:
            c = PLZ_CACHE[cache_key]
            return c.get("lat"), c.get("lon")

    with geo_lock:
        with cache_lock:
            if cache_key in PLZ_CACHE:
                c = PLZ_CACHE[cache_key]
                return c.get("lat"), c.get("lon")

        time.sleep(1.2)
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

        except Exception:
            return None, None


def clean_text(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def clean_band_name(name: str) -> str:
    if not name:
        return ""

    # Uhrzeiten radikal entfernen, z.B. "18:00 Uhr" oder "18.30 - 19.30 Uhr"
    cleaned = re.sub(r"^\s*(\d{1,2}[:.]\d{2}\s*(?:Uhr)?\s*(?:-|bis)?\s*(?:\d{1,2}[:.]\d{2}\s*(?:Uhr)?)?|\d{1,2}\s*Uhr)\s*[-:]?\s*", "", name, flags=re.IGNORECASE).strip()
    # Fallback für alleinstehende Zeiten (z.B. nur "18:00" am Anfang)
    cleaned = re.sub(r"^\s*\d{1,2}[:.]\d{2}\s*[-:]?\s*", "", cleaned, flags=re.IGNORECASE).strip()

    # Nachgestellte Zeiten entfernen
    cleaned = re.sub(r"\s*[\(\[\{]?\s*\d{1,2}[:.]\d{2}\s*(Uhr)?\s*[\)\]\}]?\s*$", "", cleaned, flags=re.IGNORECASE).strip()
    
    # Genres in eckigen/runden Klammern entfernen
    cleaned = re.sub(r"\s*[\(\[\{].*?[\)\]\}]", "", cleaned).strip()

    pattern = r"\s*[\, \-]*\b(und\s+weitere|und\s+viele\s+mehr|u\.a\.|u\.v\.m\.|und\s+viele\s+weitere)\b.*$"
    cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()

    if cleaned.lower() in ["und weitere", "und viele mehr", "u.a.", "u.v.m.", "und viele weitere"]:
        return ""
    return cleaned


def deduplicate_band_list(band_list: List[str]) -> List[str]:
    unique_bands: List[str] = []

    for band in band_list:
        if not band:
            continue

        matched_existing = None
        for existing in unique_bands:
            if band.lower() == existing.lower():
                matched_existing = existing
                break

            len_diff = abs(len(band) - len(existing))
            if len_diff <= 2 and min(len(band), len(existing)) > 4:
                if SequenceMatcher(None, band.lower(), existing.lower()).ratio() >= 0.90:
                    matched_existing = existing
                    break

        if matched_existing:
            if sum(1 for c in band if c.isupper()) > sum(1 for c in matched_existing if c.isupper()):
                idx = unique_bands.index(matched_existing)
                unique_bands[idx] = band
        else:
            unique_bands.append(band)

    return unique_bands


def levenshtein_dist(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein_dist(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def global_band_deduplication(festivals_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Sammelt alle Bands und bestimmt die bestmögliche Schreibweise (z.B. Lamb Of God vs. Lamb of God)
    band_counts = {}
    for f in festivals_data:
        for b in f.get("lineup", []):
            band_counts[b] = band_counts.get(b, 0) + 1

    unique_bands = list(band_counts.keys())
    canonical_mapping = {}

    for i, band in enumerate(unique_bands):
        if band in canonical_mapping:
            continue
        similar_group = [band]
        for j in range(i + 1, len(unique_bands)):
            other = unique_bands[j]
            if other in canonical_mapping:
                continue
            
            # Case-insensitive Übereinstimmung ODER 1 Zeichen Levenshtein-Unterschied (z. B. "Ok Kid" vs. "OK Kid")
            if band.lower() == other.lower():
                similar_group.append(other)
            elif abs(len(band) - len(other)) <= 1:
                if levenshtein_dist(band.lower(), other.lower()) <= 1:
                    similar_group.append(other)

        best_band = similar_group[0]
        best_score = (-1, -1)
        for b in similar_group:
            score = (band_counts[b], sum(1 for c in b if c.isupper()))
            if score > best_score:
                best_score = score
                best_band = b

        for b in similar_group:
            canonical_mapping[b] = best_band

    # Mapping anwenden
    for f in festivals_data:
        if "lineup" in f:
            new_lineup = []
            seen = set()
            for b in f["lineup"]:
                canon = canonical_mapping.get(b, b)
                if canon not in seen:
                    seen.add(canon)
                    new_lineup.append(canon)
            f["lineup"] = new_lineup

    return festivals_data


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
        "abgesagt": False,
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

    # Überprüfe extrem sicher auf durchgestrichenen Text und das Wort "abgesagt/absage"
    has_strike = bool(
        soup.find_all(["strike", "del", "s"])
        or soup.find_all(class_=re.compile(r"line-through", re.I))
        or soup.find_all(attrs={"style": re.compile(r"line-through", re.I)})
    )

    page_text_lower = soup.get_text().lower()
    has_cancel_word = bool(re.search(r"(abgesagt|absage)", page_text_lower))

    if has_strike and has_cancel_word:
        data["abgesagt"] = True

    h2 = soup.find("h2")
    if h2:
        raw_name = clean_text(h2.get_text())
        data["name"] = re.sub(r"^\d+\.\s*", "", raw_name)

    page_text = clean_text(soup.get_text())
    date_match_multi = re.search(r"Vom:\s*(\d{2}\.\d{2}\.\d{4})\s*bis:\s*(\d{2}\.\d{2}\.\d{4})", page_text)
    date_match_single = re.search(r"Am:\s*(\d{2}\.\d{2}\.\d{4})", page_text)

    if date_match_multi:
        data["datum"] = f"{date_match_multi.group(1)} - {date_match_multi.group(2)}"
    elif date_match_single:
        data["datum"] = date_match_single.group(1)

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

    website_label = soup.find(lambda tag: getattr(tag, "name", None) in ["strong", "b"] and "Website:" in tag.get_text())
    if website_label:
        tr_parent = website_label.find_parent("tr")
        if tr_parent:
            for a_tag in tr_parent.find_all("a", href=True):
                href = a_tag["href"].strip()
                if is_valid_official_website(href):
                    data["webseite"] = href
                    break

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

    bands_strong = soup.find(lambda tag: getattr(tag, "name", None) in ["strong", "b"] and "Bands:" in tag.get_text())
    if bands_strong:
        parent_td = bands_strong.find_parent("td")
        target_container = None
        if parent_td:
            parent_tr = parent_td.find_parent("tr")
            next_tr = parent_tr.find_next_sibling("tr") if parent_tr else None

            if next_tr and next_tr.get_text().strip():
                target_container = next_tr
            else:
                target_container = parent_td

        if target_container:
            # Trenne auch bei Zeilenumbrüchen (\n), wenn keine Kommata verwendet wurden
            container_text = target_container.get_text(separator="\n")
            container_text = re.sub(r"^Bands:\s*", "", container_text, flags=re.I)
            if "zum kompletten Programm" in container_text:
                container_text = container_text.split("zum kompletten Programm")[0]

            # Erzwinge Split, wenn Bands nicht durch Komma getrennt sind, aber Genres in Klammern stehen (z.B. Band (Pop) Band 2 (Rock))
            container_text = container_text.replace(")", "),")

            # Nach Kommata, Strichpunkten oder neuen Zeilen splitten
            raw_list = [b.strip() for b in re.split(r'[,\n\r;]+', container_text) if b.strip()]
            cleaned_list = [clean_band_name(b) for b in raw_list if clean_band_name(b)]
            data["lineup"] = deduplicate_band_list(cleaned_list)

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

    executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        future_to_url = {executor.submit(parse_festival_page, url): url for url in links}
        completed_count = 0
        total_links = len(links)

        for future in as_completed(future_to_url):
            completed_count += 1
            try:
                data = future.result()
                if data.get("name"):
                    results.append(data)
                print(f"[{completed_count}/{total_links}] Gescrapt: {data.get('name') or 'Unbekannt'}")
            except Exception as exc:
                print(f"[{completed_count}/{total_links}] Fehler bei der Verarbeitung: {exc}")

            if completed_count % 10 == 0:
                save_plz_cache()

    except KeyboardInterrupt:
        print("\n[!] Abbruch durch Benutzer. Beende laufende Threads...")
        executor.shutdown(wait=False, cancel_futures=True)
    finally:
        executor.shutdown(wait=True)
        save_plz_cache()
        
        # Globale Deduplizierung über alle gesammelten Ergebnisse ausführen
        results = global_band_deduplication(results)
        
        output_filename = "festivals.json"
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=4)

        print(
            f"\n[✔] Fertig! {len(results)} Festivals in '{output_filename}' "
            f"gespeichert ({round(time.time() - start_time, 2)}s)."
        )


if __name__ == "__main__":
    main()
