import requests
from bs4 import BeautifulSoup
import json
import re
import os

def scrape_festival_details(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    data = {
        "name": "N/A",
        "url_ticker": url,
        "datum": "N/A",
        "preis": "N/A",
        "location": "N/A",
        "plz": "N/A",
        "ort": "N/A",
        "land": "Deutschland",
        "webseite": "N/A",
        "bands": []
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return data
        
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 1. FESTIVAL NAME
        title_tag = soup.find('h1')
        if title_tag:
            data["name"] = title_tag.get_text(strip=True)

        # 2. METADATEN (Datum, Ort, Preis, Land, Webseite) aus div.finfo & Absätzen
        page_text = soup.get_text()

        # DATUM EXTRAHIEREN
        datum_match = re.search(r'(\d{2}\.\d{2}\.\d{4}\s*(bis|-)\s*\d{2}\.\d{2}\.\d{4}|\d{2}\.\d{2}\.\d{4})', page_text)
        if datum_match:
            data["datum"] = datum_match.group(1)

        # PREIS EXTRAHIEREN
        preis_match = re.search(r'(ca\.\s*)?(\d+[\.,]?\d*)\s*(€|Euro)', page_text, re.IGNORECASE)
        if preis_match:
            data["preis"] = preis_match.group(0)

        # ORT & PLZ EXTRAHIEREN
        plz_ort_match = re.search(r'\b(\d{4,5})\s+([A-Za-zÄöüß\s\-\.]+)', page_text)
        if plz_ort_match:
            data["plz"] = plz_ort_match.group(1)
            data["ort"] = plz_ort_match.group(2).split("\n")[0].strip()
            data["location"] = f"{data['plz']} {data['ort']}"

        # WEBSEITE (Sucht nach offizieller Homepage-Verlinkung)
        for a in soup.find_all('a', href=True):
            if "homepage" in a.get_text().lower() or "webseite" in a.get_text().lower() or "offizielle" in a.get_text().lower():
                data["webseite"] = a['href']
                break

        # LAND (Sucht nach bekannten Ländern im Text)
        laender = ["Deutschland", "Österreich", "Schweiz", "Belgien", "Niederlande", "Tschechien", "Frankreich", "Polen", "Spanien", "Großbritannien", "Dänemark"]
        for land in laender:
            if re.search(r'\b' + land + r'\b', page_text, re.IGNORECASE):
                data["land"] = land
                break

        # 3. BANDS PARSEN & BEREINIGEN (Links & Textabschnitte)
        unique_bands = []
        seen_normalized = set()

        # Methode A: Suche nach echten Band-Links (/bands/...)
        band_links = soup.find_all('a', href=re.compile(r'/bands/'))
        
        for a in band_links:
            band_name = a.get_text(strip=True)
            norm = re.sub(r'\s+', ' ', band_name).lower()
            
            # Phrasen wie "und weitere", "mehr Bands" filtern
            if norm and norm not in seen_normalized and not any(p in norm for p in ["und weitere", "weitere", "mehr", "bands", "lineup"]):
                seen_normalized.add(norm)
                unique_bands.append(band_name)

        # Methode B: Fallback (Falls die Bands im normalen Text stehen)
        if not unique_bands:
            bands_block = soup.find(lambda tag: tag.name in ['div', 'p', 'td'] and 'bands' in tag.get_text().lower())
            if bands_block:
                raw_text = bands_block.get_text()
                # Text wie "... und weitere 15 Bands" wegschneiden
                raw_text = re.sub(r'(\.\.\.\s*)?und\s+weitere.*$', '', raw_text, flags=re.IGNORECASE)
                raw_text = re.sub(r'\b(u\.v\.m\.|u\.a\.|\.\.\.)\b', '', raw_text, flags=re.IGNORECASE)

                raw_list = re.split(r'[,;\n]', raw_text)
                for b in raw_list:
                    clean_b = re.sub(r'^[\.\,\s\-]+|[\.\,\s\-]+$', '', b).strip()
                    norm = re.sub(r'\s+', ' ', clean_b).lower()
                    if clean_b and norm not in seen_normalized and norm not in ["und weitere", "u.v.m.", "u.a.", "...", "und", "weitere", "bands:"]:
                        seen_normalized.add(norm)
                        unique_bands.append(clean_b)

        data["bands"] = unique_bands

    except Exception as e:
        print(f"Fehler beim Scrapen von {url}: {e}")

    return data
