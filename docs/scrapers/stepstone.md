# StepStone RSS-Scraper

**Typ:** A (Strukturiert)
**Status:** ✅ Live
**Implementierung:** `app/scraper/portals/stepstone.py`
**Sektor:** gemischt (Aggregator, `sector=None`)

---

## Feed-Struktur

StepStone stellt RSS-Feeds mit Such-Parametern bereit:

```
https://www.stepstone.de/rss/joboffers/?where=Frankfurt&radius=50&language=2&sortOrder=date
```

| Parameter | Werte | Beschreibung |
|-----------|-------|-------------|
| `where` | Stadtname | Suchort (leer = deutschlandweit) |
| `radius` | km (z.B. `50`) | Suchradius um `where` |
| `language` | `2` = Deutsch | Stellensprache |
| `sortOrder` | `date` | Sortierung nach Erscheinungsdatum |
| `what` | Keyword (optional) | Keyword-Filter |

**URL-Generierung:** `_build_rss_urls()` erzeugt eine URL pro `(keyword × location)`-Kombination.
Wenn keine Keywords konfiguriert sind: eine URL pro Location.

---

## RSS-Item-Struktur

```xml
<item>
  <title>Senior Python Developer (m/w/d) - Acme Software GmbH</title>
  <link>https://www.stepstone.de/stellenangebote--Senior-Python-Developer--12345678-inline.html</link>
  <pubDate>Thu, 12 Mar 2026 08:00:00 +0000</pubDate>
  <description>
    &lt;p&gt;Beschreibungstext mit Standortinfos...&lt;/p&gt;
  </description>
</item>
```

### Titel-Parsing

Format: `"Jobtitel (m/w/d) - Firmenname"` — Split am **letzten** ` - ` (nicht am ersten,
da Titel wie `"Senior - Lead Engineer (m/w/d) - Acme"` vorkommen).

Implementiert in `_split_title_company()`. Fallback: `company_name = "Unbekannt"`.

### Ortsextraktion

StepStone verwendet keine XML-Namespaces für Firmenname oder Ort. Der Ort wird per
Heuristik-Regex aus dem HTML-`<description>`-Snippet extrahiert:

```python
r"\b(Remote|Frankfurt|Berlin|München|Hamburg|...)\b"
```

**Bekannte Einschränkung:** Erkennt nur vorkonfigurierte Städtenamen. Unbekannte Orte
geben `location_raw = None` zurück — wird in der Evaluation-Pipeline aufgelöst.

### source_job_id

Numerische Job-ID aus der URL extrahiert:
```
URL: .../stellenangebote--Titel--12345678-inline.html
ID:  12345678
```

Regex: `r"[-/](\d{6,})(?:[-/.?#]|$)"` — mindestens 6 Stellen, gefolgt von Trennzeichen.

---

## Anti-Detection

StepStone gibt bei verdächtigem Scraping-Verhalten HTTP 429 zurück.

Maßnahmen:
- **Zufälliger Delay** 2–8 Sekunden zwischen Feed-Requests (`random.uniform(2.0, 8.0)`)
- **User-Agent-Rotation** aus 3 realistischen Chrome-Browser-Strings
- **Einzelner RSS-Feed pro Request** (kein paralleles Fetching)

---

## Konfiguration (via Settings)

```python
scrape_keywords: list[str] = []          # leer = kein Keyword-Filter
scrape_locations: list[str] = [           # eine URL pro Location
    "Frankfurt", "Wiesbaden", "Darmstadt", "Remote"
]
scrape_radius_km: int = 50
scrape_posted_within_days: int = 2        # 0 = kein Altersfilter
```

---

## Bekannte Einschränkungen

- Kein RSS-Feed für alle Stellenangebote ohne Ortsangabe — `where=""` gibt wenige Ergebnisse
- Beschreibung ist HTML-Snippet, kein Volltext — raw_text enthält nur Teaser
- Firmename aus Titel (nicht aus eigenem XML-Feld) — kann bei ungewöhnlichen Formaten fehlschlagen
- Kein Gehaltsfeld im RSS-Feed — `salary_raw = None` für alle StepStone-Jobs
- Kein `deadline`-Feld im RSS — öffentliche Stellenanzeigen auf StepStone haben keine Frist

---

## Tests

`tests/unit/test_stepstone_scraper.py` — 25 Tests:
- `normalize_text`, `compute_canonical_id`
- `_split_title_company`: Standard, ohne Separator, mehrere Bindestriche
- `_is_recent`: aktuell, alt, kein Datum, `max_days=0`
- `_parse_feed`: Fixture mit 3 aktuellen + 1 alten Item
- `_build_rss_urls`: ohne Keywords, mit Keywords
- `source_job_id`-Extraktion aus URL
