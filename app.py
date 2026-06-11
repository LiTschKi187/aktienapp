import re
import time
import pandas as pd
import pdfplumber
import requests
import yfinance as yf
import streamlit as st
import plotly.graph_objects as go
from io import BytesIO
import os
import json

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
    """Wandelt eine ISIN über die OpenFIGI API in einen Yahoo Finance Ticker um."""
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
        pass

    return isin


def detect_asset_type(isin):
    """Versucht zu erkennen, ob es sich um einen ETF oder eine Aktie handelt."""
    ticker_symbol = get_ticker_from_isin(isin)
    
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info
        
        # ETF-Detection
        if "quoteType" in info:
            if info["quoteType"].upper() == "ETF":
                return "ETF"
            elif info["quoteType"].upper() == "EQUITY":
                return "Aktie"
        
        # Alternative: Prüfe auf "funds_data" (typischerweise ETFs)
        try:
            funds_data = ticker.funds_data
            if funds_data is not None:
                return "ETF"
        except:
            pass
            
        return "Aktie"
    except:
        return "Aktie"


def get_sector_weights(isin):
    """Holt die Sektorengewichtung (als Dict) für eine ISIN via yfinance."""
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
        pass
    except Exception as e:
        pass

    return None


def create_sector_dataframe(df_portfolio, progress_callback=None):
    """Erstellt aus dem Portfolio-DF ein neues, separates DataFrame
    aufgeschlüsselt nach Sektoren und schleift den Kurswert durch.
    """
    sektoren_daten = []
    total_assets = len(df_portfolio)

    for index, row in df_portfolio.iterrows():
        isin = row["ISIN"]
        name = row["Wertpapier"]
        kurswert_gesamtes_asset = row["Kurswert_EUR"]
        
        # Asset-Type erkennen
        asset_type = detect_asset_type(isin)

        weights = get_sector_weights(isin)

        # Wenn die Abfrage erfolgreich ein Dictionary geliefert hat
        if isinstance(weights, dict) and weights:
            for sektor, prozent in weights.items():
                sektoren_daten.append(
                    {
                        "ISIN": isin,
                        "Wertpapier": name,
                        "Kurswert_Asset_EUR": kurswert_gesamtes_asset,
                        "Sektor": sektor,
                        "Gewicht_im_Asset_Prozent": prozent,
                        "Asset_Type": asset_type,
                    }
                )
        else:
            sektoren_daten.append(
                {
                    "ISIN": isin,
                    "Wertpapier": name,
                    "Kurswert_Asset_EUR": kurswert_gesamtes_asset,
                    "Sektor": "Unbekannt / Keine Daten",
                    "Gewicht_im_Asset_Prozent": 100.0,
                    "Asset_Type": asset_type,
                }
            )

        if progress_callback:
            progress_callback((index + 1) / total_assets)
        
        time.sleep(0.5)

    return pd.DataFrame(sektoren_daten)


def calculate_absolute_sector_distribution(df_sektoren):
    """
    Berechnet den exakten Euro-Betrag pro Sektor, indem das Asset-Gewicht
    mit dem Kurswert multipliziert wird. Fasst das Ergebnis pro Sektor zusammen.
    """
    df_calc = df_sektoren.copy()
    
    df_calc["Sektor_Wert_EUR"] = (df_calc["Kurswert_Asset_EUR"] * df_calc["Gewicht_im_Asset_Prozent"]) / 100
    df_calc["Sektor_Wert_EUR"] = df_calc["Sektor_Wert_EUR"].round(2)
    
    df_zusammenfassung = df_calc.groupby("Sektor", as_index=False)["Sektor_Wert_EUR"].sum()
    df_zusammenfassung = df_zusammenfassung.sort_values(by="Sektor_Wert_EUR", ascending=False)
    
    return df_zusammenfassung


# ==========================================
# 3. FUNKTIONEN FÜR LÄNDERANALYSE
# ==========================================
ISIN_COUNTRY_MAPPING = {
    # Deutschland
    "DE": "Deutschland",
    # Vereinigtes Königreich
    "GB": "Vereinigtes Königreich",
    # Frankreich
    "FR": "Frankreich",
    # Niederlande
    "NL": "Niederlande",
    # Belgien
    "BE": "Belgien",
    # Österreich
    "AT": "Österreich",
    # Schweiz
    "CH": "Schweiz",
    # Italien
    "IT": "Italien",
    # Spanien
    "ES": "Spanien",
    # Schweden
    "SE": "Schweden",
    # Norwegen
    "NO": "Norwegen",
    # Dänemark
    "DK": "Dänemark",
    # Finnland
    "FI": "Finnland",
    # Polen
    "PL": "Polen",
    # Tschechien
    "CZ": "Tschechien",
    # Ungarn
    "HU": "Ungarn",
    # USA
    "US": "USA",
    # Kanada
    "CA": "Kanada",
    # Japan
    "JP": "Japan",
    # China
    "CN": "China",
    # Hongkong
    "HK": "Hongkong",
    # Australien
    "AU": "Australien",
    # Singapur
    "SG": "Singapur",
    # Indien
    "IN": "Indien",
    # Mexiko
    "MX": "Mexiko",
    # Brasilien
    "BR": "Brasilien",
    # Irland
    "IE": "Irland",
    # Luxemburg
    "LU": "Luxemburg",
}

CONTINENT_MAPPING = {
    "Deutschland": "Europa",
    "Vereinigtes Königreich": "Europa",
    "Frankreich": "Europa",
    "Niederlande": "Europa",
    "Belgien": "Europa",
    "Österreich": "Europa",
    "Schweiz": "Europa",
    "Italien": "Europa",
    "Spanien": "Europa",
    "Schweden": "Europa",
    "Norwegen": "Europa",
    "Dänemark": "Europa",
    "Finnland": "Europa",
    "Polen": "Europa",
    "Tschechien": "Europa",
    "Ungarn": "Europa",
    "Irland": "Europa",
    "Luxemburg": "Europa",
    "USA": "Nordamerika",
    "Kanada": "Nordamerika",
    "Mexiko": "Nordamerika",
    "Brasilien": "Südamerika",
    "Japan": "Asien",
    "China": "Asien",
    "Hongkong": "Asien",
    "Singapur": "Asien",
    "Indien": "Asien",
    "Australien": "Ozeanien",
}


def get_country_from_isin(isin):
    """Ermittelt das Land aus der ISIN."""
    country_code = isin[:2]
    return ISIN_COUNTRY_MAPPING.get(country_code, "Unbekannt")


def get_continent_from_country(country):
    """Ermittelt den Kontinent aus dem Ländernamen."""
    return CONTINENT_MAPPING.get(country, "Unbekannt")


def create_country_analysis(df_sektoren):
    """Erstellt Länder- und Kontinent-Analyse basierend auf ISINs."""
    df_country = df_sektoren.copy()
    
    # Land und Kontinent ermitteln
    df_country["Land"] = df_country["ISIN"].apply(get_country_from_isin)
    df_country["Kontinent"] = df_country["Land"].apply(get_continent_from_country)
    
    # Berechne Euro-Wert pro Land/Kontinent
    df_country["Sektor_Wert_EUR"] = (df_country["Kurswert_Asset_EUR"] * df_country["Gewicht_im_Asset_Prozent"]) / 100
    df_country["Sektor_Wert_EUR"] = df_country["Sektor_Wert_EUR"].round(2)
    
    # Aggregation nach Land
    df_land = df_country.groupby("Land", as_index=False)["Sektor_Wert_EUR"].sum()
    df_land = df_land.sort_values(by="Sektor_Wert_EUR", ascending=False)
    
    # Aggregation nach Kontinent
    df_kontinent = df_country.groupby("Kontinent", as_index=False)["Sektor_Wert_EUR"].sum()
    df_kontinent = df_kontinent.sort_values(by="Sektor_Wert_EUR", ascending=False)
    
    return df_country, df_land, df_kontinent


# ==========================================
# 3. STREAMLIT APP - SEKTOR ANALYZER
# ==========================================
def sektor_analyzer():
    st.title("📊 Aktienportfolio Analyzer - Sektor-Analyse")
    st.write("Laden Sie Ihre Trade Republic Vermögensübersicht hoch und analysieren Sie Ihr Portfolio nach Sektoren.")
    
    # Initialisiere Session State
    if "df_portfolio" not in st.session_state:
        st.session_state.df_portfolio = None
    if "df_sektoren" not in st.session_state:
        st.session_state.df_sektoren = None
    if "df_sektoren_geld" not in st.session_state:
        st.session_state.df_sektoren_geld = None
    if "unknown_securities" not in st.session_state:
        st.session_state.unknown_securities = None
    if "manual_sectors_input" not in st.session_state:
        st.session_state.manual_sectors_input = {}
    
    # ==========================================
    # SCHRITT 1: PDF UPLOAD
    # ==========================================
    st.header("Schritt 1: PDF Upload")
    
    uploaded_file = st.file_uploader("Laden Sie Ihre Trade Republic PDF hoch", type=["pdf"])
    
    if uploaded_file is not None:
        # Speichere PDF temporär
        pdf_bytes = uploaded_file.read()
        pdf_path = "temp_upload.pdf"
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
        
        if st.button("📂 PDF Verarbeiten"):
            with st.spinner("Lese PDF aus..."):
                st.session_state.df_portfolio = parse_vermoegensuebersicht_text_based(pdf_path)
            
            if not st.session_state.df_portfolio.empty:
                st.success(f"✅ {len(st.session_state.df_portfolio)} Positionen gefunden!")
                st.dataframe(st.session_state.df_portfolio)
            else:
                st.error("❌ Keine Positionen gefunden. Überprüfen Sie das PDF-Format.")
        
        # Cleanup
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
    
    # ==========================================
    # SCHRITT 2: SEKTOREN-ABFRAGE
    # ==========================================
    if st.session_state.df_portfolio is not None and not st.session_state.df_portfolio.empty:
        st.header("Schritt 2: Sektoren-Abfrage")
        
        if st.button("🔍 Sektoren via API abfragen"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            def progress_callback(progress):
                progress_bar.progress(progress)
                status_text.text(f"Verarbeitung: {int(progress * 100)}%")
            
            with st.spinner("Frage yfinance und OpenFIGI API ab..."):
                st.session_state.df_sektoren = create_sector_dataframe(
                    st.session_state.df_portfolio,
                    progress_callback=progress_callback
                )
            
            progress_bar.empty()
            status_text.empty()
            
            st.success("✅ Sektoren-Abfrage abgeschlossen!")
            
            # Finde unbekannte Sektoren
            unknown_df = st.session_state.df_sektoren[
                st.session_state.df_sektoren["Sektor"] == "Unbekannt / Keine Daten"
            ].drop_duplicates(subset=["ISIN"])
            
            if not unknown_df.empty:
                st.session_state.unknown_securities = unknown_df
                st.warning(f"⚠️ {len(unknown_df)} Wertpapiere haben keine Sektordaten gefunden!")
            else:
                st.info("✅ Alle Wertpapiere gefunden!")
        
        # Zeige detaillierte Sektoren
        if st.session_state.df_sektoren is not None:
            with st.expander("📋 Detaillierte Sektoren-Verteilung"):
                st.dataframe(st.session_state.df_sektoren)
    
    # ==========================================
    # SCHRITT 3: MANUELLE NACHTRAGUNG UNBEKANNTER SEKTOREN
    # ==========================================
    if st.session_state.unknown_securities is not None and not st.session_state.unknown_securities.empty:
        st.header("Schritt 3: Manuelle Nachtragung unbekannter Sektoren")
        st.write("Die folgenden Wertpapiere haben keine Sektordaten. Bitte tragen Sie diese manuell nach:")
        
        # Stelle alle bekannten Sektoren zusammen
        known_sectors = set(
            st.session_state.df_sektoren[
                st.session_state.df_sektoren["Sektor"] != "Unbekannt / Keine Daten"
            ]["Sektor"].unique()
        )
        known_sectors = sorted(list(known_sectors))
        
        for idx, row in st.session_state.unknown_securities.iterrows():
            isin = row["ISIN"]
            name = row["Wertpapier"]
            asset_type = row.get("Asset_Type", "Aktie")
            kurswert = row["Kurswert_Asset_EUR"]
            
            st.subheader(f"{name} ({isin})")
            st.write(f"**Typ:** {asset_type} | **Kurswert:** €{kurswert:.2f}")
            
            if asset_type == "ETF":
                st.write("Da dies ein ETF ist, können Sie mehrere Sektoren mit Prozentsätzen definieren:")
                
                # ETF: Mehrere Sektoren erlauben
                num_sectors = st.number_input(
                    f"Anzahl der Sektoren für {isin}",
                    min_value=1,
                    max_value=10,
                    value=1,
                    key=f"num_sectors_{isin}"
                )
                
                etf_sectors = {}
                total_percent = 0
                
                for i in range(num_sectors):
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        sector = st.selectbox(
                            f"Sektor {i+1}",
                            ["Neue Eingabe..."] + known_sectors,
                            key=f"etf_sector_{isin}_{i}"
                        )
                        
                        if sector == "Neue Eingabe...":
                            sector = st.text_input(
                                f"Neue Sektorbezeichnung {i+1}",
                                key=f"new_etf_sector_{isin}_{i}"
                            )
                    
                    with col2:
                        percent = st.number_input(
                            "Prozent",
                            min_value=0.0,
                            max_value=100.0,
                            value=100.0 / num_sectors,
                            step=0.1,
                            key=f"etf_percent_{isin}_{i}"
                        )
                    
                    if sector:
                        etf_sectors[sector] = percent
                        total_percent += percent
                
                if total_percent != 100:
                    st.warning(f"⚠️ Summe der Prozente: {total_percent:.1f}% (sollte 100% sein)")
                
                if etf_sectors:
                    st.session_state.manual_sectors_input[isin] = etf_sectors
            
            else:
                st.write("Da dies eine Aktie ist, wählen Sie einen Sektor aus:")
                
                sector = st.selectbox(
                    f"Sektor für {isin}",
                    ["Neue Eingabe..."] + known_sectors,
                    key=f"stock_sector_{isin}"
                )
                
                if sector == "Neue Eingabe...":
                    sector = st.text_input(
                        f"Neue Sektorbezeichnung",
                        key=f"new_stock_sector_{isin}"
                    )
                
                if sector:
                    st.session_state.manual_sectors_input[isin] = {sector: 100.0}
            
            st.divider()
        
        # Button zum Übernehmen der manuellen Einträge
        if st.button("✅ Manuelle Einträge übernehmen"):
            # Aktualisiere df_sektoren mit den manuellen Einträgen
            df_updated = st.session_state.df_sektoren.copy()
            
            # Entferne die alten unbekannten Einträge
            df_updated = df_updated[
                ~df_updated["ISIN"].isin(st.session_state.unknown_securities["ISIN"])
            ]
            
            # Füge neue Einträge hinzu
            neue_eintraege = []
            for isin, sectors_dict in st.session_state.manual_sectors_input.items():
                # Finde Original-Daten
                orig_row = st.session_state.unknown_securities[
                    st.session_state.unknown_securities["ISIN"] == isin
                ].iloc[0]
                
                for sektor, prozent in sectors_dict.items():
                    neue_eintraege.append({
                        "ISIN": isin,
                        "Wertpapier": orig_row["Wertpapier"],
                        "Kurswert_Asset_EUR": orig_row["Kurswert_Asset_EUR"],
                        "Sektor": sektor,
                        "Gewicht_im_Asset_Prozent": prozent,
                        "Asset_Type": orig_row.get("Asset_Type", "Aktie"),
                    })
            
            df_neue = pd.DataFrame(neue_eintraege)
            st.session_state.df_sektoren = pd.concat([df_updated, df_neue], ignore_index=True)
            
            st.success("✅ Manuelle Einträge aktualisiert!")
            st.session_state.unknown_securities = None
    
    # ==========================================
    # SCHRITT 4: BERECHNUNG UND VISUALISIERUNG
    # ==========================================
    if st.session_state.df_sektoren is not None and not st.session_state.df_sektoren.empty:
        # Überprüfe, ob noch unbekannte Sektoren existieren
        still_unknown = st.session_state.df_sektoren[
            st.session_state.df_sektoren["Sektor"] == "Unbekannt / Keine Daten"
        ]
        
        if still_unknown.empty:
            st.header("Schritt 4: Sektoren-Verteilung")
            
            # Berechne absolute Werte
            st.session_state.df_sektoren_geld = calculate_absolute_sector_distribution(
                st.session_state.df_sektoren
            )
            
            # Erstelle Pie Chart
            fig = go.Figure(data=[go.Pie(
                labels=st.session_state.df_sektoren_geld["Sektor"],
                values=st.session_state.df_sektoren_geld["Sektor_Wert_EUR"],
                hovertemplate="<b>%{label}</b><br>€%{value:.2f}<br>%{percent}<extra></extra>"
            )])
            
            fig.update_layout(
                title="Sektoren-Verteilung des Portfolios (in Euro)",
                height=600
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # Tabelle mit Sektoren und Werten
            st.subheader("📊 Sektoren-Übersicht")
            
            # Berechne auch Prozentanteile
            total_wert = st.session_state.df_sektoren_geld["Sektor_Wert_EUR"].sum()
            df_display = st.session_state.df_sektoren_geld.copy()
            df_display["Prozent_Anteil"] = (df_display["Sektor_Wert_EUR"] / total_wert * 100).round(2)
            df_display = df_display.rename(columns={
                "Sektor": "🏢 Sektor",
                "Sektor_Wert_EUR": "💶 Wert (EUR)",
                "Prozent_Anteil": "📈 Anteil (%)"
            })
            
            st.dataframe(
                df_display,
                use_container_width=True,
                hide_index=True
            )
            
            # Statistik
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("📈 Gesamtportfolio-Wert", f"€{total_wert:.2f}")
            with col2:
                st.metric("🏢 Anzahl Sektoren", len(st.session_state.df_sektoren_geld))
            with col3:
                st.metric("📊 Anzahl Positionen", len(st.session_state.df_portfolio))
            
            # ==========================================
            # SCHRITT 5: EXPORT UND MANUELLE BEARBEITUNG
            # ==========================================
            st.header("Schritt 5: Export & Manuelle Bearbeitung")
            
            st.subheader("💾 CSV-Export")
            
            col1, col2 = st.columns(2)
            
            with col1:
                csv_details = st.session_state.df_sektoren.to_csv(index=False, sep=";")
                st.download_button(
                    label="📥 Detaillierte Rohdaten herunterladen",
                    data=csv_details,
                    file_name="portfolio_sektoren_details.csv",
                    mime="text/csv"
                )
            
            with col2:
                csv_summary = st.session_state.df_sektoren_geld.to_csv(index=False, sep=";")
                st.download_button(
                    label="📥 Sektoren-Zusammenfassung herunterladen",
                    data=csv_summary,
                    file_name="portfolio_sektoren_euro_gesamt.csv",
                    mime="text/csv"
                )
            
            # Manuelle Bearbeitung
            st.subheader("✏️ Manuelle Bearbeitung")
            st.write("Sie können einzelne Positionen bearbeiten oder neue hinzufügen:")
            
            # Editable Tabelle für df_sektoren
            edited_df = st.data_editor(
                st.session_state.df_sektoren,
                use_container_width=True,
                num_rows="dynamic"
            )

            
            if st.button("💾 Änderungen speichern"):
                st.session_state.df_sektoren = edited_df
                st.session_state.df_sektoren_geld = calculate_absolute_sector_distribution(edited_df)
                st.success("✅ Änderungen gespeichert! Die Grafik wird neu berechnet.")
                st.rerun()
        else:
            st.warning("⚠️ Bitte tragen Sie zunächst alle unbekannten Sektoren nach!")


# ==========================================
# 4. STREAMLIT APP - LÄNDER ANALYZER
# ==========================================
def country_analyzer():
    st.title("🌍 Aktienportfolio Analyzer - Länder & Kontinent-Analyse")
    st.write("Analysieren Sie die geografische Diversifizierung Ihres Portfolios nach Ländern und Kontinenten.")
    
    # Initialisiere Session State (gleich wie in sektor_analyzer)
    if "df_portfolio" not in st.session_state:
        st.session_state.df_portfolio = None
    if "df_sektoren" not in st.session_state:
        st.session_state.df_sektoren = None
    if "df_country_analysis" not in st.session_state:
        st.session_state.df_country_analysis = None
    
    # ==========================================
    # SCHRITT 1: PDF UPLOAD
    # ==========================================
    st.header("Schritt 1: PDF Upload")
    
    uploaded_file = st.file_uploader("Laden Sie Ihre Trade Republic PDF hoch", type=["pdf"], key="country_uploader")
    
    if uploaded_file is not None:
        pdf_bytes = uploaded_file.read()
        pdf_path = "temp_upload_country.pdf"
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
        
        if st.button("📂 PDF Verarbeiten", key="country_parse"):
            with st.spinner("Lese PDF aus..."):
                st.session_state.df_portfolio = parse_vermoegensuebersicht_text_based(pdf_path)
            
            if not st.session_state.df_portfolio.empty:
                st.success(f"✅ {len(st.session_state.df_portfolio)} Positionen gefunden!")
                st.dataframe(st.session_state.df_portfolio)
            else:
                st.error("❌ Keine Positionen gefunden. Überprüfen Sie das PDF-Format.")
        
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
    
    # ==========================================
    # SCHRITT 2: SEKTOREN-ABFRAGE (notwendig für Länderanalyse)
    # ==========================================
    if st.session_state.df_portfolio is not None and not st.session_state.df_portfolio.empty:
        st.header("Schritt 2: Daten-Vorbereitung (Sektoren)")
        st.info("Hinweis: Für die Länderanalyse werden die Sektordaten benötigt (nur für Datenstruktur).")
        
        if st.button("🔍 Sektoren via API abfragen (für Länderanalyse)", key="country_api"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            def progress_callback(progress):
                progress_bar.progress(progress)
                status_text.text(f"Verarbeitung: {int(progress * 100)}%")
            
            with st.spinner("Frage yfinance und OpenFIGI API ab..."):
                st.session_state.df_sektoren = create_sector_dataframe(
                    st.session_state.df_portfolio,
                    progress_callback=progress_callback
                )
            
            progress_bar.empty()
            status_text.empty()
            st.success("✅ Daten-Vorbereitung abgeschlossen!")
    
    # ==========================================
    # SCHRITT 3: LÄNDER- UND KONTINENT-ANALYSE
    # ==========================================
    if st.session_state.df_sektoren is not None and not st.session_state.df_sektoren.empty:
        st.header("Schritt 3: Länder- & Kontinent-Analyse")
        
        # Erstelle Länderanalyse
        df_country, df_land, df_kontinent = create_country_analysis(st.session_state.df_sektoren)
        st.session_state.df_country_analysis = (df_country, df_land, df_kontinent)
        
        # Layout: Zwei Spalten für zwei Pie Charts
        col1, col2 = st.columns(2)
        
        # Pie Chart 1: Nach Ländern
        with col1:
            st.subheader("📍 Aufteilung nach Ländern")
            total_wert = df_land["Sektor_Wert_EUR"].sum()
            
            fig_land = go.Figure(data=[go.Pie(
                labels=df_land["Land"],
                values=df_land["Sektor_Wert_EUR"],
                hovertemplate="<b>%{label}</b><br>€%{value:.2f}<br>%{percent}<extra></extra>"
            )])
            fig_land.update_layout(height=500)
            st.plotly_chart(fig_land, use_container_width=True)
        
        # Pie Chart 2: Nach Kontinenten
        with col2:
            st.subheader("🌏 Aufteilung nach Kontinenten")
            
            fig_kontinent = go.Figure(data=[go.Pie(
                labels=df_kontinent["Kontinent"],
                values=df_kontinent["Sektor_Wert_EUR"],
                hovertemplate="<b>%{label}</b><br>€%{value:.2f}<br>%{percent}<extra></extra>"
            )])
            fig_kontinent.update_layout(height=500)
            st.plotly_chart(fig_kontinent, use_container_width=True)
        
        # ==========================================
        # DETAILLIERTE TABELLEN
        # ==========================================
        st.subheader("📊 Detailierte Länderübersicht")
        
        total_wert = df_land["Sektor_Wert_EUR"].sum()
        df_land_display = df_land.copy()
        df_land_display["Prozent_Anteil"] = (df_land_display["Sektor_Wert_EUR"] / total_wert * 100).round(2)
        df_land_display = df_land_display.rename(columns={
            "Land": "🌍 Land",
            "Sektor_Wert_EUR": "💶 Wert (EUR)",
            "Prozent_Anteil": "📈 Anteil (%)"
        })
        st.dataframe(df_land_display, use_container_width=True, hide_index=True)
        
        st.subheader("📊 Detaillierte Kontinentübersicht")
        
        df_kontinent_display = df_kontinent.copy()
        df_kontinent_display["Prozent_Anteil"] = (df_kontinent_display["Sektor_Wert_EUR"] / total_wert * 100).round(2)
        df_kontinent_display = df_kontinent_display.rename(columns={
            "Kontinent": "🌏 Kontinent",
            "Sektor_Wert_EUR": "💶 Wert (EUR)",
            "Prozent_Anteil": "📈 Anteil (%)"
        })
        st.dataframe(df_kontinent_display, use_container_width=True, hide_index=True)
        
        # ==========================================
        # STATISTIKEN
        # ==========================================
        st.subheader("📈 Geografische Diversifizierung")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("🌍 Gesamtwert Portfolio", f"€{total_wert:.2f}")
        with col2:
            st.metric("🗺️ Länder", len(df_land))
        with col3:
            st.metric("🌏 Kontinente", len(df_kontinent))
        with col4:
            # Diversifizierungsindex (höher = besser diversifiziert)
            diversification = len(df_land) / max(len(df_kontinent), 1)
            st.metric("📊 Diversifizierungs-Index", f"{diversification:.2f}")
        
        # ==========================================
        # EXPORT
        # ==========================================
        st.subheader("💾 CSV-Export")
        
        col1, col2 = st.columns(2)
        
        with col1:
            csv_land = df_land.to_csv(index=False, sep=";")
            st.download_button(
                label="📥 Länder-Aufteilung herunterladen",
                data=csv_land,
                file_name="portfolio_laender.csv",
                mime="text/csv"
            )
        
        with col2:
            csv_kontinent = df_kontinent.to_csv(index=False, sep=";")
            st.download_button(
                label="📥 Kontinent-Aufteilung herunterladen",
                data=csv_kontinent,
                file_name="portfolio_kontinente.csv",
                mime="text/csv"
            )


# ==========================================
# 5. HAUPTAPP MIT NAVIGATION
# ==========================================
def main():
    st.set_page_config(page_title="Aktienportfolio Analyzer", layout="wide")
    
    # Erstelle Navigation mit zwei Seiten
    sektor_page = st.Page(sektor_analyzer, title="Sektor-Analyse", icon="📊")
    country_page = st.Page(country_analyzer, title="Länder & Kontinente", icon="🌍")
    
    pg = st.navigation([sektor_page, country_page])
    pg.run()


if __name__ == "__main__":
    main()