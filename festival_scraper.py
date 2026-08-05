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

        # 2. GENERISCHES AUSLESEN ALLER TABELLENZEILEN (Datum, Preis, Ort, Land, Webseite, Bands)
        bands_raw_text = ""
        
        for tr in soup.find_all('tr'):
            tds = tr.find_all('td')
            if len(tds) < 2:
                continue
            
            # Beschriftung (linke Zelle) & Wert (rechte Zelle)
            label = tds[0].get_text(strip=True).lower()
            val_td = tds[1]
            val_text = val_td.get_text(strip=True)

            if "datum" in label:
                data["datum"] = val_text
            elif "preis" in label or "ticket" in label:
                data["preis"] = val_text
            elif "ort" in label or "location" in label or "plz" in label:
                data["location"] = val_text
                # PLZ herausfiltern (4- oder 5-stellig)
                plz_match = re.search(r'\b(\d{4,5})\b', val_text)
                if plz_match:
                    data["plz"] = plz_match.group(1)
                
                # Ort bereinigen (PLZ entfernen)
                ort_clean = re.sub(r'\b\d{4,5}\b', '', val_text).strip()
                if ort_clean:
                    data["ort"] = ort_clean
            elif "land" in label:
                data["land"] = val_text
            elif "web" in label or "homepage" in label or "seite" in label:
                link = val_td.find('a')
                if link and link.has_attr('href'):
                    data["webseite"] = link['href']
                else:
                    data["webseite"] = val_text
            elif "band" in label:
                # Bands aus der Zelle sichern
                bands_raw_text = val_td.get_text(separator=", ", strip=True)

        # Falls Bands nicht in der Tabelle lagen: Fallback-Suche im gesamten Dokument
        if not bands_raw_text:
            bands_header = soup.find(lambda tag: tag.name in ['td', 'th', 'div', 'strong', 'b'] and 'bands' in tag.get_text().lower())
            if bands_header:
                parent = bands_header.find_parent('tr') or bands_header.find_parent('div')
                if parent:
                    bands_raw_text = parent.get_text(separator=", ", strip=True)

        # 3. BANDS SAUBER PARSEN & ENTHALTENE PHRASEN / DUPLIKATE ENTFERNEN
        if bands_raw_text:
            # Entferne "Bands:", "... und weitere X Bands", "u.v.m.", "u.a."
            clean_str = re.sub(r'^bands\s*:\s*', '', bands_raw_text, flags=re.IGNORECASE)
            clean_str = re.sub(r'(\.\.\.\s*)?und\s+weitere.*$', '', clean_str, flags=re.IGNORECASE)
            clean_str = re.sub(r'\b(u\.v\.m\.|u\.a\.|\.\.\.)\b', '', clean_str, flags=re.IGNORECASE)

            # Aufspalten an Kommas, Semikolons oder Zeilenumbrüchen
            raw_list = re.split(r'[,;\n]', clean_str)
            
            unique_bands = []
            seen_normalized = set()

            for b in raw_list:
                clean_b = b.strip()
                # Führende/Anhängende Sonderzeichen löschen
                clean_b = re.sub(r'^[\.\,\s\-]+|[\.\,\s\-]+$', '', clean_b).strip()
                
                # Normalisierte Form für Duplikatsvergleich (Kleinschreibung & einfache Leerzeichen)
                norm = re.sub(r'\s+', ' ', clean_b).lower()

                # Leere oder unnütze Phrasen überspringen
                if not clean_b or norm in ["und weitere", "u.v.m.", "u.a.", "...", "und", "weitere", "bands", "bands:"]:
                    continue

                if norm not in seen_normalized:
                    seen_normalized.add(norm)
                    unique_bands.append(clean_b)

            data["bands"] = unique_bands

    except Exception as e:
        print(f"Fehler beim Scrapen von {url}: {e}")

    return data
