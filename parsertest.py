import re
import pdfplumber
import pandas as pd

def parse_vermoegensuebersicht_text_based(pdf_datei):
    text_inhalt = ""
    with pdfplumber.open(pdf_datei) as pdf:
        for seite in pdf.pages:
            text_inhalt += seite.extract_text() + "\n"
            
    # 1. Header, Footer und störende Datumsangaben radikal löschen
    text_inhalt = re.sub(r"Trade Republic Bank GmbH.*?Seite \d+ von \d+", "", text_inhalt, flags=re.DOTALL)
    text_inhalt = re.sub(r"TRADE REPUBLIC BANK GMBH BRUNNENSTRASSE 19-21 10119 BERLIN", "", text_inhalt)
    # Das Datum (z.B. 05.06.2026) komplett killen, damit es nicht als Kurswert fehlinterpretiert wird
    text_inhalt = re.sub(r"\d{2}\.\d{2}\.\d{4}", "", text_inhalt)
    
    # 2. Wir isolieren den reinen Wertpapier-Bereich (Alles zwischen BROKERAGE und CRYPTO WALLET)
    brokerage_zone = re.search(r"BROKERAGE.*?(?=CRYPTO WALLET|$)", text_inhalt, flags=re.DOTALL)
    if not brokerage_zone:
        return pd.DataFrame() # Falls die Struktur völlig anders ist
        
    brokerage_text = brokerage_zone.group(0)
    
    # 3. Wir splitten den Text in Blöcke auf. Jeder Asset-Block beginnt mit einer Stückzahl (z.B. "3,665729 Stk.")
    block_pattern = r"([\d\.,]+\s*Stk\..+?)(?=(?:[\d\.,]+\s*Stk\.)|ANZAHL POSITIONEN|$)"
    bloecke = re.findall(block_pattern, brokerage_text, flags=re.DOTALL)
    
    portfolio_liste = []
    
    for block in bloecke:
        # Extrahiere den Namen und die ISIN aus dem aktuellen Block
        match_basis = re.search(r"[\d\.,]+\s*Stk\.\s+(.+?)\s+ISIN:\s*([A-Z]{2}[A-Z0-9]{10})", block, flags=re.DOTALL)
        
        if match_basis:
            raw_name = match_basis.group(1)
            isin = match_basis.group(2).strip()
            
            # Namen säubern
            name = " ".join(raw_name.split())
            # Eventuelle Zusatztexte wie "Registered Shares" o.ä. sauber halten, aber Zahlenkolonnen am Ende löschen
            name = re.sub(r"\s+\d+[\d\.,]*\s+\d+[\d\.,]*.*$", "", name)
            name = re.sub(r"\s+(?:EUR|USD)\s*$", "", name).strip()
            
            # --- Den Kurswert aus dem Block extrahieren ---
            # Wir suchen nach Geldbeträgen am Ende des Textblocks (Format: 205,32 oder 3.318,03)
            # Da das Datum gelöscht wurde, ist die letzte gültige Währungszahl der Kurswert
            zahlen = re.findall(r"\b\d+[\d\.]*,\d{2}\b", block)
            
            if zahlen:
                # Die allerletzte Zahl im Block ist der finale Kurswert in EUR
                kurswert_str = zahlen[-1]
                try:
                    kurswert = float(kurswert_str.replace('.', '').replace(',', '.'))
                except ValueError:
                    kurswert = 0.0
            else:
                kurswert = 0.0
                
            # Keine Duplikate aufnehmen
            if not any(item['ISIN'] == isin for item in portfolio_liste):
                portfolio_liste.append({
                    "Wertpapier": name,
                    "ISIN": isin,
                    "Kurswert_EUR": kurswert
                })
                
    return pd.DataFrame(portfolio_liste)
# Beispielaufruf
if __name__ == "__main__":
    df_portfolio = parse_vermoegensuebersicht_text_based("vermoegensuebersicht.pdf")
    print(df_portfolio)