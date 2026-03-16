# ADR-001: Dreistufige Deduplizierungsstrategie

**Status:** Accepted
**Stand:** März 2026

---

## Kontext

Mehrere Scraper-Quellen (StepStone, service.bund.de, künftig weitere) scrapen denselben
Stellenmarkt. Dieselbe Stelle kann auf mehreren Portalen erscheinen, oder dieselbe Quelle
kann die gleiche Stelle bei zwei aufeinanderfolgenden Scraping-Läufen liefern.

Ziele der Deduplizierung:
- Keine doppelten Einträge in der `jobs`-Tabelle
- Trotzdem alle Quell-URLs als `job_sources` erhalten (für Nachverfolgung)
- Bestehende Jobs mit aktualisiertem `last_seen_at` markieren
- Verschiedene Titelformulierungen derselben Stelle erkennen

## Entscheidung

Drei aufeinanderfolgende Deduplizierungs-Stufen, implementiert in `BaseScraper._process_job()`:

### Stufe 0 — Source-Job-ID-Match
Wenn der Scraper eine `source_job_id` liefert (quell-native ID, z.B. aus der URL),
wird zuerst in `job_sources` nach `(source_name, source_job_id)` gesucht.

- **Trefferquote:** 100% für Rückkehr derselben Quelle mit gleicher ID
- **Kosten:** eine DB-Abfrage, kein String-Hashing
- **Vorteil:** Erkennt Duplikate selbst wenn Titel oder Standort sich leicht geändert haben

### Stufe 1 — Canonical-ID Hash-Match
SHA-256 über normalisierter `titel|firma|ort`-Kombination (ohne PLZ-Präfix).

- **Trefferquote:** Hoch für quell-übergreifende Duplikate (gleiche Stelle, gleiche Firma, gleicher Ort)
- **Kosten:** eine DB-Abfrage nach `canonical_id`
- **Einschränkung:** Schlägt fehl bei leicht variierendem Titel oder Ort

### Stufe 2 — Fuzzy-Match
`difflib.SequenceMatcher` vergleicht neuen Titel mit allen bekannten Titeln derselben Firma.
Schwellwert: ≥ 85% Ähnlichkeit.

- **Trefferquote:** Erkennt `"Python Developer (m/w/d)"` ≈ `"Python-Entwickler (m/w/d)"`
- **Kosten:** O(n) pro Firma — akzeptabel da Firmen selten mehr als ~50 aktive Stellen haben
- **Einschränkung:** Kann False Positives bei Firmen mit vielen ähnlichen Stellen produzieren

## Konsequenzen

- `job_sources` erhält das Feld `source_job_id` (Migration 002)
- Alle Scraper sollten `source_job_id` befüllen um Stufe 0 nutzen zu können
- Stufe 2 ist der einzige nicht-deterministische Teil — `_FUZZY_THRESHOLD = 0.85` ist
  ein Kompromiss und kann ggf. pro Quelle überschrieben werden
- Bei False Positives in Stufe 2: Schwellwert erhöhen oder Stufe 2 deaktivieren

## Alternativen verworfen

- **Nur URL-basiert:** Fragil, URLs können sich ändern, erkennt keine Cross-Source-Duplikate
- **Nur Fuzzy:** Zu langsam ohne vorherige Hash-Filterung
- **Embedding-basiert:** Zu teuer für Scraping-Frequenz (täglich), ChromaDB für Evaluation reserviert
