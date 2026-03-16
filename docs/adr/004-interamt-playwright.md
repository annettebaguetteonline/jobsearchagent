# ADR-004: interamt.de — Reklassifizierung zu Typ B (Playwright)

**Status:** Accepted
**Stand:** März 2026
**Implementiert:** März 2026

---

## Kontext

Das ursprüngliche Design-Dokument klassifizierte interamt.de als **Typ A**
("Strukturiert — stabile API oder RSS-Feed") mit der Begründung "URL-Parameter-API".

Bei der Implementierungsvorbereitung wurde der Browser-Netzwerk-Tab analysiert.

### Befund aus dem Netzwerk-Tab

```
GET /koop/app/trefferliste?4-1.0-&windowName=92e4a9e8-4ffb-48ba-852a-f28804702309&_=1773330874099
Host: www.interamt.de
Accept: application/xml, text/xml, */*; q=0.01
Wicket-Ajax: true
Wicket-Ajax-BaseURL: koop/app/trefferliste
Wicket-FocusedElementId: comp3

Response:
  Content-Type: text/xml;charset=UTF-8
  → Wicket-internes AJAX-Protokoll (Component-Update-XML, keine Job-Daten)
```

interamt.de verwendet **Apache Wicket** — ein zustandsbehaftetes Java-Web-Framework.

### Warum Typ A nicht funktioniert

- **Session-gebunden:** Jeder Request benötigt `JSESSIONID` und `windowName`
  (eine UUID pro Browser-Session), die durch vorherige Requests etabliert werden
- **Kein REST:** Die URL-Parameter `4-1.0-` sind Wickets interne Komponenten-IDs,
  keine öffentliche API
- **Stateful AJAX:** Jeder Request baut auf Prior-Navigation-State auf —
  nicht replizierbar mit einfachem `httpx`-Request
- **Kein RSS-Feed** vorhanden

## Entscheidung

interamt.de wird als **Typ B (Playwright)** implementiert — in einem separaten Sprint.

Playwright kann:
- Eine vollständige Browser-Session aufbauen (inkl. `JSESSIONID`)
- Die Seite navigieren und Suchergebnisse laden
- Den gerenderten DOM auslesen
- Pagination durchlaufen

## Konsequenzen

- interamt.de-Scraper ist implementiert (`app/scraper/portals/interamt.py`) und in `_SCRAPERS` registriert
- Playwright-Integration erfolgte direkt in `BaseScraper` (kein separates `PlaywrightBaseScraper` nötig)
- Docker-Image enthält Playwright + Chromium (via `playwright install chromium --with-deps`)
- `raw_text` wird via httpx-Detail-Fetch befüllt (`_fetch_raw_text`); Playwright nur für Listing-Pagination

## Alternativen verworfen

- **Session-Engineering via httpx:** Theoretisch möglich, aber extrem fragil bei
  Wicket-Framework-Updates oder Session-Invalidierung
- **Anderes Portal für Öffentlicher Dienst:** service.bund.de deckt bundesweite
  Stellen bereits ab — interamt.de hat Überschneidungen, ist aber ergänzend sinnvoll
