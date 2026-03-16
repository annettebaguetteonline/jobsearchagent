# Job-Datenquellen: Technische Implementierungsreferenz

> **Zweck:** Dieses Dokument dient als Arbeitsgrundlage für Claude Code zur Integration von Jobdatenquellen in das bestehende Agentic-Job-Search-System (FastAPI + Docker Compose + Ollama). Jede Quelle ist mit konkreten Endpunkten, Authentifizierung, Datenfeldern, Stolpersteinen und Workarounds dokumentiert.

> **Bestehende Quellen (bereits integriert):** Bundesagentur für Arbeit API, Interamt, service.bund.de

> **Kernanforderung:** Vollständiger Anzeigentext + Filterung nach Veröffentlichungsdatum

---

## Architektur-Übersicht

### Empfohlene Integrations-Tiers

```
Tier 1 – Kostenlose APIs (sofort integrierbar)
├── Adzuna API (DE)           → breiter Aggregator, max_days_old-Filter
├── Arbeitnow API             → Volltext, kein Auth, Deutschland-Fokus
├── Jooble API                → großer Aggregator, 67+ Länder
├── Stellenmarkt.de RSS       → 15 Kategorie-Feeds, triviale Integration
└── Careerjet API             → Backup, Status prüfen

Tier 2 – Kostenpflichtig, bestes Preis-Leistungs-Verhältnis (~15–50 €/Monat)
├── JSearch (RapidAPI)        → Google-for-Jobs-Proxy, ~80-90% Volltext
└── Apify XING Scraper        → einziger skalierbarer XING-Zugang

Tier 3 – Eigenes Scraping (einmalige Entwicklung)
├── Jobbörse.de               → ~1,2 Mio. Stellen, SSR, sauberes HTML
└── Kimeta.de                 → ~2,5 Mio. Stellen, SSR, Meta-Aggregator
```

### Zweistufiges Volltext-Pattern

```python
# Für APIs die nur Snippets liefern (Jooble, Adzuna teilweise, Careerjet):
async def ensure_full_text(job: JobListing) -> JobListing:
    """Fetch full description if API only returned a snippet."""
    SNIPPET_THRESHOLD = 500  # Zeichen
    if len(job.description or "") < SNIPPET_THRESHOLD and job.source_url:
        full_html = await fetch_and_extract(job.source_url)
        if full_html and len(full_html) > len(job.description or ""):
            job.description = full_html
            job.description_source = "fetched"
    return job
```

**Stolperstein:** Beim Nachfetchen der Quell-URLs können Anti-Bot-Maßnahmen greifen (besonders bei Indeed/StepStone-Originalquellen). Workaround: User-Agent-Rotation, Rate-Limiting auf max 1 req/2s, ggf. Headless-Browser für JS-schwere Seiten.

---

## Tier 1: Kostenlose APIs

### 1. Adzuna API

| Eigenschaft | Wert |
|---|---|
| **Base-URL** | `https://api.adzuna.com/v1/api/jobs/de/search/{page}` |
| **Auth** | Query-Params: `app_id` + `app_key` (kostenlos registrieren auf developer.adzuna.com) |
| **Rate-Limit** | ~250 Requests/Tag, 25 Requests/Minute |
| **Datumsfilter** | `max_days_old=7` (native Unterstützung) |
| **Sortierung** | `sort_by=date` für chronologisch |
| **Volltext** | ⚠️ TEILWEISE – `description` Feld ist oft gekürzt (200-500 Zeichen) |
| **Paginierung** | Seitenbasiert, `page=1`, `results_per_page=50` (max) |

#### Request-Beispiel

```bash
curl "https://api.adzuna.com/v1/api/jobs/de/search/1?app_id=YOUR_ID&app_key=YOUR_KEY&results_per_page=50&max_days_old=7&sort_by=date&what=product+owner&where=wiesbaden"
```

#### Response-Felder (relevant)

```json
{
  "results": [
    {
      "id": "4567890123",
      "title": "Product Owner (m/w/d)",
      "description": "Wir suchen einen erfahrenen...",  // ⚠️ oft gekürzt
      "redirect_url": "https://www.adzuna.de/details/...",
      "company": { "display_name": "Firma GmbH" },
      "location": {
        "display_name": "Wiesbaden, Hessen",
        "area": ["Deutschland", "Hessen", "Wiesbaden"]
      },
      "created": "2025-12-01T12:00:00Z",
      "salary_min": 55000,
      "salary_max": 75000,
      "contract_type": "permanent",
      "category": { "label": "IT Jobs", "tag": "it-jobs" }
    }
  ],
  "count": 1234,
  "mean": 62000
}
```

#### Stolpersteine & Workarounds

1. **Gekürzte Beschreibungen:** Das `description`-Feld enthält häufig nur 200-500 Zeichen. Die `redirect_url` führt zur Adzuna-Detailseite, die wiederum zur Originalquelle weiterleitet.
   - **Workaround:** Zweistufig – erst `redirect_url` fetchen, dann den `rel=canonical` oder die finale URL nach Redirect fetchen, um den Volltext von der Originalquelle zu extrahieren.
   - **Achtung:** Adzuna-Redirect-URLs sind zeitlich begrenzt gültig (einige Tage).

2. **Gehaltsangaben unzuverlässig:** Adzuna schätzt Gehälter algorithmisch, wenn keine explizite Angabe vorhanden. Feld `salary_is_predicted` prüfen.

3. **Duplikate:** Dieselbe Stelle kann unter verschiedenen IDs auftauchen, wenn sie von mehreren Quellen aggregiert wurde. Deduplizierung über Titel + Firma + Standort empfohlen.

4. **Paginierungslimit:** Maximal 1000 Ergebnisse pro Suche (20 Seiten à 50). Bei breiten Suchen nach Region oder Kategorie aufteilen.

---

### 2. Arbeitnow API

| Eigenschaft | Wert |
|---|---|
| **Base-URL** | `https://www.arbeitnow.com/api/job-board-api` |
| **Auth** | Keine – komplett offen |
| **Rate-Limit** | Nicht dokumentiert, moderat halten (1 req/5s empfohlen) |
| **Datumsfilter** | Kein API-Parameter – clientseitig über `created_at` filtern |
| **Sortierung** | Standard nach Aktualität |
| **Volltext** | ✅ JA – `description` enthält vollständigen HTML-Text |
| **Paginierung** | `?page=1`, Response enthält `links.next` |

#### Request-Beispiel

```bash
curl "https://www.arbeitnow.com/api/job-board-api?page=1"
```

#### Response-Felder (relevant)

```json
{
  "data": [
    {
      "slug": "firma-gmbh-product-owner-123456",
      "company_name": "Firma GmbH",
      "title": "Product Owner",
      "description": "<p>Vollständiger HTML-Text der Stellenanzeige...</p>",
      "tags": ["product-management", "agile"],
      "job_types": ["Full-Time"],
      "location": "Berlin",
      "remote": true,
      "url": "https://www.arbeitnow.com/jobs/...",
      "created_at": 1701388800
    }
  ],
  "links": {
    "next": "https://www.arbeitnow.com/api/job-board-api?page=2"
  }
}
```

#### Stolpersteine & Workarounds

1. **Unix-Timestamp:** `created_at` ist ein Unix-Timestamp (Sekunden), kein ISO-String. Umrechnung beachten.

2. **Begrenztes Volumen:** Schwerpunkt auf Tech/Englisch in Deutschland, insgesamt nur niedrige Tausender-Anzahl. Als Ergänzung gut, nicht als Primärquelle.

3. **Kein Suchfilter:** Die API hat keine Keyword- oder Standortsuche. Man bekommt den gesamten Feed und muss clientseitig filtern. Bei kleinem Volumen akzeptabel.

4. **HTML-Beschreibungen:** Der Volltext ist HTML. Für die LLM-Evaluierung im Pipeline sollte das HTML zu Plaintext konvertiert werden (z.B. mit `beautifulsoup4` oder `html2text`).

---

### 3. Jooble API

| Eigenschaft | Wert |
|---|---|
| **Base-URL** | `https://jooble.org/api/{api_key}` |
| **Auth** | API-Key in URL (kostenlos nach Registrierung auf jooble.org/api/about) |
| **Methode** | POST mit JSON-Body |
| **Rate-Limit** | Nicht öffentlich dokumentiert, als großzügig beschrieben |
| **Datumsfilter** | ❌ KEIN nativer Parameter – clientseitig über `updated` filtern |
| **Volltext** | ❌ NEIN – nur `snippet` (Auszug, ~200-300 Zeichen) |
| **Paginierung** | `page` im JSON-Body (1-basiert) |

#### Request-Beispiel

```bash
curl -X POST "https://jooble.org/api/YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "keywords": "Product Owner",
    "location": "Wiesbaden",
    "radius": "25",
    "salary": "50000",
    "page": "1"
  }'
```

#### Response-Felder (relevant)

```json
{
  "totalCount": 567,
  "jobs": [
    {
      "title": "Product Owner (m/w/d)",
      "location": "Wiesbaden",
      "snippet": "Wir suchen einen erfahrenen Product Owner für unser agiles Team...",
      "salary": "55.000 € - 75.000 €",
      "source": "stepstone.de",
      "type": "Vollzeit",
      "link": "https://de.jooble.org/away/...",
      "company": "Firma GmbH",
      "updated": "2025-12-01T00:00:00.0000000",
      "id": 1234567890
    }
  ]
}
```

#### Stolpersteine & Workarounds

1. **Kein Volltext:** Das ist der größte Nachteil. `snippet` reicht nicht für LLM-Evaluierung.
   - **Workaround:** `link` fetchen → Jooble-Weiterleitungsseite → finale Quell-URL extrahieren → Volltext von Originalquelle scrapen.
   - **Achtung:** Die `link`-URL ist ein Jooble-Redirect. Man muss dem Redirect folgen, um die tatsächliche Stellenanzeigen-URL zu bekommen.

2. **`updated` vs. Veröffentlichungsdatum:** Das Feld `updated` ist das letzte Aktualisierungsdatum, nicht unbedingt das Erstveröffentlichungsdatum. Stellen können mit aktuellem Datum erscheinen, obwohl sie schon Wochen alt sind.

3. **Duplikate über Quellen:** Jooble aggregiert – die `source`-Info (z.B. "stepstone.de") hilft bei der Quellerkennung, aber Duplikate zwischen Jooble und eigenen StepStone-Daten sind wahrscheinlich.

4. **API-Key-Vergabe:** Die Registrierung erfordert eine Website-URL. Für ein privates Projekt eine einfache Landing-Page oder GitHub-Repo-URL angeben.

---

### 4. Stellenmarkt.de RSS-Feeds

| Eigenschaft | Wert |
|---|---|
| **Base-URL** | `https://www.stellenmarkt.de/rss/smrssbf{N}.xml` |
| **Auth** | Keine |
| **Format** | Standard RSS 2.0 XML |
| **Datumsfilter** | `pubDate` im Feed, clientseitig filtern |
| **Volltext** | ⚠️ TEILWEISE – `description` ist ausführlich aber ggf. nicht komplett |
| **Aktualisierung** | Täglich |

#### Verfügbare Feed-URLs

```
IT/Telekommunikation:  https://www.stellenmarkt.de/rss/smrssbf6.xml
Ingenieurwesen:        https://www.stellenmarkt.de/rss/smrssbf5.xml
Vertrieb:              https://www.stellenmarkt.de/rss/smrssbf12.xml
Marketing/PR:          https://www.stellenmarkt.de/rss/smrssbf8.xml
Medizin/Pharma:        https://www.stellenmarkt.de/rss/smrssbf9.xml
Personal/HR:           https://www.stellenmarkt.de/rss/smrssbf10.xml
Recht:                 https://www.stellenmarkt.de/rss/smrssbf11.xml
Finanzen:              https://www.stellenmarkt.de/rss/smrssbf3.xml
Einkauf/Logistik:      https://www.stellenmarkt.de/rss/smrssbf2.xml
Verwaltung:            https://www.stellenmarkt.de/rss/smrssbf14.xml
Produktion:            https://www.stellenmarkt.de/rss/smrssbf4.xml
Consulting:            https://www.stellenmarkt.de/rss/smrssbf1.xml
Sonstige:              https://www.stellenmarkt.de/rss/smrssbf13.xml
Design:                https://www.stellenmarkt.de/rss/smrssbf15.xml
Bildung:               https://www.stellenmarkt.de/rss/smrssbf7.xml
```

#### RSS-Item-Struktur

```xml
<item>
  <title>Product Owner (m/w/d) - Firma GmbH</title>
  <link>https://www.stellenmarkt.de/jobs/product-owner-12345</link>
  <description>Ausführliche Beschreibung der Stelle...</description>
  <pubDate>Mon, 01 Dec 2025 08:00:00 +0100</pubDate>
  <guid>https://www.stellenmarkt.de/jobs/product-owner-12345</guid>
</item>
```

#### Implementierung (Python)

```python
import feedparser
from datetime import datetime, timedelta

FEEDS = {
    "it": "https://www.stellenmarkt.de/rss/smrssbf6.xml",
    "vertrieb": "https://www.stellenmarkt.de/rss/smrssbf12.xml",
    # ... alle weiteren Feeds
}

async def fetch_stellenmarkt_jobs(max_age_days: int = 7) -> list[dict]:
    jobs = []
    cutoff = datetime.now() - timedelta(days=max_age_days)

    for category, url in FEEDS.items():
        feed = feedparser.parse(url)
        for entry in feed.entries:
            pub_date = datetime(*entry.published_parsed[:6])
            if pub_date >= cutoff:
                jobs.append({
                    "title": entry.title,
                    "url": entry.link,
                    "description": entry.description,  # ggf. Detailseite nachfetchen
                    "published": pub_date.isoformat(),
                    "category": category,
                    "source": "stellenmarkt.de"
                })
    return jobs
```

#### Stolpersteine & Workarounds

1. **RSS-Beschreibung nicht immer vollständig:** Für den kompletten Anzeigentext die `link`-URL fetchen. Die Detailseiten sind serverseitig gerendert und gut parsebar.

2. **Feed-Größe variiert:** Manche Feeds haben nur 20-50 Items, andere deutlich mehr. Tägliches Polling empfohlen.

3. **Encoding:** UTF-8, aber gelegentlich HTML-Entities in `description`. Mit `html.unescape()` nachbearbeiten.

4. **Keine Keyword-Suche:** Man bekommt alle Stellen der Kategorie. Clientseitige Filterung nötig.

---

### 5. Careerjet API

| Eigenschaft | Wert |
|---|---|
| **Base-URL** | `http://public.api.careerjet.net/search` |
| **Auth** | Affiliate-ID (kostenlos auf careerjet.com/partners/api) |
| **Rate-Limit** | Nicht dokumentiert |
| **Datumsfilter** | Kein nativer Parameter |
| **Volltext** | ❌ NEIN – nur Snippet |
| **Status** | ⚠️ UNSICHER – API-Aktivität 2025/26 unklar |

#### Stolpersteine

1. **Veraltete Bibliotheken:** Die offiziellen Python/PHP-Bibliotheken sind seit Jahren nicht aktualisiert. Empfehlung: Direkt HTTP-Requests senden.
2. **Priorität niedrig:** Nur als Backup einplanen, zuerst Adzuna/Jooble/Arbeitnow testen. Falls die API nicht antwortet, streichen.

---

## Tier 2: Kostenpflichtige APIs

### 6. JSearch (RapidAPI) – Top-Empfehlung

| Eigenschaft | Wert |
|---|---|
| **Base-URL** | `https://jsearch.p.rapidapi.com/search` |
| **Auth** | RapidAPI-Key im Header `X-RapidAPI-Key` |
| **Free-Tier** | 500 Requests/Monat |
| **Paid** | Ab ~10-20 $/Monat für 10.000+ Requests |
| **Datumsfilter** | `date_posted=today|3days|week|month` ✅ |
| **Volltext** | ✅ JA (~80-90% der Stellen) – `job_description` Feld |
| **Paginierung** | `page=1`, `num_pages=1-20` |

#### Request-Beispiel

```bash
curl "https://jsearch.p.rapidapi.com/search?query=Product+Owner+Wiesbaden+Deutschland&page=1&num_pages=1&date_posted=week&country=de" \
  -H "X-RapidAPI-Key: YOUR_KEY" \
  -H "X-RapidAPI-Host: jsearch.p.rapidapi.com"
```

#### Response-Felder (relevant)

```json
{
  "status": "OK",
  "data": [
    {
      "job_id": "abc123",
      "employer_name": "Firma GmbH",
      "employer_logo": "https://...",
      "employer_website": "https://firma.de",
      "job_title": "Product Owner (m/w/d)",
      "job_description": "Vollständiger Stellentext...",  // ✅ meist Volltext
      "job_apply_link": "https://firma.de/careers/...",
      "job_city": "Wiesbaden",
      "job_state": "Hessen",
      "job_country": "DE",
      "job_posted_at_datetime_utc": "2025-12-01T00:00:00.000Z",
      "job_min_salary": 55000,
      "job_max_salary": 75000,
      "job_salary_currency": "EUR",
      "job_required_experience": { "experience_mentioned": true },
      "job_required_skills": ["Scrum", "JIRA", "Product Management"],
      "job_benefits": ["Homeoffice", "Firmenwagen"],
      "job_is_remote": false,
      "job_employment_type": "FULLTIME",
      "job_publisher": "StepStone"  // ← zeigt die Originalquelle!
    }
  ]
}
```

#### Warum JSearch die wichtigste einzelne Ergänzung ist

JSearch nutzt Google for Jobs als Datenquelle. Google for Jobs indexiert alle Portale, die schema.org/JobPosting-Markup verwenden – das sind in Deutschland: StepStone, Indeed, LinkedIn, XING, Jobware, HeyJobs, Stellenanzeigen.de und praktisch alle größeren Portale. **Mit JSearch bekommt man also indirekt Zugang zu den Portalen, die man direkt nicht scrapen kann.**

#### Stolpersteine & Workarounds

1. **~10-20% ohne Volltext:** Wenn `job_description` kurz ist (<500 Zeichen), den `job_apply_link` fetchen.
   - **Achtung:** Apply-Links führen oft auf ATS-Systeme (Greenhouse, Workday, SAP SuccessFactors) die JS-gerendert sind.
   - **Workaround:** Für diese Fälle einen Headless-Browser-Fallback implementieren (Playwright/Selenium).

2. **Rate-Limits strikt:** RapidAPI blockt sofort bei Überschreitung. Exponential Backoff implementieren.

3. **`job_publisher` nutzen:** Das Feld zeigt die Originalquelle (z.B. "StepStone", "Indeed", "LinkedIn"). Für Deduplizierung mit anderen eigenen Quellen essenziell.

4. **Google-for-Jobs-Latenz:** Neue Stellen erscheinen bei Google for Jobs mit 12-48h Verzögerung. Für tagesaktuelle Stellen die BA-API und Arbeitnow als Ergänzung nutzen.

5. **Suchsyntax:** `query` akzeptiert natürliche Sprache. Für den deutschen Markt `Deutschland` oder den Ortsnamen im Query angeben UND `country=de` setzen.

6. **Alternative zu RapidAPI:** Auch auf Zyla API Hub verfügbar (~0,0032 $/Request), falls RapidAPI-Pricing ungünstiger ist.

---

### 7. Apify – XING-Scraper

| Eigenschaft | Wert |
|---|---|
| **Plattform** | apify.com |
| **XING Actor** | `apify/xing-jobs-scraper` (oder Community-Actors suchen) |
| **Kosten** | Starter: 39 $/Monat (inkl. Compute-Credits) |
| **Volltext** | ✅ JA – Scraper rendert Detailseiten |
| **Datumsfilter** | ✅ Im Scraper konfigurierbar |

#### Integration via Apify API

```python
import httpx

APIFY_TOKEN = "apify_api_YOUR_TOKEN"
ACTOR_ID = "apify~xing-jobs-scraper"  # exakten Actor-Namen prüfen

async def run_xing_scraper(keywords: str, location: str) -> list[dict]:
    # Actor starten
    run_url = f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs"
    resp = await httpx.post(
        run_url,
        headers={"Authorization": f"Bearer {APIFY_TOKEN}"},
        json={
            "searchQuery": keywords,
            "location": location,
            "maxResults": 100
        }
    )
    run_id = resp.json()["data"]["id"]

    # Auf Fertigstellung warten (polling oder webhook)
    # ...

    # Ergebnisse abrufen
    dataset_url = f"https://api.apify.com/v2/actor-runs/{run_id}/dataset/items"
    results = await httpx.get(
        dataset_url,
        headers={"Authorization": f"Bearer {APIFY_TOKEN}"}
    )
    return results.json()
```

#### Stolpersteine & Workarounds

1. **Asynchrones Modell:** Apify-Actors laufen asynchron. Man startet einen Run und pollt auf Fertigstellung oder nutzt Webhooks. Für das Jobsuche-System einen Webhook-Endpunkt implementieren oder einen Polling-Worker.

2. **Actor-Verfügbarkeit:** Community-Actors können jederzeit vom Autor entfernt werden. Auf den offiziellen Apify-Actor setzen oder einen eigenen Actor auf Basis des Apify SDK forken.

3. **XING-Schutzmaßnahmen:** Moderat, aber nicht null. Apify kümmert sich um Proxy-Rotation. Bei häufiger Nutzung dennoch die Account-Limits im Auge behalten.

4. **Auch für LinkedIn/Indeed nutzbar:** Apify hat Scraper für beide, allerdings ist LinkedIn aggressiver geschützt → höherer Creditverbrauch.

---

## Tier 3: Eigenes Scraping

### 8. Jobbörse.de

| Eigenschaft | Wert |
|---|---|
| **Base-URL** | `https://www.jobbörse.de` (oder `https://www.xn--jobbrse-d1a.de`) |
| **Rendering** | SSR (Server-Side Rendered) – kein JS nötig |
| **Anti-Bot** | Minimal – kein Cloudflare, kein DataDome |
| **Volltext** | ✅ JA – Detailseiten enthalten vollen Text |
| **Stellenanzahl** | ~1,2 Mio. aktive Anzeigen |
| **Datumsfilter** | URL-Parameter für "Heute veröffentlicht" etc. |

#### URL-Struktur (Beispiel)

```
Suche:  https://www.xn--jobbrse-d1a.de/stellenangebote/?was=Product+Owner&wo=Wiesbaden&zeitraum=7
Detail: https://www.xn--jobbrse-d1a.de/stellenangebote/product-owner-bei-firma-gmbh-12345.html
```

#### Scraping-Ansatz

```python
import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.xn--jobbrse-d1a.de"

async def scrape_jobboerse(keyword: str, location: str, max_age_days: int = 7) -> list[dict]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "de-DE,de;q=0.9"
    }

    search_url = f"{BASE_URL}/stellenangebote/"
    params = {"was": keyword, "wo": location, "zeitraum": str(max_age_days)}

    resp = await httpx.get(search_url, params=params, headers=headers)
    soup = BeautifulSoup(resp.text, "html.parser")

    jobs = []
    for listing in soup.select("div.job-listing"):  # ← Selektor anpassen!
        detail_url = BASE_URL + listing.select_one("a")["href"]
        # Detail-Seite für Volltext fetchen
        detail_resp = await httpx.get(detail_url, headers=headers)
        detail_soup = BeautifulSoup(detail_resp.text, "html.parser")

        jobs.append({
            "title": listing.select_one(".job-title").text.strip(),
            "company": listing.select_one(".company").text.strip(),
            "location": listing.select_one(".location").text.strip(),
            "description": detail_soup.select_one(".job-description").get_text(),
            "url": detail_url,
            "source": "jobboerse.de"
        })

        await asyncio.sleep(2)  # Rate-Limiting!

    return jobs
```

#### Stolpersteine & Workarounds

1. **Punycode-Domain:** `jobbörse.de` → `xn--jobbrse-d1a.de`. Manche HTTP-Libraries haben Probleme mit IDN-Domains. Immer die Punycode-Form verwenden.

2. **CSS-Selektoren ändern sich:** Die HTML-Struktur kann sich ohne Vorwarnung ändern. Resilientes Parsing mit Fallbacks implementieren. Empfehlung: Selektoren in einer separaten Config-Datei halten, nicht hard-coded.

3. **Rate-Limiting zwingend:** Ohne Pause zwischen Requests → IP-Sperre. Mindestens 2 Sekunden zwischen Requests, besser 3-5 bei Detailseiten.

4. **Paginierung:** Die Suchergebnis-Seiten haben Paginierung via URL-Parameter. Maximal verfügbare Seiten prüfen (meist 20-50 Seiten).

5. **Duplikate mit BA-API:** Jobbörse.de aggregiert auch aus der Bundesagentur → Deduplizierung gegen bestehende BA-Daten nötig.

---

### 9. Kimeta.de

| Eigenschaft | Wert |
|---|---|
| **Base-URL** | `https://www.kimeta.de` |
| **Rendering** | SSR |
| **Anti-Bot** | Leicht (selbst ein Aggregator/Crawler) |
| **Volltext** | ⚠️ BEDINGT – Kimeta zeigt oft nur Auszüge + Link zur Originalquelle |
| **Stellenanzahl** | ~2,5 Mio. |
| **Datumsfilter** | URL-Parameter vorhanden |

#### URL-Struktur

```
Suche:  https://www.kimeta.de/jobs-mit-product-owner-in-wiesbaden
Detail: https://www.kimeta.de/job/12345  → Redirect zur Originalquelle
```

#### Stolpersteine & Workarounds

1. **Kimeta ist selbst ein Aggregator:** Die Detailseiten enthalten oft nur einen Auszug und einen Link zur Originalquelle (z.B. StepStone, Karriereseite des Arbeitgebers). Für den Volltext muss man der Weiterleitung folgen.
   - **Problem:** Die Originalquelle kann eine geschützte Seite sein (StepStone, Indeed).
   - **Workaround:** Kimeta primär für Discovery nutzen (welche Stellen gibt es?), Volltext dann über JSearch oder die BA-API abgleichen.

2. **URL-Routing:** Die URL-Struktur `jobs-mit-{keyword}-in-{ort}` ist SEO-freundlich aber erfordert URL-Encoding und Bindestrich-Normalisierung.

3. **50+ White-Label-Portale:** Kimeta betreibt Portale unter Dutzenden Domains (jobanzeigen.de, etc.). Beim Scraping von mehreren dieser Portale sind die Daten identisch → nicht doppelt scrapen.

---

## Quellen die NICHT integriert werden können/sollten

### Indeed

- **Publisher API:** Offiziell deprecated, keine neuen Keys, Endpunkt liefert keine Ergebnisse mehr.
- **XML-Feeds:** Werden am 31.03.2026 für organische Stellen abgestellt, bis Ende 2026 komplett.
- **Scraping:** Cloudflare WAF, JS-Challenges, aggressive IP-Sperren. Technisch möglich mit Headless-Browser + Residential Proxies, aber juristisch riskant und wartungsintensiv.
- **Empfehlung:** Indeed-Stellen über JSearch (Google for Jobs) abgreifen – dort sind die meisten Indeed-Stellen indexiert.

### StepStone

- **Keine öffentliche API.**
- **Scraping:** Mittelschwerer Bot-Schutz (kein Cloudflare, aber JS-Rendering nötig + Rate-Limiting).
- **Empfehlung:** Wie Indeed → JSearch als Proxy nutzen.

### LinkedIn

- **Keine öffentliche Job-Such-API.** Job Posting API nur für ATS-Partner (kein Zugang möglich).
- **Scraping:** Aggressivster Schutz im Markt. Juristisch aktiv gegen Scraper (Proxycurl-Urteil 2025).
- **Empfehlung:** JSearch enthält teilweise LinkedIn-Stellen via Google for Jobs.

### XING/onlyfy

- **API eingefroren:** Keine neuen App-Registrierungen möglich.
- **Scraping:** Moderater Schutz – über Apify (Tier 2) realisierbar.

---

## Deduplizierungs-Strategie

Da mehrere Quellen dieselben Stellen aggregieren, ist Deduplizierung kritisch:

```python
import hashlib
from difflib import SequenceMatcher

def generate_job_fingerprint(job: dict) -> str:
    """Erzeuge einen Fingerprint für Deduplizierung."""
    # Normalisierung
    title = job.get("title", "").lower().strip()
    company = job.get("company", "").lower().strip()
    # Nur die ersten 3 Wörter des Standorts (Stadt-Level)
    location = " ".join(job.get("location", "").lower().split()[:3])

    raw = f"{title}|{company}|{location}"
    return hashlib.md5(raw.encode()).hexdigest()

def is_duplicate(job_a: dict, job_b: dict, threshold: float = 0.85) -> bool:
    """Fuzzy-Duplikat-Erkennung für unterschiedliche Schreibweisen."""
    title_sim = SequenceMatcher(None,
        job_a.get("title", "").lower(),
        job_b.get("title", "").lower()
    ).ratio()

    company_sim = SequenceMatcher(None,
        job_a.get("company", "").lower(),
        job_b.get("company", "").lower()
    ).ratio()

    return (title_sim * 0.6 + company_sim * 0.4) >= threshold
```

### Typische Duplikat-Quellen

| Quelle A | Quelle B | Wahrscheinlichkeit |
|---|---|---|
| BA-API | Jobbörse.de | Hoch (Jobbörse.de aggregiert BA) |
| JSearch | Jooble | Hoch (beide aggregieren dieselben Portale) |
| JSearch | Adzuna | Mittel |
| Kimeta | Jobbörse.de | Mittel-Hoch (überlappende Quellen) |
| Arbeitnow | JSearch | Niedrig (Arbeitnow hat eigene ATS-Quellen) |

---

## Implementierungs-Reihenfolge (Empfehlung)

### Phase 1: Quick Wins (1-2 Tage)
1. **Stellenmarkt.de RSS** – triviale Integration, `feedparser` + cron
2. **Arbeitnow API** – kein Auth, Volltext, 30 Min Implementierung

### Phase 2: Kernquellen (2-3 Tage)
3. **Adzuna API** – Registrierung + Integration, `max_days_old`-Filter
4. **Jooble API** – Registrierung + Integration, Volltext-Nachfetchen implementieren

### Phase 3: Game-Changer (1-2 Tage)
5. **JSearch (RapidAPI)** – Free Tier zum Testen, dann Paid für Vollbetrieb

### Phase 4: Scraping (3-5 Tage)
6. **Jobbörse.de Scraper** – SSR, relativ einfach
7. **Kimeta.de Scraper** – nur für Discovery, Volltext über JSearch

### Phase 5: Optional (nach Bedarf)
8. **Apify für XING** – nur wenn XING-Stellen signifikant zum Ergebnis beitragen
9. **Careerjet** – nur falls andere Quellen Lücken haben

---

## Abstrakte Quell-Schnittstelle (für Claude Code)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum

class SourceType(Enum):
    API = "api"
    RSS = "rss"
    SCRAPER = "scraper"

class FullTextStatus(Enum):
    FULL = "full"           # Volltext direkt geliefert
    SNIPPET = "snippet"     # Nur Auszug, Nachfetchen nötig
    FETCHED = "fetched"     # Volltext nachträglich geholt

@dataclass
class JobListing:
    title: str
    company: str
    location: str
    description: str
    url: str
    source: str
    source_type: SourceType
    published_at: datetime
    fulltext_status: FullTextStatus

    # Optional
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: str = "EUR"
    employment_type: Optional[str] = None  # Vollzeit, Teilzeit, etc.
    remote: Optional[bool] = None
    tags: list[str] = field(default_factory=list)
    raw_data: Optional[dict] = None  # Original-Response für Debugging
    fingerprint: Optional[str] = None  # Für Deduplizierung

class JobSource(ABC):
    """Abstrakte Basis für alle Jobquellen."""

    @abstractmethod
    async def fetch_jobs(
        self,
        keywords: Optional[str] = None,
        location: Optional[str] = None,
        max_age_days: int = 7,
        max_results: int = 100
    ) -> list[JobListing]:
        pass

    @abstractmethod
    def source_name(self) -> str:
        pass

    @abstractmethod
    def source_type(self) -> SourceType:
        pass

    @abstractmethod
    def supports_fulltext(self) -> bool:
        """True wenn die Quelle zuverlässig Volltext liefert."""
        pass

    @abstractmethod
    def supports_date_filter(self) -> bool:
        """True wenn die Quelle nativ nach Datum filtern kann."""
        pass
```

---

## Checkliste für Claude Code

- [ ] `JobListing` Dataclass und `JobSource` ABC erstellen
- [ ] Stellenmarkt.de RSS-Integration (feedparser)
- [ ] Arbeitnow API-Integration (httpx, kein Auth)
- [ ] Adzuna API-Integration (httpx, API-Key aus .env)
- [ ] Jooble API-Integration (httpx, API-Key aus .env)
- [ ] JSearch API-Integration (httpx, RapidAPI-Key aus .env)
- [ ] Volltext-Nachfetch-Modul für Snippet-Quellen
- [ ] Deduplizierungs-Modul (Fingerprint + Fuzzy-Matching)
- [ ] Jobbörse.de Scraper (httpx + BeautifulSoup, Rate-Limited)
- [ ] Source-Orchestrator: Alle Quellen parallel abfragen, Ergebnisse mergen + deduplizieren
- [ ] .env-Template mit allen API-Keys
- [ ] Integration in bestehende FastAPI-Pipeline
- [ ] Tests: Mindestens Smoke-Tests pro Quelle (API erreichbar? Daten parsebar?)
