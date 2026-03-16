# Scraper-Dokumentation

## Übersicht

Der Job Search Agent verwendet drei generische Scraper-Typen:

| Typ | Beschreibung | Technologie | Beispiele |
|-----|-------------|-------------|-----------|
| **A – Strukturiert** | Stabiler RSS-Feed oder öffentliche API | `httpx` + `xml.etree` | service.bund.de, Bundesagentur, Arbeitnow |
| **B – Konfigurierbar** | JavaScript-SPA, bekanntes Layout | Playwright + Chromium | interamt.de, karriere.hessen.de |
| **C – Generisch** | Beliebige Websites | Playwright + LLM-Extraktion | Behörden, Firmen-Karriereseiten |

---

## Implementierungsstatus

| Quelle | Typ | Status | Volltext | Datei |
|--------|-----|--------|---------|-------|
| service.bund.de | A | ✅ Live | ✅ (RSS `<description>`) | `app/scraper/portals/service_bund.py` |
| Bundesagentur für Arbeit | A | ✅ Live | ✅ (Detail-API `stellenbeschreibung`) | `app/scraper/portals/arbeitsagentur.py` |
| Arbeitnow | A | ✅ Live | ✅ (API `description`) | `app/scraper/portals/arbeitnow.py` |
| Jooble | A | ✅ Live | ⚠️ Nur Snippet | `app/scraper/portals/jooble.py` |
| Adzuna | A | ✅ Live | ⚠️ Nur Snippet | `app/scraper/portals/adzuna.py` |
| Kimeta | A | ✅ Live | ⚠️ Nur iframe-URLs (ADR-006) | `app/scraper/portals/kimeta.py` |
| Jobbörse.de | A | ✅ Live | ✅ (Detail-Seite HTML) | `app/scraper/portals/jobboerse.py` |
| Stellenmarkt.de | A | ✅ Live | ⚠️ Snippet (RSS) | `app/scraper/portals/stellenmarkt.py` |
| interamt.de | B | ✅ Live (ADR-004) | ✅ (Detail-Seite HTML) | `app/scraper/portals/interamt.py` |
| karriere.hessen.de | B | 📋 Geplant | — | — |
| karriere.rlp.de | B | 📋 Geplant | — | — |
| Indeed | A | 📋 Geplant | — | — |
| XING | B | 📋 Geplant | — | — |
| academics.de | B | 📋 Geplant | — | — |
| Individuelle Behörden | C | 📋 Geplant | — | — |
| Firmen-Karriereseiten | C | 📋 Geplant | — | — |

---

## Architektur

### Klassenstruktur

```
BaseScraper (ABC)                   app/scraper/base.py
├── fetch_jobs() → list[ScrapedJob]  # abstrakt, von Subklassen implementiert
└── run(db, run_id?)                 # Template-Method: fetch → dedup → insert

ScrapedJob (Pydantic)               app/scraper/base.py
├── title, company_name, url         # Pflichtfelder
├── location_raw, work_model         # Optional
├── deadline, salary_raw, raw_text   # Optional
├── source_job_id                    # Quell-native ID für Stage-0-Dedup
└── sector                           # 'public'|'private'|None
```

### Deduplizierungs-Pipeline

Implementiert in `BaseScraper._process_job()`. Drei aufeinanderfolgende Stufen:

```
Stufe 0 │ source_job_id vorhanden? → Suche in job_sources(source_name, source_job_id)
        │ Treffer → update last_seen_at → 'duplicate'
        ▼
Stufe 1 │ canonical_id = SHA256(norm_titel|norm_firma|norm_ort_ohne_plz)
        │ Suche in jobs(canonical_id)
        │ Treffer → update last_seen_at → 'duplicate'
        ▼
Stufe 2 │ Fuzzy-Match: difflib ≥ 85% gegen alle Titel der Firma
        │ Treffer → 'duplicate'
        ▼
        │ Neu → insert_job + insert_job_source → 'new'
```

Siehe [ADR-001](../adr/001-dreistufige-deduplizierung.md) für die Designentscheidung.

### Ortsfeld und PLZ-Normalisierung

service.bund.de liefert `"34117 Kassel"`, StepStone liefert `"Kassel"`. Um
quell-übergreifende Duplikate zu erkennen, wird die PLZ in `compute_canonical_id()`
entfernt. `location_raw` behält das Original-Format.

Siehe [ADR-002](../adr/002-plz-normalisierung-canonical-id.md).

---

## Neuen Typ-A-Scraper hinzufügen

1. **Neue Datei** anlegen: `app/scraper/portals/<quellname>.py`

2. **`BaseScraper` implementieren:**
   ```python
   from app.scraper.base import BaseScraper, ScrapedJob

   class MeinScraper(BaseScraper):
       source_name = "meine_quelle"
       source_type = "portal"  # oder 'aggregator'

       async def fetch_jobs(self) -> list[ScrapedJob]:
           # HTTP-Request → Parsing → ScrapedJob-Liste
           return [
               ScrapedJob(
                   title="...",
                   company_name="...",
                   url="...",
                   source_job_id="...",  # wenn verfügbar
                   sector="public",      # wenn öffentlicher Dienst
               )
           ]
   ```

3. **In der API-Registry registrieren** (`app/api/scrape.py`):
   ```python
   _SCRAPERS = {
       "stepstone": StepstoneScraper,
       "service_bund": ServiceBundScraper,
       "meine_quelle": MeinScraper,  # ← hier ergänzen
   }
   ```

4. **Tests schreiben:** `tests/unit/test_<quellname>_scraper.py`
   - Parsing-Funktionen für Feed-Struktur
   - Datumsfilter
   - source_job_id-Extraktion
   - Ungültiges XML / HTTP-Fehler

---

## Konfiguration

Alle Scraping-Parameter in `app/core/config.py` / `.env`:

| Variable | Standard | Beschreibung |
|----------|---------|-------------|
| `SCRAPE_KEYWORDS` | `[]` | Keywords für StepStone-Suche (leer = alle) |
| `SCRAPE_LOCATIONS` | Frankfurt, Wiesbaden, Darmstadt, Remote | Orte für StepStone |
| `SCRAPE_RADIUS_KM` | `50` | Suchradius für StepStone |
| `SCRAPE_POSTED_WITHIN_DAYS` | `2` | Maximales Alter von Stellenanzeigen (0 = kein Filter) |
