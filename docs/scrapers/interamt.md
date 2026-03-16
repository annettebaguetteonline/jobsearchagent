# interamt.de — Geplanter Typ-B-Scraper

**Typ:** B (Playwright) — ursprünglich als Typ A geplant
**Status:** 🔄 Deferred — separater Sprint
**Sektor:** Öffentlicher Dienst (`sector="public"`)

---

## Hintergrund

interamt.de war im ursprünglichen Design-Dokument als **Typ A** ("URL-Parameter-API")
klassifiziert. Eine Analyse des Netzwerk-Traffics ergab jedoch, dass die Site
Apache Wicket (Java-Framework) verwendet — eine zustandsbehaftete AJAX-Architektur,
die mit einfachen HTTP-Requests nicht reproduzierbar ist.

Details: [ADR-004](../adr/004-interamt-playwright.md).

---

## Technische Analyse

### Netzwerk-Befund (März 2026)

```
GET /koop/app/trefferliste?4-1.0-&windowName=92e4a9e8-4ffb-48ba-852a-f28804702309&_=1773330874099
Host: www.interamt.de
Accept: application/xml, text/xml, */*; q=0.01
Wicket-Ajax: true
Wicket-Ajax-BaseURL: koop/app/trefferliste
Wicket-FocusedElementId: comp3
Cookie: JSESSIONID=...
```

Response: `text/xml` — Wicket-internes Component-Update-Protokoll, keine Job-Daten-Struktur.

### Warum httpx nicht ausreicht

- `windowName` ist eine Session-UUID, die beim ersten Seitenaufruf vergeben wird
- `4-1.0-` ist eine Wicket-interne Komponenten-ID (ändert sich pro Request)
- `JSESSIONID` muss durch Seitennavigation etabliert werden
- Jeder AJAX-Request baut auf dem vorherigen Zustand auf

---

## Geplante Implementierung (Typ B)

### Playwright-Workflow

```
1. Browser-Session öffnen
2. Startseite laden: https://www.interamt.de/koop/app/trefferliste
3. Suchparameter eingeben (Ort / Keyword optional)
4. Suchergebnisse abwarten (Wicket AJAX)
5. Jobs aus gerendertem DOM extrahieren
6. Pagination durchlaufen
7. Pro Job: URL, Titel, Behörde, Standort, Deadline extrahieren
```

### Zu implementierende Klasse

```python
# app/scraper/portals/interamt.py

class InteramtScraper(BaseScraper):
    source_name = "interamt"
    source_type = "portal"

    async def fetch_jobs(self) -> list[ScrapedJob]:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto("https://www.interamt.de/koop/app/trefferliste")
            # ... Wicket-Seite navigieren, DOM parsen
```

### Playwright-Voraussetzungen

Der Docker-Container enthält bereits Playwright + Chromium:
```dockerfile
RUN pip install playwright && playwright install chromium --with-deps
```

Kein zusätzlicher Infrastruktur-Aufwand nötig.

---

## Relevanz

interamt.de ist das wichtigste zentrale Portal für Bundesbehörden. Besonders relevant
für IT-Stellen in Bundesbehörden die nicht auf service.bund.de erscheinen (verschiedene
Portale haben unterschiedliche Abdeckung). Ergänzung zu service.bund.de, nicht Ersatz.
