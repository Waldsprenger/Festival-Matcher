from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import time
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from geopy.geocoders import Nominatim
import requests

BASE_URL = "https://www.festivalticker.de"
START_URL = "https://www.festivalticker.de/alle-festivals/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

MAX_WORKERS = 25
CACHE_FILE = "plz_cache.json"

GENRE_MAPPING = {
    "Metal": [
        "metal",
        "heavy metal",
        "death metal",
        "black metal",
        "thrash metal",
        "power metal",
        "metalcore",
        "nu metal",
        "gothic metal",
        "doom metal",
        "pagan metal",
        "folk metal",
        "alternative metal",
    ],
    "Rock": [
        "rock",
        "hard rock",
        "punk rock",
        "indie rock",
        "alternative rock",
        "garage rock",
        "stoner rock",
        "post rock",
        "psychedelic rock",
        "deutschrock",
        "folk rock",
    ],
    "Punk & Hardcore": [
        "punk",
        "pop punk",
        "skatepunk",
        "hardcore",
        "post-hardcore",
        "indie punk",
        "garage punk",
        "crust",
        "screamo",
    ],
    "Electronic / Electro": [
        "electro",
        "electronic",
        "techno",
        "house",
        "deephouse",
        "techhouse",
        "psytrance",
        "trance",
        "dubstep",
        "drum and bass",
        "dnb",
        "edm",
        "electro pop",
        "brasstechno",
        "electronica",
        "gabber",
        "hardstyle",
    ],
    "Hip Hop / Rap": [
        "hip hop",
        "hiphop",
        "rap",
        "trap",
        "deutschrap",
        "urban",
        "rapcore",
    ],
    "Pop & Indie": ["pop", "indie", "indie pop", "synth pop", "alternative pop"],
    "Reggae & Ska": ["reggae", "ska", "dub", "dancehall", "skacore"],
    "Gothic & Wave": [
        "gothic",
        "darkwave",
        "ebm",
        "industrial",
        "wave",
        "post punk",
    ],
    "Folk & World": ["folk", "mittelalter", "worldmusic", "weltmusik", "country"],
    "Jazz & Blues": ["jazz", "blues", "funk", "soul"],
}

session = requests.Session()
session.headers.update(HEADERS)


# --- CACHING SYSTEM FÜR GEOKOORDINATEN ---
def load_plz_cache():
  if os.path.exists(CACHE_FILE):
    try:
      with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
    except Exception:
      return {}
  return {}


def save_plz_cache(cache):
  try:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
      json.dump(cache, f, ensure_ascii=False, indent=2)
  except Exception:
    pass


PLZ_CACHE = load_plz_cache()
geolocator = Nominatim(user_agent="festival_scraper_geocoder_v3")


def get_coordinates_safe(plz: str, land: str = "Deutschland", ort: str = ""):
  """Holt Koordinaten mit Rate-Limit-Schutz (1 Req/Sek) & Ort-Fallback."""
  if not plz and not ort:
    return None, None

  plz_str = str(plz).strip() if plz else ""
  land_str = str(land).strip() if land else "Deutschland"
  ort_str = str(ort).strip() if ort else ""

  cache_key = f"{plz_str}_{ort_str}_{land_str}"

  # 1. Aus Cache lesen
  if cache_key in PLZ_CACHE:
    c = PLZ_CACHE[cache_key]
    return c.get("lat"), c.get("lon")

  # 2. Falls nicht im Cache: Sanfte API-Abfrage
  try:
    query = f"{plz_str} {ort_str}, {land_str}".strip()
    location = geolocator.geocode(query, timeout=5)

    # Fallback: Nur Ort & Land versuchen
    if not location and ort_str:
      location = geolocator.geocode(f"{ort_str}, {land_str}", timeout=5)

    if location:
      lat, lon = location.latitude, location.longitude
      PLZ_CACHE[cache_key] = {"lat": lat, "lon": lon}
      # 1.1 Sekunden Pause um OpenStreetMap-Richtlinien einzuhalten
      time.sleep(1.1)
      return lat, lon
  except Exception:
    pass

  return None, None


# --- TEXT- UND BEREINIGUNGSFUNKTIONEN ---
def clean_text(text: str) -> str:
  if not text:
    return ""
  return re.sub(r"\s+", " ", text).strip()


def clean_band_name(name: str) -> str:
  if not name:
    return ""
  pattern = (
      r"\s+(und\s+weitere|und\s+viele\s+mehr|u\.a\.|u\.v\.m\.|und\s+viele\s+weitere)$"
  )
  cleaned = re.sub(pattern, "", name, flags=re.IGNORECASE).strip()
  if cleaned.lower() in [
      "und weitere",
      "und viele mehr",
      "u.a.",
      "u.v.m.",
      "und viele weitere",
  ]:
    return ""
  return cleaned


def map_genres_to_main_categories(subgenres: list[str]) -> list[str]:
  matched_main_genres = set()
  for sub in subgenres:
    sub_clean = sub.lower().strip()
    for main_cat, keywords in GENRE_MAPPING.items():
      for kw in keywords:
        if re.search(r"\b" + re.escape(kw) + r"\b", sub_clean):
          matched_main_genres.add(main_cat)
          break
  return sorted(list(matched_main_genres)) or ["Sonstige / Mixed"]


# --- SCRAPING-LOGIK ---
def get_all_festival_links(start_url: str) -> list[str]:
  print(f"[+] Lade Übersichtsseite: {start_url}")
  try:
    response = session.get(start_url, timeout=15)
    response.raise_for_status()
  except requests.RequestException as e:
    print(f"[-] Fehler beim Laden der Übersicht: {e}")
    return []

  soup = BeautifulSoup(response.content, "html.parser")
  festival_links = set()

  for a_tag in soup.find_all("a", href=True):
    href = a_tag["href"]
    if "/festivals/" in href and not any(
        sub in href
        for sub in [
            "/genre/",
            "/programm/",
            "/neuer-kommentar/",
            "/news/",
            "/fotos/",
            "/suche/",
        ]
    ):
      full_url = urljoin(BASE_URL, href)
      festival_links.add(full_url)

  print(f"[+] Insgesamt {len(festival_links)} Festival-Links gefunden.\n")
  return list(festival_links)


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
    response = session.get(url, timeout=10)
    response.raise_for_status()
  except Exception as e:
    print(f"[-] Fehler bei URL {url}: {e}")
    return data

  soup = BeautifulSoup(response.content, "html.parser")

  # 1. Festival Name
  h2 = soup.find("h2")
  if h2:
    raw_name = clean_text(h2.get_text())
    data["name"] = re.sub(r"^\d+\.\s*", "", raw_name)

  # 2. Datum
  page_text = soup.get_text()
  date_match_multi = re.search(
      r"Vom:\s*(\d{2}\.\d{2}\.\d{4})\s*bis:\s*(\d{2}\.\d{2}\.\d{4})", page_text
  )
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
          if len(raw_preis) < 100 and not any(
              bad in raw_preis.lower() for bad in ["gewinne", "wetter", "radar"]
          ):
            data["preis"] = raw_preis
            break
        else:
          raw_preis = (
              clean_text(base_td.get_text()).replace("Preis:", "").strip()
          )
          if raw_preis and len(raw_preis) < 100 and not any(
              bad in raw_preis.lower() for bad in ["gewinne", "wetter"]
          ):
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
          if not any(
              bad in raw_stil.lower()
              for bad in ["gewinne", "wetter", "radar", "festivalplaner"]
          ):
            if "..." in raw_stil:
              raw_stil = raw_stil.split("...")[0]
            raw_stil = re.sub(
                r"\b(mehr|close)\b", "", raw_stil, flags=re.IGNORECASE
            )
            subgenres = [s.strip() for s in raw_stil.split(",") if s.strip()]

            if subgenres:
              data["stile"] = subgenres
              data["obergruppen_genre"] = map_genres_to_main_categories(
                  subgenres
              )
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
  web_td = soup.find(
      lambda tag: tag.name == "td" and "Website:" in tag.get_text()
  )
  if web_td:
    val_td = web_td.find_next_sibling("td")
    if val_td:
      for a_tag in val_td.find_all("a", href=True):
        href = a_tag["href"]
        if href.startswith("http") and "festivalticker.de" not in href:
          data["webseite"] = href
          break
        elif not href.startswith("javascript:"):
          data["webseite"] = urljoin(BASE_URL, href)

  # 7. Lineup / Bands
  bands_strong = soup.find(
      lambda tag: tag.name == "strong" and "Bands:" in tag.get_text()
  )
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

  return data


def main():
  start_time = time.time()
  links = get_all_festival_links(START_URL)

  if not links:
    print("Keine Links gefunden.")
    return

  results = []
  print(f"[+] 1. Starte schnelles HTML-Scraping mit {MAX_WORKERS} Threads...")

  with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    future_to_url = {
        executor.submit(parse_festival_page, url): url for url in links
    }

    completed_count = 0
    total_links = len(links)

    for future in as_completed(future_to_url):
      completed_count += 1
      data = future.result()
      if data["name"]:
        results.append(data)
      print(f"[{completed_count}/{total_links}] Gescrapt: {data['name']}")

  # --- SCHRITT 2: Geokodierung sequentiell & schonend durchführen ---
  print("\n[+] 2. Ermittle Geokoordinaten (mit Rate-Limit Schutz & Caching)...")
  for idx, item in enumerate(results, 1):
    lat, lon = get_coordinates_safe(
        item.get("plz"), item.get("land", "Deutschland"), item.get("ort")
    )
    item["lat"] = lat
    item["lon"] = lon

  save_plz_cache(PLZ_CACHE)

  output_filename = "festivals.json"
  with open(output_filename, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=4)

  print(
      f"\n[✔] Fertig! {len(results)} Festivals komplett in '{output_filename}'"
      f" gespeichert ({round(time.time() - start_time, 2)}s)."
  )


if __name__ == "__main__":
  main()
