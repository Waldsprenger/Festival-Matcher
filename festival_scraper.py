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

        # 2. TABELLEN-DATEN (Datum, Preis, Ort, Land, Webseite)
        for tr in soup.find_all('tr'):
            tds = tr.find_all('td')
            if len(tds) < 2:
                continue
            
            label = tds[0].get_text(strip=True).lower()
            val_td = tds[1]
            val_text = val_td.get_text(strip=True)

            if "datum" in label:
                data["datum"] = val_text
            elif "preis" in label or "tickets" in label:
                data["preis"] = val_text
            elif "ort" in label or "location" in label:
                data["location"] = val_text
                # PLZ und Ort extrahieren
                plz_match = re.search(r'\b(\d{4,5})\b', val_text)
                if plz_match:
                    data["plz"] = plz_match.group(1)
                
                # Ort extrahieren
                ort_clean = re.sub(r'\b\d{4,5}\b', '', val_text).strip()
                if ort_clean:
                    data["ort"] = ort_clean
            elif "land" in label:
                data["land"] = val_text
            elif "webseite" in label or "homepage" in label:
                link = val_td.find('a')
                if link and link.has_attr('href'):
                    data["webseite"] = link['href']
                else:
                    data["webseite"] = val_text

        # 3. BANDS BEREINIGEN & EXTRAHIEREN (BEAUTIFULSOUP LOGIK)
        bands_td = None
        for strong in soup.find_all('strong'):
            if "bands" in strong.get_text(strip=True).lower():
                # Die Bandzelle ist meist das Eltern-TD oder das nächste TD
                parent_td = strong.find_parent('td')
                if parent_td:
                    bands_td = parent_td
                    break

        if bands_td:
            # Extrahiere den reinen Text aus der Zelle
            raw_text = bands_td.get_text(separator=" ", strip=True)
            
            # Entferne die Überschrift "Bands:"
            raw_text = re.sub(r'^bands\s*:\s*', '', raw_text, flags=re.IGNORECASE)
            
            # Entferne Anhänge wie "... und weitere 12 Bands", "u.v.m.", "u.a."
            raw_text = re.sub(r'(\.\.\.\s*)?und\s+weitere.*$', '', raw_text, flags=re.IGNORECASE)
            raw_text = re.sub(r'\b(u\.v\.m\.|u\.a\.|\.\.\.)\b', '', raw_text, flags=re.IGNORECASE)

            # Trenne Bands an Kommas, Zeilenumbrüchen oder " & "
            raw_list = re.split(r'[,;\n]', raw_text)
            
            unique_bands = []
            seen_normalized = set()

            for b in raw_list:
                clean_b = b.strip()
                # Entferne führende/anhängende Sonderzeichen
                clean_b = re.sub(r'^[\.\,\s\-]+|[\.\,\s\-]+$', '', clean_b).strip()
                
                # Normalisierung für Duplikats-Check
                norm = re.sub(r'\s+', ' ', clean_b).lower()

                # Ungültige Phrasen oder leere Strings filtern
                if not clean_b or norm in ["und weitere", "u.v.m.", "u.a.", "...", "und", "weitere", "bands:"]:
                    continue

                if norm not in seen_normalized:
                    seen_normalized.add(norm)
                    unique_bands.append(clean_b)

            data["bands"] = unique_bands

    except Exception as e:
        print(f"Fehler beim Scrapen von {url}: {e}")

    return data
