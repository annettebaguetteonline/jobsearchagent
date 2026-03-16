# ADR-005: Explizites `sector`-Feld für öffentlichen vs. privaten Sektor

**Status:** Accepted
**Stand:** März 2026

---

## Kontext

Mit service.bund.de als Quelle entstehen strukturell unterschiedliche Job-Typen:
- **Öffentlicher Dienst** (service.bund.de, interamt.de, Landesportale): TVöD/TV-L,
  Verbeamtung möglich, andere Bewerbungsprozesse, Jobsicherheit
- **Privatwirtschaft** (StepStone, Indeed, Firmenwebsites): marktübliche Gehälter,
  variable Prozesse

Diese Unterscheidung beeinflusst:
- Die Evaluation-Pipeline (andere Bewertungskriterien)
- Das Dashboard (getrennte Ansichten / Filter)
- Den Anschreiben-Generator (formellerer Stil für Behörden)

Alternativen für die Implementierung:
1. Feld `sector` explizit in `jobs`-Tabelle
2. Ableitbar aus `job_sources.source_name` zur Laufzeit
3. Kein Feld — Evaluation-Pipeline erkennt aus Jobtitel/Beschreibung

## Entscheidung

**Option 1: Explizites `sector`-Feld.**

Werte: `'public'` | `'private'` | `NULL` (unbekannt/nicht zugeordnet).

Gesetzt vom Scraper (nicht vom LLM):
- `ServiceBundScraper`: `sector = "public"` (alle Stellen)
- `StepstoneScraper`: `sector = None` (Aggregator, gemischt)
- künftige direkte Behörden-Scraper: `sector = "public"`
- künftige direkte Firmen-Scraper: `sector = "private"`

## Konsequenzen

- Datenbankschema: Migration 002 ergänzt `sector TEXT` in `jobs`
- `ScrapedJob`-Modell erhält `sector: str | None = None`
- `JobCreate`-Modell und `Job`-Modell erben `sector`
- `insert_job()` übergibt `sector` in den INSERT
- Evaluation-Pipeline kann `sector` als Signal nutzen ohne erneutes LLM-Parsing
- Für StepStone bleibt `sector = NULL` — Evaluation muss ggf. aus Beschreibung ableiten

## Alternativen verworfen

- **Aus `source_name` ableiten:** Funktioniert für bekannte Quellen, versagt bei
  Aggregatoren (StepStone listet auch Behördenstellen) und neuen Quellen
- **LLM-Erkennung:** Zu kostspielig für jeden Job, redundant wenn die Quelle
  den Sektor schon bekannt macht
