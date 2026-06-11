# 📊 Aktienportfolio Analyzer

Eine Streamlit-Anwendung zur Analyse und Visualisierung von Trade Republic Depots nach Sektoren.

## 🎯 Funktionsweise

### Ablauf der Analyse:

1. **PDF Upload** → Laden Sie Ihre Trade Republic Vermögensübersicht hoch
2. **Daten-Extraktion** → Automatische Extraktion von Wertpapieren, ISIN und Kurswerten
3. **Sektoren-Abfrage** → Automatische Abfrage via OpenFIGI API und yfinance
4. **Manuelle Nachtragung** → Für nicht gefundene Wertpapiere (mit ETF/Aktien-Unterscheidung)
5. **Visualisierung** → Pie Chart und detaillierte Tabellen
6. **Export** → CSV-Download der Rohdaten und Zusammenfassung
7. **Manuelle Bearbeitung** → Nachträgliche Anpassung einzelner Positionen

## 🔧 Installation

### Voraussetzungen:
- Python 3.8+
- pip

### Setup:

```bash
# 1. Abhängigkeiten installieren
pip install -r requirements.txt

# 2. App starten
streamlit run app.py
```

## 📋 Abhängigkeiten

```
streamlit>=1.28.0
pdfplumber>=0.10.0
pandas>=2.0.0
yfinance>=0.2.0
requests>=2.31.0
plotly>=5.17.0
```

## 📊 Datenfluss

```
PDF-Upload
    ↓
parse_vermoegensuebersicht_text_based()
    ↓ (df_portfolio: Wertpapier, ISIN, Kurswert_EUR)
    ↓
detect_asset_type() + get_sector_weights()
    ↓ (df_sektoren: ISIN, Wertpapier, Kurswert_Asset_EUR, Sektor, Gewicht_im_Asset_Prozent, Asset_Type)
    ↓
Manuelle Nachtragung für unbekannte Sektoren
    ↓
calculate_absolute_sector_distribution()
    ↓ (df_sektoren_geld: Sektor, Sektor_Wert_EUR)
    ↓
Pie Chart + Tabelle
```

## 🔍 Wichtige Features

### ETF vs. Aktien
- **Aktien**: Automatisch erkannt über `yfinance` (quoteType = "EQUITY")
- **ETFs**: Automatisch erkannt über `yfinance` (quoteType = "ETF")

### Manuelle Nachtragung
- **Aktien**: Einzelnen Sektor auswählen
- **ETFs**: Bis zu 10 Sektoren mit individuellen Prozentsätzen möglich

### Sektoren-Normalisierung
Die App nutzt die folgenden standardisierten Sektoren von yfinance:
- Technologie
- Finanzen
- Gesundheitswesen
- Zyklische Konsumgüter
- Nichtzyklische Konsumgüter
- Telekommunikation
- Energie
- Industrie
- Grundstoffe
- Immobilien
- Versorger

## 📁 Ausgangsdaten

Die App generiert folgende DataFrames:

### df_portfolio
```
Wertpapier | ISIN      | Kurswert_EUR
-----------|-----------|-------------
Allianz    | DE000001  | 1500.00
iShares... | IE000002  | 2000.00
```

### df_sektoren
```
ISIN      | Wertpapier | Kurswert_Asset_EUR | Sektor         | Gewicht_im_Asset_Prozent | Asset_Type
----------|-----------|-------------------|----------------|-------------------------|----------
DE000001  | Allianz    | 1500.00           | Finanzen       | 100.0                   | Aktie
IE000002  | iShares    | 2000.00           | Technologie    | 45.0                    | ETF
IE000002  | iShares    | 2000.00           | Finanzen       | 30.0                    | ETF
IE000002  | iShares    | 2000.00           | Gesundheit     | 25.0                    | ETF
```

### df_sektoren_geld
```
Sektor        | Sektor_Wert_EUR
--------------|----------------
Finanzen      | 1950.00
Technologie   | 900.00
Gesundheit    | 500.00
```

## 🚀 Verwendung

### Schritt-für-Schritt:

1. **Starten Sie die App**:
   ```bash
   streamlit run app.py
   ```

2. **Laden Sie Ihre PDF hoch** → "PDF Verarbeiten" klicken

3. **Starten Sie die Sektoren-Abfrage** → "Sektoren via API abfragen" klicken

4. **Tragen Sie unbekannte Sektoren manuell nach** (sofern nötig)

5. **Ansicht der Pie Chart** und Download der CSV-Dateien

6. **Optional: Manuelle Bearbeitung** einzelner Positionen mit "data_editor"

## 📝 CSV-Exports

### portfolio_sektoren_details.csv
Detaillierte Rohdaten mit allen Positionen aufgeschlüsselt nach Sektoren (Trennzeichen: `;`)

### portfolio_sektoren_euro_gesamt.csv
Zusammenfassung mit Gesamtwert pro Sektor (Trennzeichen: `;`)

## ⚠️ Bekannte Limitationen

1. **API-Rate-Limiting**: OpenFIGI hat Rate-Limits (verzögerung von 0.5s zwischen Anfragen)
2. **Sektoren-Konsistenz**: yfinance nutzt teilweise unterschiedliche Bezeichnungen für Sektoren
3. **Manuelle PDF-Formate**: Die App ist optimiert für Trade Republic PDFs; andere Brokers müssen angepasst werden
4. **Weekend/Holiday**: yfinance kann am Wochenende oder an Feiertagen keine Kurse liefern

## 🔮 Zukünftige Erweiterungen (Roadmap)

- [ ] Zielwerte pro Sektor definieren (z.B. max 30% Technologie)
- [ ] Automatische Benachrichtigungen bei Abweichungen
- [ ] Mehrsprachige UI
- [ ] Historische Daten und Trend-Tracking
- [ ] Integration mit anderen Brokern
- [ ] Benchmark-Vergleiche (z.B. DAX, MSCI World)

## 📞 Support / Troubleshooting

### Problem: "Keine Positionen gefunden"
- Überprüfen Sie das PDF-Format (muss Trade Republic sein)
- Stellen Sie sicher, dass der BROKERAGE-Bereich sichtbar ist

### Problem: "API-Fehler bei OpenFIGI"
- Dies ist normalerweise vorübergehend
- Die App versucht, die Anfrage später erneut

### Problem: "yfinance kann Ticker nicht finden"
- Die ISIN wird manuell nachtragen müssen
- Sie können einen custom Ticker in der manuellen Nachtragung eingeben

## 📄 Lizenz

Dieses Projekt ist frei verfügbar und kann beliebig angepasst werden.
