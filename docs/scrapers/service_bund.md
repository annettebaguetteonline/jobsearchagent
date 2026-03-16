# service.bund.de RSS-Scraper

**Typ:** A (Strukturiert)
**Status:** ✅ Live
**Implementierung:** `app/scraper/portals/service_bund.py`
**Sektor:** Öffentlicher Dienst (`sector="public"` für alle Stellen)

---

## Feed-Struktur

service.bund.de stellt einen bundesweiten RSS-Feed für Stellenangebote bereit:

```
https://www.service.bund.de/Content/Globals/Functions/RSSFeed/RSSGenerator_Stellen.xml
```

**Kein Bundesland-Filter** — der Feed liefert immer alle bundesweiten Stellen.
Hintergrund: [ADR-003](../adr/003-service-bund-kein-ortsfilter.md).

---

## RSS-Item-Struktur

```xml
<item>
  <title>Sachbearbeiterin/Sachbearbeiter Personal (w/m/d)</title>

  <!-- Link enthält #track=feed-jobs — wird nicht verwendet -->
  <link>https://www.service.bund.de/.../Sachbearbeiter-Personal-1111111.html#track=feed-jobs</link>

  <!-- GUID ist die saubere URL — wird als job.url und für source_job_id verwendet -->
  <guid>https://www.service.bund.de/.../Sachbearbeiter-Personal-1111111.html</guid>

  <pubDate>Thu, 12 Mar 2026 14:00:00 +0100</pubDate>

  <description><![CDATA[
    Arbeitgeber: <strong>Landesbetrieb Landwirtschaft Hessen (LLH)</strong><br />
    Ort: <strong>34117 Kassel</strong><br />
    Bewerbungsfrist: <strong>03.04.2026 23:59</strong><br />
    Veröffentlichungsende: <strong>03.04.2026 23:59</strong>
  ]]></description>
</item>
```

### URL: GUID statt Link

`<link>` enthält `#track=feed-jobs` am Ende — ein Tracking-Parameter.
`<guid>` ist identisch ohne diesen Suffix. Der Scraper verwendet **immer `<guid>`** als URL.

### CDATA-Beschreibungs-Parsing

Die Beschreibung ist HTML in CDATA eingebettet. Extraktion via Regex:

| Feld | Regex | Beispiel |
|------|-------|---------|
| Arbeitgeber | `r'Arbeitgeber:\s*<strong>(.*?)</strong>'` | `"Landesbetrieb Landwirtschaft Hessen (LLH)"` |
| Ort | `r'Ort:\s*<strong>(.*?)</strong>'` | `"34117 Kassel"` |
| Bewerbungsfrist | `r'Bewerbungsfrist:\s*<strong>(.*?)</strong>'` | `"03.04.2026 23:59"` |

### Ortsfeld

Format: `"PLZ Stadt"` (z.B. `"34117 Kassel"`). Wird unverändert als `location_raw` gespeichert.
Für die `canonical_id`-Berechnung wird die PLZ via `_strip_plz()` entfernt — dadurch
ergibt sich quell-übergreifend dieselbe canonical_id wie für StepStone-Einträge mit `"Kassel"`.

Siehe [ADR-002](../adr/002-plz-normalisierung-canonical-id.md).

### Deadline-Konvertierung

Format in der Quelle: `"DD.MM.YYYY HH:MM"` (z.B. `"03.04.2026 23:59"`)
Gespeichert als ISO-8601 UTC: `"2026-04-03T23:59:00Z"`

Implementiert in `_parse_deadline()`. Behandelt auch `"DD.MM.YYYY"` ohne Uhrzeit.
Ungültige Formate → `None` (Fehlertoleranz).

### source_job_id

Numerische ID aus dem GUID-Pfad:
```
URL: .../INPCOX-Sachbearbeiter-Personal-1111111.html
ID:  1111111
```

Regex: `r"-(\d+)\.html$"` — letztes Segment mit numerischem Suffix vor `.html`.

---

## Konfiguration

| Setting | Wert für service.bund.de |
|---------|--------------------------|
| `source_name` | `"service_bund"` |
| `source_type` | `"portal"` |
| `sector` | `"public"` (alle Stellen) |
| `scrape_posted_within_days` | Geteilt mit allen Scrapern (Standard: 2) |

Kein Ort- oder Keyword-Parameter — der Feed hat keine wirksamen Filter.

---

## Sektor

Alle Stellen von service.bund.de sind Öffentlicher Dienst. Der Scraper setzt deshalb
für jeden `ScrapedJob` explizit `sector = "public"`.

Hintergrund: [ADR-005](../adr/005-sektor-feld.md).

---

## Bekannte Einschränkungen

- Kein Volltext der Stellenanzeige — `raw_text` enthält nur CDATA-Snippet (~4 Felder)
- Kein Gehaltsfeld (`salary_raw = None`) — TVöD/TV-L-Eingruppierung steht im Volltext
- Kein `work_model`-Feld — Remote/Hybrid muss aus Volltext abgeleitet werden
- Kein Pagination-Problem — der Feed enthält immer aktuelle Stellen (~200–500 Items)
- Bewerbungsfrist != Veröffentlichungsende — beide können im CDATA stehen, nur `Bewerbungsfrist` wird verwendet

---

## Tests

`tests/unit/test_service_bund_scraper.py` — 21 Tests:
- `_parse_deadline`: Vollformat, nur Datum, ungültig, Whitespace
- `_extract_source_job_id`: numerischer Suffix, doppelter Bindestrich, kein ID
- `_is_recent`: kein Datum, `max_days=0`, altes Datum, ungültig
- `_parse_rss_item`: vollständiges CDATA, GUID vs. Link, fehlende Frist, fehlendes Titel, sector
- `_parse_feed`: Fixture (3 aktuelle + 1 altes), Datumsfilter, ungültiges XML, sector, source_job_ids
