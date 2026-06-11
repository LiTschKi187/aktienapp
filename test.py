import re
import time
import pandas as pd
import pdfplumber
import requests
import yfinance as yf


# ==========================================
# 1. FUNKTIONEN FÜR DAS PDF-PARSING
# ==========================================
def parse_vermoegensuebersicht_text_based(pdf_datei):
    """Liest die Trade Republic Vermögensübersicht aus und extrahiert

    Name, ISIN und Kurswert der Brokerage-Positionen.
    """
    text_inhalt = ""
    with pdfplumber.open(pdf_datei) as pdf:
        for seite in pdf.pages:
            text_inhalt += seite.extract_text() + "\n"

    # Header, Footer und störende Datumsangaben radikal löschen
    text_inhalt = re.sub(
        r"Trade Republic Bank GmbH.*?Seite \d+ von \d+",
        "",
        text_inhalt,
        flags=re.DOTALL,
    )
    text_inhalt = re.sub(
        r"TRADE REPUBLIC BANK GMBH BRUNNENSTRASSE 19-21 10119 BERLIN",
        "",
        text_inhalt,
    )
    text_inhalt = re.sub(r"\d{2}\.\d{2}\.\d{4}", "", text_inhalt)

    # Isolieren des reinen Wertpapier-Bereichs (Zwischen BROKERAGE und CRYPTO WALLET)
    brokerage_zone = re.search(
        r"BROKERAGE.*?(?=CRYPTO WALLET|$)", text_inhalt, flags=re.DOTALL
    )
    if not brokerage_zone:
        return pd.DataFrame()

    brokerage_text = brokerage_zone.group(0)

    # Text in Blöcke pro Asset aufsplitten
    block_pattern = (
        r"([\d\.,]+\s*Stk\..+?)(?=(?:[\d\.,]+\s*Stk\.)|ANZAHL POSITIONEN|$)"
    )
    bloecke = re.findall(block_pattern, brokerage_text, flags=re.DOTALL)

    portfolio_liste = []

    for block in bloecke:
        match_basis = re.search(
            r"[\d\.,]+\s*Stk\.\s+(.+?)\s+ISIN:\s*([A-Z]{2}[A-Z0-9]{10})",
            block,
            flags=re.DOTALL,
        )

        if match_basis:
            raw_name = match_basis.group(1)
            isin = match_basis.group(2).strip()

            # Namen säubern
            name = " ".join(raw_name.split())
            name = re.sub(r"\s+\d+[\d\.,]*\s+\d+[\d\.,]*.*$", "", name)
            name = re.sub(r"\s+(?:EUR|USD)\s*$", "", name).strip()

            # Kurswert extrahieren
            zahlen = re.findall(r"\b\d+[\d\.]*,\d{2}\b", block)

            if zahlen:
                kurswert_str = zahlen[-1]
                try:
                    kurswert = float(
                        kurswert_str.replace(".", "").replace(",", ".")
                    )
                except ValueError:
                    kurswert = 0.0
            else:
                kurswert = 0.0

            # Keine Duplikate aufnehmen
            if not any(item["ISIN"] == isin for item in portfolio_liste):
                portfolio_liste.append(
                    {"Wertpapier": name, "ISIN": isin, "Kurswert_EUR": kurswert}
                )

    return pd.DataFrame(portfolio_liste)


# ==========================================
# 2. FUNKTIONEN FÜR DIE SEKTOREN-ABFRAGE
# ==========================================
def get_ticker_from_isin(isin):
    """Wandelt eine ISIN über die OpenFIGI API in einen Yahoo Finance Ticker

    um.
    """
    url = "https://api.openfigi.com/v1/mapping"
    headers = {"Content-Type": "application/json"}
    payload = [{"idType": "ID_ISIN", "idValue": isin}]

    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if data and "data" in data[0]:
                return data[0]["data"][0]["ticker"]
    except Exception as e:
        print(f"Fehler bei der ISIN-Konvertierung für {isin}: {e}")

    return isin


def get_sector_weights(isin):
    """Holt die Sektorengewichtung (als Dict) für eine ISIN via yfinance.

    Fängt harte Fehler ab, falls yfinance die ISIN ablehnt.
    """
    ticker_symbol = get_ticker_from_isin(isin)

    try:
        ticker = yf.Ticker(ticker_symbol)

        # 1. Versuch: Einzelaktie
        try:
            info = ticker.info
            if info and "sector" in info:
                return {info["sector"]: 100.0}
        except Exception:
            pass

        # 2. Versuch: ETF
        try:
            funds_data = ticker.funds_data
            sector_weights = funds_data.sector_weightings
            if sector_weights:
                return {k: round(v * 100, 2) for k, v in sector_weights.items()}
        except Exception:
            pass

    except ValueError as e:
        print(f"   ⚠️ yfinance ValueError für {isin} ({ticker_symbol}): {e}")
    except Exception as e:
        print(f"   ⚠️ Unerwarteter Fehler bei yfinance Abfrage für {isin}: {e}")

    return None


def create_sector_dataframe(df_portfolio):
    """Erstellt aus dem Portfolio-DF ein neues, separates DataFrame

    aufgeschlüsselt nach Sektoren und schleift den Kurswert durch.
    """
    sektoren_daten = []

    print("\n--- Starte Sektoren-Abfrage über die API ---")

    for index, row in df_portfolio.iterrows():
        isin = row["ISIN"]
        name = row["Wertpapier"]
        kurswert_gesamtes_asset = row["Kurswert_EUR"]  # Hier holen wir den Wert!

        print(f"Lade Sektoren für: {name} ({isin})...")
        weights = get_sector_weights(isin)

        # Wenn die Abfrage erfolgreich ein Dictionary geliefert hat
        if isinstance(weights, dict) and weights:
            for sektor, prozent in weights.items():
                sektoren_daten.append(
                    {
                        "ISIN": isin,
                        "Wertpapier": name,
                        "Kurswert_Asset_EUR": kurswert_gesamtes_asset,  # Neu dabei!
                        "Sektor": sektor,
                        "Gewicht_im_Asset_Prozent": prozent,
                    }
                )
        else:
            print(
                f"   -> ❌ Keine Sektorendaten gefunden für {name}. Wird als 'Unbekannt' markiert."
            )
            sektoren_daten.append(
                {
                    "ISIN": isin,
                    "Wertpapier": name,
                    "Kurswert_Asset_EUR": kurswert_gesamtes_asset,  # Neu dabei!
                    "Sektor": "Unbekannt / Keine Daten",
                    "Gewicht_im_Asset_Prozent": 100.0,
                }
            )

        # Kurze Pause für die API-Ratenbegrenzung
        time.sleep(0.5)

    return pd.DataFrame(sektoren_daten)

def calculate_absolute_sector_distribution(df_sektoren):
    """
    Berechnet den exakten Euro-Betrag pro Sektor, indem das Asset-Gewicht
    mit dem Kurswert multipliziert wird. Fasst das Ergebnis pro Sektor zusammen.
    """
    print("\n--- Berechne absolute Euro-Verteilung pro Sektor ---")
    
    # 1. Eine Kopie erstellen, um das originale DataFrame nicht zu verändern
    df_calc = df_sektoren.copy()
    
    # 2. Den Euro-Wert für jede Zeile berechnen: (Kurswert * Prozent) / 100
    df_calc["Sektor_Wert_EUR"] = (df_calc["Kurswert_Asset_EUR"] * df_calc["Gewicht_im_Asset_Prozent"]) / 100
    # Auf 2 Nachkommastellen runden
    df_calc["Sektor_Wert_EUR"] = df_calc["Sektor_Wert_EUR"].round(2)
    
    # 3. Alle Zeilen nach 'Sektor' gruppieren und die Euro-Werte aufsummieren
    df_zusammenfassung = df_calc.groupby("Sektor", as_index=False)["Sektor_Wert_EUR"].sum()
    
    # 4. Nach dem höchsten Euro-Wert sortieren, damit die wichtigsten Sektoren oben stehen
    df_zusammenfassung = df_zusammenfassung.sort_values(by="Sektor_Wert_EUR", ascending=False)
    
    return df_zusammenfassung

# ==========================================
# 3. AUSFÜHRUNG, TEST & DOPPELTER CSV-EXPORT
# ==========================================
if __name__ == "__main__":
    pdf_datei = "vermoegensuebersicht.pdf"

    # Schritt 1: PDF auslesen
    print("Schritt 1: Lese PDF-Daten aus...")
    df_portfolio = parse_vermoegensuebersicht_text_based(pdf_datei)
    print(df_portfolio)

    if not df_portfolio.empty:
        # Schritt 2: Detaillierte Sektoren abfragen
        df_sektoren = create_sector_dataframe(df_portfolio)
        print("\n=== DETAILLIERTE SEKTOREN-VERTEILUNG (mit Kurswerten) ===")
        print(df_sektoren)

        # --- NEU: Schritt 3: Absolute Euro-Werte pro Sektor berechnen ---
        df_sektor_geld = calculate_absolute_sector_distribution(df_sektoren)

        print("\n=== REINE SEKTOREN-VERTEILUNG IN EURO ===")
        print(df_sektor_geld)
        print("=========================================")

        # --- EXPORT 1: Die detaillierte Liste (Rohdaten) ---
        csv_details = "portfolio_sektoren_details.csv"
        df_sektoren.to_csv(csv_details, index=False, sep=";", encoding="utf-8-sig")
        print(f"\nDetaillierte Rohdaten gespeichert in: '{csv_details}'")

        # --- EXPORT 2: Das gewünschte Debug-Outcome (Euro pro Sektor) ---
        csv_ergebnis = "portfolio_sektoren_euro_gesamt.csv"
        df_sektor_geld.to_csv(csv_ergebnis, index=False, sep=";", encoding="utf-8-sig")
        print(f"▶️ DEBUG-OUTCOME: Euro pro Sektor gespeichert in: '{csv_ergebnis}'")
        
    else:
        print("Das Portfolio-DataFrame ist leer. Abbruch.")