# Job Search Agent – Systemdesign

**Version:** 0.5
**Stand:** März 2026
**Status:** In Ausarbeitung

---

## Inhaltsverzeichnis

1. [Systemübersicht](#1-systemübersicht)
2. [Scraping-Komponente](#2-scraping-komponente)
3. [Evaluierungs-Pipeline](#3-evaluierungs-pipeline)
4. [Standort & ÖPNV](#4-standort--öpnv)
5. [Datenbank](#5-datenbank)
6. [Anschreiben-Generator](#6-anschreiben-generator)
7. [Dashboard](#7-dashboard)
8. [Infrastruktur & Docker](#8-infrastruktur--docker)
9. [Modelle & LLM-Integration](#9-modelle--llm-integration)
10. [Offene Punkte](#10-offene-punkte)
11. [Implementierungsreihenfolge](#11-implementierungsreihenfolge)

---

## 1. Systemübersicht

### Ziel

Automatisiertes System zur Jobsuche das:
- Stellenanzeigen aus mehreren Quellen täglich scrapt
- Diese anhand eines persönlichen Profils bewertet und filtert
- Eine strukturierte Übersicht offener Stellen führt
- Anschreiben auf Basis von Beispielen generiert

### Gesamtarchitektur

```
┌─────────────────────────────────────────────────────────────────┐
│                        Cron-Job (Host)                          │
│                    täglich 07:00, Mo–Fr                         │
│              curl -X POST /api/scrape/start                     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                      FastAPI Backend                            │
│                                                                 │
│  ┌─────────────┐  ┌──────────────────┐  ┌───────────────────┐  │
│  │  Scraper    │  │   Evaluierungs-  │  │   Anschreiben-    │  │
│  │  Pipeline   │  │   Pipeline       │  │   Generator       │  │
│  └──────┬──────┘  └────────┬─────────┘  └─────────┬─────────┘  │
│         │                  │                       │            │
│         └──────────────────┼───────────────────────┘            │
│                            │                                    │
│  ┌─────────────────────────▼──────────────────────────────────┐ │
│  │                   Datenschicht                             │ │
│  │   SQLite (jobs.db)          ChromaDB (RAG-Vektoren)       │ │
│  └────────────────────────────────────────────────────────────┘ │
└──────────────────────────┬──────────────────────────────────────┘
                           │ REST API
┌──────────────────────────▼──────────────────────────────────────┐
│                    React Frontend                               │
│            (Übersicht · Stellen · Klärungsbedarf · Steuerung)  │
└─────────────────────────────────────────────────────────────────┘

Externe Services (außerhalb Docker):
  Ollama (nativ, GPU)    → Lokale LLMs (mistral-nemo:12b, nomic-embed-text)
  DB REST API            → ÖPNV-Reisezeiten
  Anthropic API          → Claude Haiku/Sonnet für Tiefanalyse & Anschreiben
```

### Technologie-Stack

| Schicht | Technologie | Begründung |
|---|---|---|
| Backend | FastAPI + Python | Alle bisherigen Komponenten in Python, async-fähig |
| Frontend | React + TypeScript + Vite | Flexibel, marktrelevant, lerngeeignet für Partnerin |
| UI-Komponenten | shadcn/ui + Tailwind CSS | Modern, anpassbar, kein Styling-Lock-in |
| Charts | Recharts + D3.js | Recharts für Standard, D3 für Skill-Netzwerk |
| API-State | TanStack Query | Datenfetching, Caching, optimistische Updates |
| Relationale DB | SQLite | Lokal, portabel, ausreichend für Abfragevolumen |
| Vektordatenbank | ChromaDB (embedded) | Kein separater Service nötig |
| Lokale LLMs | Ollama (nativ) | Bessere GPU-Performance als Docker |
| Websuche | duckduckgo-search (Python) | Kein Container, kein API-Key, ausreichend für Firmenwebsite-Suche |
| LaTeX | TeX Live (im Backend-Container) | CV bereits in LaTeX; kein separater Service nötig |
| Cloud-LLM | Anthropic API (Haiku/Sonnet) | Tiefanalyse & Anschreiben-Generierung |

---

## 2. Scraping-Komponente

### Scraper-Typen

Statt eines Scrapers pro Website: **drei generische Typen** die per Konfiguration spezialisiert werden.

| Typ | Beschreibung | Beispiele |
|---|---|---|
| **A – Strukturiert** | Stabile API oder RSS-Feed | service.bund.de, Bundesagentur, Arbeitnow |
| **B – Konfigurierbar** | Bekanntes aber variables Layout, JS-SPA | karriere.hessen.de, XING, academics.de |
| **C – Generisch** | Beliebige Websites, vollständig LLM-basiert | Behörden-Websites, Firmen-Karriereseiten |

### Implementierungsstand

```
Quelle                    Typ   Status         Volltext              Technologie
──────────────────────────────────────────────────────────────────────────────────────────
service.bund.de           A     ✅ Live        ✅ RSS description    RSS (bundesweit)
Bundesagentur f. Arbeit   A     ✅ Live        ✅ Detail-API         REST JSON API
Arbeitnow                 A     ✅ Live        ✅ API description    REST JSON API
Jooble                    A     ✅ Live        ⚠️ Snippet           REST JSON API
Adzuna                    A     ✅ Live        ⚠️ Snippet           REST JSON API
Kimeta                    A     ✅ Live        ⚠️ Nur iframe-URLs   Next.js SSR + HTML-Filter (ADR-006)
Jobbörse.de               A     ✅ Live        ✅ Detail-Seite       httpx + BeautifulSoup
Stellenmarkt.de           A     ✅ Live        ⚠️ Snippet           RSS-Feed
interamt.de               B     ✅ Live        ✅ Detail-Seite       Playwright (Listing) + httpx (Detail)
──────────────────────────────────────────────────────────────────────────────────────────
karriere.hessen.de        B     📋 Geplant     —                    Playwright (JS-SPA)
karriere.rlp.de           B     📋 Geplant     —                    Playwright
Indeed                    A     📋 Geplant     —                    RSS-Feed
XING                      B     📋 Geplant     —                    Playwright
academics.de              B     📋 Geplant     —                    Playwright
──────────────────────────────────────────────────────────────────────────────────────────
Individuelle Behörden     C     📋 Geplant     —                    LLM-Extraktion
Firmen-Karriereseiten     C     📋 Geplant     —                    LLM-Extraktion
```

> **interamt.de — Typ B (Playwright):** Verwendet Apache Wicket AJAX-Framework (Session-gebunden,
> `JSESSIONID` + `windowName`). Playwright-Scraper implementiert und live. Volltext (`raw_text`)
> wird nicht befüllt. Siehe ADR-004.

> **service.bund.de — kein Ortsfilter:** Der RSS-Feed hat keine wirksamen Bundesland-Parameter.
> Es werden alle bundesweiten Stellen gescrapt, Relevanzfilterung übernimmt die
> Evaluierungs-Pipeline. Siehe ADR-003.

> **Kimeta — Multi-Stage-Suche:** Überwindet das 15-Seiten-Limit durch HTML-basierte
> Filter-Extraktion (`<a class="pos">`) und Sub-Suchen pro pf-Wert. Volltext nur für
> Kimeta-gehostete iframe-URLs verfügbar. Siehe [ADR-006](../docs/adr/006-kimeta-multistage-search.md).

> **Hinweis LinkedIn:** Technisch kaum zuverlässig scrapeBar.
> Empfehlung: `linkedin-api` (inoffizielle mobile App-API) oder
> manueller Import von Job-URLs.

### Scheduling

```json
{
  "scan_profiles": {
    "daily": {
      "run_at": "07:00",
      "timezone": "Europe/Berlin",
      "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri"],
      "sources": ["service_bund", "arbeitsagentur", "interamt", "arbeitnow",
                  "stellenmarkt", "adzuna", "jooble", "jobboerse", "kimeta"]
    },
    "weekly": {
      "run_at": "07:00",
      "run_on": "monday",
      "sources": ["custom_behoerden", "custom_firmen"]
    }
  }
}
```

Trigger: Cron-Job auf dem Host ruft `POST /api/scrape/start` auf.
Das Backend muss dafür nicht dauerhaft laufen.

### Vollständiger Scraping-Flow

```
1. FETCH           Quellen abrufen mit Query-Filtern
        │
2. POST-FILTER     Harte Ausschlüsse: Frist, Ort, Keywords
        │
3. DEDUPLIZIERUNG  Canonical-ID + Fuzzy-Match + LLM (Grenzfälle)
        │
4. FIRMENWEBSITE   Aggregator-URL → kanonische Direkt-URL
        │
5. ÄNDERUNGSERKENNUNG  Hash-Vergleich → LLM-Diff bei Änderung
        │
        ▼
   Evaluierungs-Pipeline
```

### Query-Filter

```json
{
  "query_filters": {
    "keywords": ["Software Engineer", "Backend Developer", "Python Entwickler"],
    "locations": ["Hessen", "Rheinland-Pfalz", "Frankfurt", "Wiesbaden", "Remote"],
    "radius_km": 50,
    "posted_within_days": 2,
    "exclude_keywords": ["Junior", "Praktikum", "Werkstudent", "Ausbildung", "Azubi"]
  }
}
```

> `posted_within_days: 90` für den ersten Lauf, danach `2` für tägliche Deltas.

### Deduplizierung

Eine Stelle die auf StepStone, service.bund.de und der Firmenwebsite erscheint
ist **ein Job mit drei Quellen** – nicht drei Jobs.

Implementiert in `BaseScraper._process_job()`:

```
Stufe 0 – Source-Job-ID-Match (schnellster Pfad):
  Suche in job_sources(source_name, source_job_id)
  Greift wenn Quelle eigene stabile IDs liefert (z.B. StepStone, service.bund.de)

Stufe 1 – Hash-Match (kostenlos):
  canonical_id = SHA256(norm_title | norm_company | norm_ort_ohne_plz)
  PLZ-Prefix wird vor dem Hashing entfernt: "34117 Kassel" → "kassel"
  → quell-übergreifende Duplikate zwischen service.bund.de und StepStone

Stufe 2 – Fuzzy-Match (kostenlos):
  Titel-Ähnlichkeit ≥ 85% (difflib) + gleiche Firma → wahrscheinlich Duplikat

Stufe 3 – LLM (reserviert für spätere Erweiterung):
  Semantisch ähnliche Titel bei gleicher Firma/Ort → LLM entscheidet
  Noch nicht implementiert.
```

Jeder `job_sources`-Eintrag speichert eine `source_job_id` für Stufe 0.
Duplikate aktualisieren immer `last_seen_at` und upserten die Quell-URL.

Siehe ADR-001 (Dreistufige Deduplizierung), ADR-002 (PLZ-Normalisierung).

### Firmenwebsite-Suche (gestaffelt)

```
Stufe 1  Kostenlos   companies-DB Lookup (fuzzy match)
Stufe 2  Kostenlos   duckduckgo-search Python-Library + URL-Plausibilitätsprüfung
Stufe 3  Günstig     Lokales Modell bewertet Kandidaten-URLs
Stufe 4  Kostenpflichtig  Claude Haiku mit Web-Search (nur on demand)
─────────────────────────────────────────────────────
Kein Treffer → 🔴 Klärungsbedarf (Dashboard-Drilldown)
```

DuckDuckGo wird als Python-Library (`duckduckgo-search`) direkt
im Backend-Prozess genutzt – kein separater Service nötig.

**ATS-Systeme** (Lever, Greenhouse, Personio, Softgarden) werden
als kanonische URLs akzeptiert – sie führen direkt zur Bewerbung.

### Änderungserkennung

```sql
ALTER TABLE jobs ADD COLUMN content_hash TEXT;
ALTER TABLE jobs ADD COLUMN change_history TEXT; -- JSON-Array
```

Bei jedem Scan: Hash-Vergleich → bei Änderung LLM-Diff der
relevanten Felder (Frist, Gehalt, Anforderungen, Arbeitsmodell).

### Anti-Detection

- Zufällige Delays zwischen Requests (2–8s, nicht gleichmäßig)
- Reale User-Agents rotieren
- Max. 1 Request/5s pro Domain
- Robots.txt respektieren
- Scans nur zu normalen Tageszeiten

---

## 3. Evaluierungs-Pipeline

### Hybrid-Ansatz (Stufe 1a/1b + Stufe 2)

```
Neue Stelle
     │
     ▼
┌─────────────────────────────────────────────────┐
│  Stufe 1a – Deterministische Ausschlüsse        │
│  Keyword-basiert, kein LLM                      │
│  exclude_keywords aus config.yaml               │
│  z.B. "Chefarzt", "Professur", "Kfz-Mechanik"  │
│  → Sofort SKIP bei Treffer (schnell, kostenlos) │
└──────────────────────┬──────────────────────────┘
                       │ kein Ausschluss-Treffer
                       ▼
┌─────────────────────────────────────────────────┐
│  Stufe 1b – LLM-Vorfilter (lokal, Ollama)      │
│  Standard: mistral-nemo:12b                     │
│  Binäre Entscheidung: PASS / SKIP              │
│  Kriterien: falsches Berufsfeld, kultureller    │
│  Mismatch, zu hohes/niedriges Senioritätslevel │
│  Schwellwert: bewusst liberal (lieber false     │
│  positive als gute Stellen verlieren)           │
└──────────────────────┬──────────────────────────┘
                       │ PASS
                       ▼
┌─────────────────────────────────────────────────┐
│  Stufe 2 – Tiefanalyse (Claude Haiku)          │
│  Standard: claude-haiku-4-5                     │
│  Input: Stelle + Kontext (siehe Strategie)      │
│  Output: Score 1–10 + 5 Dimensionen            │
│          + Empfehlung + Details bei Score ≥ 7   │
└─────────────────────────────────────────────────┘
```

### Bewertungsdimensionen

| Dimension | Gewicht | Beschreibung |
|---|---|---|
| Skills-Match | 35% | Überschneidung Primary/Secondary Skills |
| Erfahrungslevel | 25% | Senior/Lead-Anforderung passt zu Profil |
| Branche/Domäne | 20% | Bekannte vs. neue Industrie |
| Standort/Remote | 15% | Geografische Passung (via ÖPNV-Score) |
| Karrierepotenzial | 5% | Wachstumsmöglichkeit, Technologie-Zukunft |

Gewichte sind konfigurierbar und werden durch den Feedback-Loop
implizit angepasst.

### Evaluierungsstrategie (A/B-Test)

Drei Strategien werden parallel getestet und verglichen:

| Strategie | Kontext im Prompt | Token-Kosten |
|---|---|---|
| `full_profile` | Alle Dokumente direkt (~25.000 Token) | ~$0.031/Stelle |
| `structured_core` | Nur Kernprofil-JSON (~400 Token) | ~$0.008/Stelle |
| `rag_hybrid` | Kernprofil + RAG-Chunks (~4.300 Token) | ~$0.014/Stelle |

Vergleichsmetrik: `score_delta` (wie gut trifft das Modell
deine eigenen Entscheidungen). Messung über mehrere Wochen,
dann Entscheidung für eine Strategie.

```sql
ALTER TABLE evaluations ADD COLUMN eval_strategy TEXT;
-- 'full_profile' | 'structured_core' | 'rag_hybrid'
```

### Das Kernprofil-JSON

Einmalig von Claude Sonnet aus allen Dokumenten extrahiert,
danach manuell geprüft und angepasst:

```json
{
  "skills": {
    "primary":   ["Python", "Kubernetes", "PostgreSQL"],
    "secondary": ["TypeScript", "Terraform", "Kafka"],
    "domains":   ["Backend", "Data Engineering", "Cloud"]
  },
  "experience": {
    "total_years": 8,
    "levels_held": ["Senior", "Lead"],
    "industries":  ["FinTech", "E-Commerce", "Öffentlicher Dienst"]
  },
  "preferences": {
    "locations": ["Hessen", "Rheinland-Pfalz", "Remote"],
    "min_level": "Senior",
    "avoid":     ["Consulting", "Reisebereitschaft >20%"]
  }
}
```

### Arbeitszeugnisse: Aufbereitung

Zeugnisse werden nicht roh indexiert sondern einmalig aufbereitet:

```
Schritt 1 – Dekodierung (Claude Sonnet):
  Input:  Roher Zeugnistext
  Output: {
    "aufgaben":  ["konkrete Tätigkeiten"],
    "staerken":  ["eigenverantwortlich", "konzeptionell stark"],
    "niveau":    1–5 (1 = sehr gut, deutsche Zeugnissprache),
    "kontext":   "Was das Unternehmen machte, welche Rolle"
  }

Schritt 2 – Narratives Stärkenprofil (aus allen Zeugnissen):
  "Über mehrere Stationen: eigenverantwortliche Konzeption,
   Führung kleinerer Teams, Stärke bei komplexen Systemen."
```

Das narrative Profil fließt in den Evaluierungs-Prompt als
Charakterisierung – nicht als Keywords.

### RAG-Chunking-Strategie

| Dokument | Chunk-Strategie | Prefix |
|---|---|---|
| CV | Semantisch nach Abschnitten (pro Stelle, Ausbildung) | – |
| Projekte | Ein Chunk pro Projekt, max. 400 Token | `[Projekt: Name, Dauer, Tech]` |
| Zeugnisse | Aufbereitete Zusammenfassung (nicht Originaltext) | – |
| Zertifikate | Kurze Chunks für Skill-Belege | `[Zertifikat: Name, Aussteller, Jahr]` |

### Feedback-Loop

**Mechanismus:** Deine Entscheidungen (APPLY / MAYBE / IGNORE / SKIP)
werden als Few-Shot-Beispiele in den Stufe-2-Prompt eingefügt.
Ab ~15 Einträgen lernt das Modell deine Präferenzen implizit.

```python
{
  "job_snapshot":    { ... },   # Titel, Firma, Schlüsselanforderungen
  "decision":        "IGNORE",
  "reasoning":       "zu AWS-lastig",   # optional, privat
  "model_score":     7.2,
  "score_delta":     -2.2,       # du hast niedriger bewertet → Lernsignal
  "feedback_version": 3
}
```

**Kaltstart:** 5–8 manuelle Seed-Einträge in `feedback_seed.yaml`
für die erste Woche.

**Transparenz:** Dashboard zeigt erkannte Muster:
*„Du meidest AWS-only-Stacks, bevorzugst Unternehmen < 500 MA"*
Einzelne Einträge können gelöscht oder korrigiert werden.

**Anonymisierter Export:** Feedback ohne persönliche Begründungen,
Firmennamen durch Branchenkategorie ersetzt → für Community-Sharing.

---

## 4. Standort & ÖPNV

### Geschichtete Standort-Pipeline

```
Neue Stelle
     │
     ▼
Schicht 1  Cache-Lookup (companies-DB)
     │ Kein Treffer
     ▼
Schicht 2  Klassifikation: Full Remote? → Score 1.0, fertig
     │ Nicht Remote
     ▼
Schicht 3  Adress-Recherche (agentisch, 4 Stufen)
     │ Adresse gefunden
     ▼
Schicht 4  ÖPNV-API → Reisezeit
     │
     ▼
Score-Berechnung
```

### Adress-Recherche (4 Stufen)

```
Stufe 1  companies-DB fuzzy lookup
Stufe 2  Impressum der Stellen-Website scrapen
Stufe 3  Unternehmens-Homepage Impressum (via SearXNG)
Stufe 4  Nominatim (OpenStreetMap, kostenlos, kein Key)
──────────────────────────────────────────────────────
Kein Treffer → 🟡/🔴 Klärungsbedarf (nach Score priorisiert)
```

### ÖPNV-APIs (konfigurierbar)

```json
{
  "transit_apis": [
    {
      "name": "db_rest",
      "priority": 1,
      "base_url": "https://v6.db.transport.rest",
      "enabled": true
    },
    {
      "name": "transport_rest",
      "priority": 2,
      "base_url": "https://v1.db.transport.rest",
      "enabled": true
    }
  ],
  "transit": {
    "home_address": "...",         // nur in config.yaml, nie in DB
    "max_acceptable_minutes": 60,
    "cache_ttl_days": 90,
    "departure_time": "08:00",
    "departure_weekday": "tuesday" // repräsentativ, kein Mo/Fr
  }
}
```

> Die Heimatadresse wird **nie in der DB gespeichert** –
> nur ihr SHA256-Hash als Cache-Key (`origin_hash`).

### Hybrid-Score-Gewichtung

| Arbeitsmodell | Gewicht | Logik |
|---|---|---|
| Full Remote | 0.0 | Ort irrelevant |
| Hybrid 1x/Woche | 0.2 | 60 min Fahrt = 12 min/Tag effektiv |
| Hybrid 2–3x/Woche | 0.5 | spürbar aber nicht dominierend |
| Hybrid 4–5x/Woche | 0.8 | fast wie Onsite |
| Onsite | 1.0 | volle Penalisierung |
| Unbekannt | 0.6 | konservative Schätzung + Hinweis |

```python
def location_score(transit_min: int, model: str, max_min: int = 60) -> float:
    effective = transit_min * WEIGHTS[model]
    if effective <= max_min:
        return 1.0 - (effective / max_min) * 0.3
    return max(0.0, 0.7 - (effective - max_min) / 60 * 0.5)
```

### Unternehmens-Datenbank

```sql
CREATE TABLE companies (
    id                    INTEGER PRIMARY KEY,
    name                  TEXT NOT NULL,
    name_normalized       TEXT NOT NULL,
    name_aliases          TEXT,              -- JSON
    address_street        TEXT,
    address_city          TEXT,
    address_zip           TEXT,
    lat                   REAL,
    lng                   REAL,
    address_status        TEXT DEFAULT 'unknown',
    address_source        TEXT,
    agent_findings        TEXT,              -- JSON: Zwischenergebnisse
    remote_policy         TEXT DEFAULT 'unknown',
    careers_url           TEXT,
    ats_system            TEXT,
    created_at            TEXT DEFAULT (datetime('now')),
    updated_at            TEXT DEFAULT (datetime('now'))
);

CREATE TABLE transit_cache (
    company_id      INTEGER REFERENCES companies(id),
    origin_hash     TEXT NOT NULL,           -- Hash der Heimatadresse
    transit_minutes INTEGER NOT NULL,
    api_used        TEXT,
    cached_at       TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    UNIQUE(company_id, origin_hash)
);
```

---

## 5. Datenbank

### Übersicht

**SQLite** als einzige relationale Datenbank – kein Server,
portabel, einfach zu sichern (`tar -czf backup.tar.gz ./data`).

**ChromaDB** embedded im Backend-Prozess für RAG-Vektoren.

### Schema

#### Stellen & Quellen

```sql
CREATE TABLE jobs (
    id                  INTEGER PRIMARY KEY,
    canonical_id        TEXT UNIQUE NOT NULL,
    title               TEXT NOT NULL,
    company_id          INTEGER REFERENCES companies(id),
    location_raw        TEXT,
    location_status     TEXT DEFAULT 'unknown',
    work_model          TEXT,
    hybrid_days_hint    INTEGER,
    salary_raw          TEXT,
    salary_min          INTEGER,
    salary_max          INTEGER,
    deadline            TEXT,
    first_seen_at       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL,
    status              TEXT DEFAULT 'new',
    is_active           BOOLEAN DEFAULT TRUE,
    content_hash        TEXT,
    raw_text            TEXT,
    change_history      TEXT,                -- JSON-Array
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- Status-Werte:
-- 'new' | 'reviewed' | 'applying' | 'applied'
-- 'interview' | 'offer' | 'rejected' | 'expired' | 'ignored'

CREATE TABLE job_sources (
    id              INTEGER PRIMARY KEY,
    job_id          INTEGER NOT NULL REFERENCES jobs(id),
    url             TEXT UNIQUE NOT NULL,
    source_name     TEXT NOT NULL,
    source_type     TEXT NOT NULL,  -- 'aggregator'|'portal'|'direct'|'ats'
    is_canonical    BOOLEAN DEFAULT FALSE,
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    last_checked_at TEXT,
    is_available    BOOLEAN,
    content_hash    TEXT
);
```

#### Evaluierungen

```sql
CREATE TABLE evaluations (
    id                    INTEGER PRIMARY KEY,
    job_id                INTEGER UNIQUE NOT NULL REFERENCES jobs(id),
    eval_strategy         TEXT,     -- 'full_profile'|'structured_core'|'rag_hybrid'
    stage1_pass           BOOLEAN,
    stage1_reason         TEXT,
    stage1_model          TEXT,
    stage1_ms             INTEGER,
    stage2_score          REAL,     -- 1.0–10.0
    stage2_score_breakdown TEXT,    -- JSON: {skills, level, domain, location, potential}
    stage2_recommendation TEXT,     -- 'APPLY'|'MAYBE'|'SKIP'
    stage2_match_reasons  TEXT,     -- JSON-Array
    stage2_missing_skills TEXT,     -- JSON-Array
    stage2_salary_estimate TEXT,
    stage2_summary        TEXT,
    stage2_application_tips TEXT,   -- JSON-Array
    stage2_model          TEXT,
    stage2_tokens_used    INTEGER,
    stage2_ms             INTEGER,
    location_score        REAL,
    location_effective_minutes INTEGER,
    evaluated_at          TEXT NOT NULL,
    profile_version       TEXT,     -- Hash des Kernprofils
    needs_reevaluation    BOOLEAN DEFAULT FALSE
);
```

#### Feedback-Loop

```sql
CREATE TABLE feedback (
    id                        INTEGER PRIMARY KEY,
    job_id                    INTEGER NOT NULL REFERENCES jobs(id),
    decision                  TEXT NOT NULL,  -- 'APPLY'|'MAYBE'|'IGNORE'|'SKIP'
    reasoning                 TEXT,           -- PRIVAT, wird beim Export entfernt
    model_score               REAL,
    model_recommendation      TEXT,
    score_delta               REAL,
    job_snapshot              TEXT,           -- JSON (anon. exportierbar)
    model_reasoning_snapshot  TEXT,
    decided_at                TEXT NOT NULL,
    feedback_version          INTEGER,
    is_seed                   BOOLEAN DEFAULT FALSE
);

CREATE TABLE preference_patterns (
    id              INTEGER PRIMARY KEY,
    pattern_type    TEXT NOT NULL,
    pattern_key     TEXT NOT NULL,
    pattern_value   TEXT,
    confidence      REAL,
    sample_count    INTEGER,
    last_updated    TEXT,
    is_active       BOOLEAN DEFAULT TRUE
);
```

#### Anschreiben

```sql
CREATE TABLE cover_letters (
    id                      INTEGER PRIMARY KEY,
    job_id                  INTEGER NOT NULL REFERENCES jobs(id),
    version                 INTEGER NOT NULL DEFAULT 1,
    subject                 TEXT,
    salutation              TEXT,
    body                    TEXT NOT NULL,   -- JSON mit Absätzen
    closing                 TEXT,
    model_used              TEXT,
    tokens_used             INTEGER,
    profile_version         TEXT,
    rag_chunks_used         TEXT,            -- JSON
    feedback_examples_used  INTEGER,
    quality_score           REAL,
    quality_feedback        TEXT,            -- JSON: Verbesserungshinweise
    is_sent                 BOOLEAN DEFAULT FALSE,
    sent_at                 TEXT,
    notes                   TEXT,
    created_at              TEXT DEFAULT (datetime('now')),
    is_active               BOOLEAN DEFAULT TRUE
);
```

#### Analytics

```sql
CREATE TABLE job_skills (
    job_id      INTEGER REFERENCES jobs(id),
    skill       TEXT NOT NULL,
    skill_type  TEXT,    -- 'required'|'nice_to_have'|'mentioned'
    confidence  REAL,
    PRIMARY KEY (job_id, skill)
);

CREATE TABLE skill_trends (
    skill           TEXT NOT NULL,
    period_start    TEXT NOT NULL,
    job_count       INTEGER,
    avg_salary_min  INTEGER,
    source_mix      TEXT,            -- JSON
    PRIMARY KEY (skill, period_start)
);
```

#### Scraping-Log & Klärungsbedarf

```sql
CREATE TABLE scrape_runs (
    id              INTEGER PRIMARY KEY,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT,
    sources_run     TEXT,            -- JSON-Array
    stats           TEXT,            -- JSON
    error_log       TEXT             -- JSON-Array
);

CREATE TABLE clarification_queue (
    id              INTEGER PRIMARY KEY,
    entity_type     TEXT NOT NULL,   -- 'job'|'company'
    entity_id       INTEGER NOT NULL,
    issue_type      TEXT NOT NULL,
    priority        TEXT DEFAULT 'normal',  -- 'high'|'normal'|'low'
    severity        TEXT DEFAULT 'yellow',  -- 'red'|'yellow'
    attempts        TEXT,            -- JSON: [{stage, tried_at, result}]
    last_attempt_at TEXT,
    resolved        BOOLEAN DEFAULT FALSE,
    resolved_at     TEXT,
    resolved_by     TEXT,            -- 'manual'|'stage4_llm'|'auto'
    resolution_note TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);
```

#### Multi-User-Support (Migration 003)

User-bezogene Tabellen erhalten `user_id TEXT REFERENCES users(id)`:

| Tabelle | Änderung |
|---|---|
| `evaluations` | `UNIQUE(job_id)` → `UNIQUE(job_id, user_id)` |
| `feedback` | `user_id` FK hinzugefügt |
| `cover_letters` | `user_id` FK hinzugefügt |
| `preference_patterns` | `user_id` FK hinzugefügt |

Geteilte Tabellen (ohne `user_id`): `jobs`, `companies`, `job_sources`,
`transit_cache`, `scrape_runs`, `clarification_queue`, `job_skills`, `skill_trends`.

Default-User `00000000-…-000000000001` wird automatisch angelegt.
Vollständige Details: [ADR-007](../docs/adr/007-datenbankdesign.md).

### Designprinzipien

- **Soft Deletes:** Nichts wird gelöscht, nur `is_active = FALSE`
- **Anonymisierung by Design:** Persönliche Daten (Heimatadresse,
  persönliche Begründungen) nie im Klartext in der DB
- **profile_version:** In `evaluations` und `cover_letters` –
  zeigt welche Einträge nach einer Profiländerung neu berechnet werden müssen
- **JSON für volatile Strukturen:** `change_history`, `agent_findings`,
  Score-Breakdown – alles was sich strukturell ändern könnte

### Indizes

```sql
CREATE INDEX idx_jobs_status       ON jobs(status);
CREATE INDEX idx_jobs_canonical    ON jobs(canonical_id);
CREATE INDEX idx_jobs_company      ON jobs(company_id);
CREATE INDEX idx_jobs_deadline     ON jobs(deadline);
CREATE INDEX idx_eval_score        ON evaluations(stage2_score);
CREATE INDEX idx_eval_strategy     ON evaluations(eval_strategy);
CREATE INDEX idx_eval_profile      ON evaluations(profile_version);
CREATE INDEX idx_feedback_decision ON feedback(decision);
CREATE INDEX idx_feedback_delta    ON feedback(score_delta);
CREATE INDEX idx_clarif_open       ON clarification_queue(resolved, priority);
CREATE INDEX idx_companies_name    ON companies(name_normalized);
CREATE INDEX idx_transit_company   ON transit_cache(company_id, origin_hash);
```

---

## 6. Anschreiben-Generator

### Pipeline

```
Stufe 1 – Kontext-Aufbereitung
  a) RAG: relevante CV/Projekt-Chunks für diese Stelle
  b) Stil-Profil: einmalig aus Beispiel-Anschreiben extrahiert
  c) Tonalitäts-Profil: Arbeitgeber-Typ bestimmt
  d) Schlüsselanforderungen: die 3 wichtigsten Punkte der Stelle
        │
Stufe 2 – Generierung (Claude Sonnet)
  Input:  Kontexte aus Stufe 1 + Struktur-Vorgabe
  Output: JSON mit Absätzen (nicht Fließtext)
        │
Stufe 3 – Qualitätsprüfung (Claude Haiku)
  Prüft: Floskeln, adressierte Anforderungen, Ton, Belege
  Output: Score + Hinweise → im Dashboard angezeigt
          (nicht automatisch korrigiert)
```

### Arbeitgeber-Tonalität

| Typ | Ton | Länge | Besonderheiten |
|---|---|---|---|
| Startup / KMU | Direkt, persönlich | 3 Abs. | Motivation > Formalität |
| Konzern | Professionell, formell | 4 Abs. | Zahlen/Belege, Karrierepfad |
| Behörde | Sehr formell, sachlich | 4 Abs. | Anforderungen punkt-für-punkt |
| Hochschule / Forschung | Sachlich, präzise | 4 Abs. | Projekte, Interdisziplinarität |
| Öffentl. Unternehmen | Hybrid | 4 Abs. | Zwischen Konzern und Behörde |

Tonalität wird automatisch aus `employer_type` der Evaluation
bestimmt – kein manuelles Auswählen nötig.

### Absatz-Datenmodell

Anschreiben werden als strukturiertes JSON gespeichert –
nie als Fließtext. Das ermöglicht gezielte Absatz-Regenerierung.

```json
{
  "meta": {
    "job_id": 42,
    "employer_type": "behoerde",
    "quality_score": 7.8
  },
  "sections": {
    "subject":    { "text": "...", "locked": false },
    "opening":    { "text": "...", "intent": "Motivation + Bezug",
                    "rag_chunks_used": ["cv_3", "projekt_x"], "locked": false },
    "competence": { "text": "...", "intent": "Qualifikationen mit Belegen",
                    "locked": false },
    "motivation": { "text": "...", "intent": "Warum diese Stelle",
                    "locked": false },
    "closing":    { "text": "...", "locked": true }
  },
  "quality_feedback": [
    { "type": "warning", "section": "opening",
      "message": "Generische Eröffnung erkannt" }
  ]
}
```

`locked: true` = manuell bearbeitet, wird bei Regenerierung
nicht überschrieben.

### Absatz-Regenerierung mit Kontext-Hint

```
[🔄 Neu generieren]
Hinweis: "Bezug auf Digitalisierungsprojekt des Ministeriums"
→ [Los]
```

Kein vollständiger Chat-Dialog – nur ein optionaler Hint
pro Absatz. Einfach zu implementieren, deutlich nützlicher
als blindes Neu-Generieren.

### Stil-Extraktion (einmalig)

Einmalig aus 2–3 eigenen Beispiel-Anschreiben:

```
Input:  Beispiel-Anschreiben
Output: Stil-Profil JSON (~200 Token)
        - Typische Satzlänge und -struktur
        - Bevorzugte Formulierungen
        - Typischer Absatzeinstieg
        - Was diese Person NIE schreibt
        - Ton: direkt/indirekt, persönlich/sachlich
```

Fließt bei jeder Generierung als Anker mit rein.

### LaTeX-Export

Bestehendes LaTeX-Template wird per Jinja2 befüllt. TeX Live
ist direkt im Backend-Container installiert (minimale Pakete,
~150–300MB) – kein separater Service nötig.

```
Templates:
  anschreiben_privat.tex.j2      → Startup / Konzern
  anschreiben_behoerde.tex.j2    → Behörde (klassischer Briefstil)
  anschreiben_hochschule.tex.j2  → Akademischer Stil

Befüllung:   Jinja2 mit LaTeX-kompatiblen Delimitern (\VAR{...})
Escaping:    Automatisch für alle LaTeX-Sonderzeichen
Rendering:   pdflatex als Subprocess im Backend-Prozess
             (temporäres Verzeichnis, kein Dateisystem-Leak)
```

```python
import subprocess, tempfile
from pathlib import Path

def render_pdf(tex_content: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmpdir:
        tex_file = Path(tmpdir) / "anschreiben.tex"
        tex_file.write_text(tex_content, encoding="utf-8")
        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode",
             "-output-directory", tmpdir, str(tex_file)],
            capture_output=True, timeout=30
        )
        if result.returncode != 0:
            raise LatexRenderError(result.stdout.decode())
        return (Path(tmpdir) / "anschreiben.pdf").read_bytes()
```

Benötigte Debian-Pakete im Backend-Dockerfile:
```dockerfile
RUN apt-get install -y --no-install-recommends \
    texlive-latex-base \
    texlive-latex-recommended \
    texlive-fonts-recommended \
    texlive-lang-german \
    && rm -rf /var/lib/apt/lists/*
```

---

## 7. Dashboard

### Technologie

```
React + TypeScript + Vite
shadcn/ui + Tailwind CSS     → UI-Komponenten
TanStack Query               → API-State-Management
TanStack Table               → Stellenliste
Recharts                     → Standard-Charts
D3.js                        → Skill-Netzwerk, komplexe Visualisierungen
React Router                 → Navigation
```

### Seitenstruktur

```
Header (immer sichtbar):
  [3 neu] [2 ⚠️ Klärungsbedarf] [1 🔴 dringend] [▶ Scan] [Letzter Scan]

Seiten:
  1. Übersicht    → Daily View, neue Stellen, Schnellaktionen
  2. Stellen      → Vollständige Liste mit Filtern + Detail-Panel
  3. Klärungsbedarf → Drilldown für ungeklärte Adressen/Websites
  4. Analytics    → Marktanalyse, eigene Pipeline, Modell-Kalibrierung
  5. Steuerung    → Scraping, Evaluation, Quellen, Feedback-Export
```

### Seite 1: Übersicht (Daily View)

Ziel: In < 5 Minuten die neuen Stellen reviewen.

- KPI-Kacheln: Neu, Gesamt offen, Frist < 7 Tage, Interviews
- Liste der neuen Stellen seit gestern (nach Score sortiert)
- Pro Stelle: Score, Titel, Unternehmen, Ort, ÖPNV-Zeit, Frist
- Aktionen: `[Reviewed]` `[Anschreiben ✨]` `[Ignorieren]`
- Klärungsbedarf-Zusammenfassung mit direktem Link

### Seite 2: Stellen

- Filterbar: Status, Score, Quelle, Frist, Arbeitsmodell, Freitext
- Tabelle sortierbar nach Score, Frist, Datum
- Klick → Detail-Panel (kein Seitenwechsel):
  - Score-Breakdown als Balkendiagramm (5 Dimensionen)
  - Match-Gründe und fehlende Skills
  - ÖPNV-Details (effektive Minuten nach Hybrid-Gewichtung)
  - Links: Firmenwebsite, Originalanzeige
  - Status setzen, Feedback geben, Anschreiben generieren

### Seite 3: Klärungsbedarf

- 🔴 Dringend zuerst (Score > 7, Problem offen)
- 🟡 Normal eingeklappt, nach Score sortiert
- Pro Eintrag: was wurde versucht, gefundene Hinweise
- Aktionen: URL eingeben, Näherung übernehmen,
  Stufe 4 on-demand, Ausblenden

### Seite 4: Analytics

- Technologie-Trends (Balkendiagramm, zeitlich)
- Gehaltsverteilung (Histogram)
- Remote-Anteil nach Branche
- Skill-Netzwerk (D3, Verbindungsstärke = gemeinsames Vorkommen)
- Eigene Pipeline (Funnel: Gefunden → Bewerbt → Interview → Angebot)
- Modell-Kalibrierung: Ø Score-Delta pro Strategie
- Beste Quellen für dich (Ø Score nach Quelle)

### Seite 5: Steuerung

- Scraping: manueller Trigger, nächster Auto-Scan, Quellen-Status
- Evaluation: Neu bewerten (alle / veraltete), Profil bearbeiten
- Feedback: Anzahl Einträge, erkannte Muster, anonymisierter Export
- RAG: Index-Status, neu indexieren
- ÖPNV-Cache: Einträge, abgelaufene erneuern

### Scan-Trigger

Pull-basiert – kein dauerlaufender Service:

```python
# FastAPI: Scan als Background-Task
@app.post("/api/scrape/start")
async def start_scrape(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_pipeline)
    return {"status": "started"}

# Frontend: Status alle 5s pollen während Scan läuft
# Kein WebSocket nötig
```

---

## 8. Infrastruktur & Docker

### Service-Übersicht

| Service | Typ | Läuft in Docker | Anmerkung |
|---|---|---|---|
| FastAPI Backend | Selbst entwickelt | ✅ | Inkl. TeX Live + Playwright |
| React Frontend | Selbst entwickelt | ✅ nginx (nur Prod) | Dev: nativer Vite-Dev-Server |
| SQLite | Datei | – (Bind-Mount) | – |
| ChromaDB | Embedded in Backend | – | – |
| Ollama | Third-Party | ❌ (nativ, GPU) | – |
| Anthropic API | Extern | – | – |
| DB REST / ÖPNV | Extern | – | – |

Im Entwicklungsalltag läuft **ein einziger Container** (Backend).
Das Frontend läuft nativ mit `npm run dev` (Vite, Port 5173).

**Entfernte Services gegenüber ursprünglichem Plan:**
- SearXNG → ersetzt durch `duckduckgo-search` Python-Library
- TeX Live (on-demand Container) → direkt im Backend-Container installiert
- Frontend-Container → in Entwicklung nicht nötig (Vite Dev Server)

### Verzeichnisstruktur

```
job-agent/
├── docker-compose.yml
├── docker-compose.prod.yml      # Heimserver-Overrides
├── .env                         # git-ignored
├── .env.example
├── config/
│   ├── config.yaml              # git-ignored
│   ├── config.example.yaml
│   └── sources.json             # Scraping-Quellen
├── backend/
│   └── Dockerfile               # inkl. TeX Live + Playwright
├── frontend/
│   └── Dockerfile               # nur für Produktion genutzt
├── templates/
│   ├── anschreiben_privat.tex.j2
│   ├── anschreiben_behoerde.tex.j2
│   └── anschreiben_hochschule.tex.j2
└── data/                        # Bind-Mount, git-ignored
    ├── jobs.db
    ├── chroma/
    ├── exports/
    └── logs/
```

### docker-compose.yml (Kernstruktur)

```yaml
services:
  backend:
    build: ./backend
    restart: unless-stopped
    ports: ["8000:8000"]
    volumes:
      - ./data:/app/data
      - ./config:/app/config:ro
      - ./templates:/app/templates:ro
    environment:
      - OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-http://host.docker.internal:11434}
    secrets:
      - anthropic_key          # sicherer als Umgebungsvariable
    extra_hosts:
      - "host.docker.internal:host-gateway"
    user: "1000:1000"          # non-root
    security_opt:
      - no-new-privileges:true

  # Nur in docker-compose.prod.yml aktiv:
  # frontend:
  #   build: ./frontend
  #   restart: unless-stopped
  #   ports: ["3000:80"]
  #   depends_on: [backend]

secrets:
  anthropic_key:
    file: ./secrets/anthropic_key.txt   # gitignored, nur der Wert
```

Im Entwicklungsalltag startet `make dev` den Backend-Container
plus den Vite Dev Server nativ – kein weiterer Container nötig.

### Cron-Job (Host)

```bash
# crontab -e
0 7 * * 1-5 curl -s -X POST http://localhost:8000/api/scrape/start
0 7 * * 1   curl -s -X POST http://localhost:8000/api/scrape/start?profile=weekly
```

### Heimserver-Migration

Änderungen für `docker-compose.prod.yml`:
- `restart: always` statt `unless-stopped`
- Frontend-Service aktivieren (nginx, Port 3000)
- Feste Ollama-IP statt `host.docker.internal`
- nginx Reverse Proxy mit self-signed Cert für LAN-Zugriff
- `VITE_API_URL` auf lokale Domain

### Secrets & Umgebungsvariablen

```bash
# .env.example – nur nicht-sensitive Konfiguration
OLLAMA_BASE_URL=http://host.docker.internal:11434
BACKEND_PORT=8000
FRONTEND_PORT=3000

# secrets/anthropic_key.txt – git-ignored, nur der reine Key-Wert
# sk-ant-...
```

Der Anthropic API-Key wird als Docker Secret gemountet
(`/run/secrets/anthropic_key`) – nicht als Umgebungsvariable,
die in `docker inspect` sichtbar wäre.

---

## 9. Modelle & LLM-Integration

### Überblick: Aufgaben und Anforderungen

Zehn Aufgaben im System nutzen Sprachmodelle. Sie unterscheiden
sich stark in Frequenz, Qualitätsanforderung und Kostentoleranz:

```
Aufgabe                        Frequenz      Qualität  Speed   Kosten
──────────────────────────────────────────────────────────────────────
Eval Stufe 1 (Filter)          ~200/Tag      Mittel    ★★★★★  €0
Eval Stufe 2 (Tiefanalyse)     ~60/Tag       Hoch      ★★★    €€
RAG Embeddings                 ~200/Tag      Mittel    ★★★★   €0
Anschreiben generieren         ~5/Woche      Sehr hoch ★★     €€€
Scraping Typ C (Extraktion)    ~50/Woche     Mittel    ★★★    €0
Adress-Extraktion              ~20/Woche     Mittel    ★★★★   €0
Firmenwebsite-Suche            ~60/Tag       Niedrig   ★★★★★  €0
Zeugnis-Dekodierung            Einmalig      Hoch      egal   €€
Kernprofil-Extraktion          Einmalig      Sehr hoch egal   €€€
Stil-Extraktion                Einmalig      Hoch      egal   €€
```

### Modell-Zuordnung

#### Lokale Modelle via Ollama

**`mistral-nemo:12b` (Q4_K_M, ~7.5GB VRAM)** – primäres lokales Modell:

| Aufgabe | Begründung |
|---|---|
| Eval Stufe 1 | Gutes Deutsch, zuverlässiger JSON-Output |
| Scraping Typ C | Extraktion aus deutschen Stellenseiten |
| Adress-Extraktion | Deutsche Adressen/Impressum-Texte |
| Firmenwebsite-Suche | URL-Plausibilitätsbewertung |

Warum `mistral-nemo:12b` statt `llama3.1:8b`:
- Besser für deutschsprachige Aufgaben (Mistral + NVIDIA co-trainiert)
- Zuverlässigere JSON-Instruktionsbefolgung bei strukturiertem Output
- 128k Context Window für lange Stellentexte
- Passt mit `Q4_K_M`-Quantisierung knapp in 8GB VRAM

`llama3.1:8b` bleibt als Fallback-Option in der Config – A/B-Test
gegen `mistral-nemo:12b` ist in Phase 1 eingeplant.

**`nomic-embed-text` (~270MB)** – ausschließlich für Embeddings:

| Aufgabe | Begründung |
|---|---|
| RAG Embeddings | Spezialisiert, schnell, kostenlos |

#### Claude API (Anthropic SDK)

**`claude-haiku-4-5`** – günstig, schnell, strukturierter Output:

| Aufgabe | Begründung |
|---|---|
| Eval Stufe 2 | Tiefanalyse braucht mehr als 12B, ~10× günstiger als Sonnet |
| Anschreiben Qualitätsprüfung | Einfache Prüfaufgabe |

**`claude-sonnet-4-6`** – beste Qualität, nur wo es zählt:

| Aufgabe | Begründung |
|---|---|
| Anschreiben generieren | Qualität direkt sichtbar, lohnt Aufpreis |
| Zeugnis-Dekodierung | Komplexe deutsche Zeugnissprache, einmalig |
| Kernprofil-Extraktion | Basis für alles andere – hier nicht sparen |
| Stil-Extraktion | Beeinflusst alle zukünftigen Anschreiben |

### Einheitliche Schnittstelle: ModelRegistry (direkte SDKs)

Statt LiteLLM als Abstraktionsschicht (aufgrund dokumentierter
Sicherheitsprobleme entfernt — siehe Tech-Audit, 10+ CVEs) werden
die Provider-SDKs direkt verwendet:

- **`anthropic`** (AsyncAnthropic) für Claude-Tasks
- **`ollama`** (AsyncClient) für lokale Modelle + Embeddings

Die `ModelRegistry` bleibt als einheitliche Schnittstelle bestehen —
intern dispatcht sie basierend auf dem `provider`-Feld in der
`TaskConfig` an den jeweiligen Client.

```
┌──────────────────────────────────────────────────────────┐
│                    ModelRegistry                         │
│           registry.complete(task, prompt)                │
└──────────────┬──────────────────────┬────────────────────┘
               │ provider="anthropic" │ provider="ollama"
               ▼                      ▼
        AsyncAnthropic          AsyncClient
         (anthropic)             (ollama)
               │                      │
               ▼                      ▼
         Anthropic API         Ollama (lokal, GPU)
```

Kernvorteil bleibt: Modell wechseln = eine Zeile in `config.yaml`.
Provider wechseln = `provider`-Feld anpassen. Direkte Voraussetzung
für den Modell-A/B-Test.

### Konfiguration

Alle Modell-Parameter pro Aufgabe in `config.yaml`:

```yaml
models:

  ollama:
    base_url: "http://localhost:11434"

    tasks:
      eval_stage1:
        model: "mistral-nemo:12b"
        temperature: 0.1        # deterministisch für Filter
        max_tokens: 150         # {"pass": true, "reason": "..."}
        timeout_s: 30

      scraping_extraction:
        model: "mistral-nemo:12b"
        temperature: 0.1
        max_tokens: 2000
        timeout_s: 60

      address_extraction:
        model: "mistral-nemo:12b"
        temperature: 0.0        # maximal deterministisch
        max_tokens: 200
        timeout_s: 20

      careers_url_rating:
        model: "mistral-nemo:12b"
        temperature: 0.0
        max_tokens: 100
        timeout_s: 15

    embeddings:
      model: "nomic-embed-text"
      timeout_s: 10

  anthropic:
    tasks:
      eval_stage2:
        model: "claude-haiku-4-5"
        temperature: 0.2
        max_tokens: 1000
        timeout_s: 30

      cover_letter_generate:
        model: "claude-sonnet-4-6"
        temperature: 0.7        # mehr Varianz für Anschreiben
        max_tokens: 2000
        timeout_s: 60

      cover_letter_quality_check:
        model: "claude-haiku-4-5"
        temperature: 0.1
        max_tokens: 500
        timeout_s: 20

      profile_extraction:
        model: "claude-sonnet-4-6"
        temperature: 0.1
        max_tokens: 2000
        timeout_s: 60

      certificate_decoding:
        model: "claude-sonnet-4-6"
        temperature: 0.1
        max_tokens: 1500
        timeout_s: 60

      style_extraction:
        model: "claude-sonnet-4-6"
        temperature: 0.1
        max_tokens: 1000
        timeout_s: 60
```

### ModelRegistry – Implementierung

```python
# backend/app/core/models.py

from enum import Enum
from dataclasses import dataclass
import anthropic
import ollama
from app.core.config import Settings

class ModelTask(str, Enum):
    EVAL_STAGE1             = "eval_stage1"
    EVAL_STAGE2             = "eval_stage2"
    SCRAPING_EXTRACTION     = "scraping_extraction"
    ADDRESS_EXTRACTION      = "address_extraction"
    CAREERS_URL_RATING      = "careers_url_rating"
    COVER_LETTER_GENERATE   = "cover_letter_generate"
    COVER_LETTER_CHECK      = "cover_letter_quality_check"
    PROFILE_EXTRACTION      = "profile_extraction"
    CERTIFICATE_DECODING    = "certificate_decoding"
    STYLE_EXTRACTION        = "style_extraction"

@dataclass
class TaskConfig:
    provider:    str    # "ollama" oder "anthropic"
    model:       str    # "mistral-nemo:12b" oder "claude-haiku-4-5"
    temperature: float
    max_tokens:  int
    timeout_s:   int

class ModelRegistry:
    """
    Zentraler Zugangspunkt für alle LLM-Calls.
    Einmalig beim Start initialisiert, per Dependency Injection
    an alle Services weitergegeben.

    Dispatcht intern an anthropic.AsyncAnthropic oder
    ollama.AsyncClient — kein LiteLLM (siehe Tech-Audit).
    """

    def __init__(self, settings: Settings):
        self._anthropic = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
        )
        self._ollama = ollama.AsyncClient(
            host=settings.ollama_host,
        )
        self._configs = self._build_configs(settings)

    def _build_configs(self, settings) -> dict[ModelTask, TaskConfig]:
        configs = {}
        for section in ("ollama", "anthropic"):
            for task_name, cfg in settings.models[section]["tasks"].items():
                configs[ModelTask(task_name)] = TaskConfig(
                    provider=section,
                    model=cfg["model"],
                    temperature=cfg["temperature"],
                    max_tokens=cfg["max_tokens"],
                    timeout_s=cfg["timeout_s"],
                )
        return configs

    async def complete(
        self,
        task: ModelTask,
        prompt: str,
        system: str | None = None,
    ) -> str:
        """Einheitlicher Completion-Call – Provider-Details sind gekapselt."""
        cfg = self._configs[task]

        if cfg.provider == "anthropic":
            response = await self._anthropic.messages.create(
                model=cfg.model,
                max_tokens=cfg.max_tokens,
                temperature=cfg.temperature,
                system=system or "",
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text

        # provider == "ollama"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await self._ollama.chat(
            model=cfg.model,
            messages=messages,
            options={"temperature": cfg.temperature, "num_predict": cfg.max_tokens},
        )
        return response["message"]["content"]

    async def embed(self, text: str) -> list[float]:
        """Embedding – immer lokal via nomic-embed-text."""
        response = await self._ollama.embed(
            model="nomic-embed-text",
            input=text,
        )
        return response["embeddings"][0]
```

Verwendung in der Evaluierungs-Pipeline:

```python
# backend/app/evaluator/stage1.py
class Stage1Filter:
    def __init__(self, registry: ModelRegistry):
        self._registry = registry

    async def filter(self, job: Job) -> Stage1Result:
        raw = await self._registry.complete(
            task=ModelTask.EVAL_STAGE1,
            prompt=STAGE1_PROMPT.format(job_text=job.raw_text[:1500]),
        )
        data = extract_json(raw)   # robust gegen Präambeln + Markdown-Fences
        return Stage1Result(pass_filter=data["pass"], reason=data["reason"])
```

### Fehlerbehandlung

Drei häufige Fehlerquellen mit expliziter Behandlung:

**Ollama nicht erreichbar:**
```python
except httpx.ConnectError:
    raise ModelUnavailableError(
        "Ollama nicht erreichbar. Bitte 'ollama serve' ausführen."
    )
```

**Invalides JSON vom lokalen Modell** (passiert regelmäßig bei 12B):
```python
# backend/app/core/json_utils.py
def extract_json(raw: str) -> dict:
    """Extrahiert JSON robust – entfernt Präambeln und Markdown-Fences."""
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0]
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0]
    start, end = raw.find("{"), raw.rfind("}") + 1
    if start == -1:
        raise JSONExtractionError(f"Kein JSON in Antwort: {raw[:200]}")
    return json.loads(raw[start:end])
```

**Anthropic Rate Limit:**
```python
except anthropic.RateLimitError:
    await asyncio.sleep(60)
    return await self.complete(task, prompt, system)  # einmaliger Retry
```

### Kosten-Tracking

API-Kosten werden pro Call in der DB erfasst und im Dashboard
auf der Steuerungs-Seite angezeigt:

```sql
ALTER TABLE evaluations  ADD COLUMN stage2_cost_usd REAL;
ALTER TABLE cover_letters ADD COLUMN cost_usd        REAL;
```

```python
PRICE_PER_1K_TOKENS = {
    "claude-haiku-4-5":  {"input": 0.00025, "output": 0.00125},
    "claude-sonnet-4-6": {"input": 0.003,   "output": 0.015},
}

def estimate_cost(model: str, input_tok: int, output_tok: int) -> float:
    p = PRICE_PER_1K_TOKENS.get(model, {"input": 0, "output": 0})
    return input_tok / 1000 * p["input"] + output_tok / 1000 * p["output"]
```

Dashboard-Anzeige (Steuerungs-Seite):
```
Kosten diese Woche:
  Evaluierungen  (Haiku):   $0.43   87 Stellen
  Anschreiben    (Sonnet):  $0.31    6 Anschreiben
  ───────────────────────────────
  Gesamt:                   $0.74
```

### Modell-A/B-Test

Die Config-Struktur ermöglicht systematisches Testen ohne
Code-Änderungen. Geplante Vergleiche:

| Task | Variante A | Variante B |
|---|---|---|
| `eval_stage1` | `mistral-nemo:12b` | `llama3.1:8b` |
| `eval_stage2` | `claude-haiku-4-5` | `claude-sonnet-4-6` |
| `scraping_extraction` | `mistral-nemo:12b` | `mistral:7b` |

Tracking in der DB: `evaluations.stage1_model` und
`evaluations.stage2_model` werden bereits gespeichert.
Vergleichsmetrik: `score_delta` (Modell-Score vs. eigene Entscheidung).
Auswertung nach ~200 Feedback-Einträgen, ca. Phase 7.

### Lokale Modell-Alternativen (Referenz)

```
Modell               VRAM (Q4)   Deutsch  JSON-Output  Status
──────────────────────────────────────────────────────────────
mistral-nemo:12b     ~7.5 GB     ★★★★    ★★★★★       Primär ⭐
llama3.1:8b          ~5.5 GB     ★★★     ★★★★        Fallback
mistral:7b           ~4.5 GB     ★★★     ★★★★        Fallback
gemma3:12b           ~8.5 GB     ★★★     ★★★★        Experimentell
mistral-small:22b    ~14 GB      ★★★★★   ★★★★★       Zu groß für 1080
```

---

## 10. Offene Punkte

### Erledigt

| Thema | Block | Notiz |
|---|---|---|
| **Multi-User-Support** | Block 3 | Migration 003: `users`-Tabelle, `user_id` FK in evaluations/feedback/cover_letters/preference_patterns. Details: ADR-007. |
| **LiteLLM entfernt** | Block 4 | Durch direkte `anthropic` + `ollama` SDKs ersetzt (Tech-Audit: 10+ CVEs). |
| **Hybrid Stage-1-Filter** | Block 4 | Stufe 1a (deterministisch) + Stufe 1b (Ollama) statt reinem LLM-Filter. |

### Zurückgestellt (bewusst)

| Thema | Notiz |
|---|---|
| **Profil-Versionierung in DB** | `profile_versions`-Tabelle für saubere Re-Evaluierung, wenn Profil sich ändert |
| **Generischer Klärungsbedarf-Mechanismus** | Resolution Agent als generisches Pattern für alle Klärungstypen (Adresse, Karriereseite, Gehalt, Sprache) |
| **LinkedIn-Scraping** | Technisch fragil – erst angehen wenn andere Quellen stabil laufen |

### Offen / zu entscheiden

| Thema | Optionen | Empfehlung |
|---|---|---|
| **Hessen SPA-API** | Playwright vs. versteckte REST-API | 10-min Netzwerk-Analyse vor Implementierung |
| **ChromaDB-Backup** | Gemeinsam mit SQLite oder getrennt | Gemeinsam ist einfacher, reicht für diesen Use Case |
| **Evaluierungsstrategie** | A/B-Test über mehrere Wochen | Nach ~200 Feedback-Einträgen entscheiden |
| **LinkedIn** | `linkedin-api` Library vs. manueller Import | Erst andere Quellen stabilisieren |

---

## 11. Implementierungsreihenfolge

### Prinzip

**Vertical Slices statt horizontale Schichten.**
Nicht erst alle Scraper, dann alle Evaluierungen, dann Dashboard –
sondern: ein vollständiger Durchlauf mit einer Quelle zuerst,
dann schrittweise erweitern.

### Phase 1 – Fundament (Woche 1–2)

```
1. Datenbankschema (SQLite, alle Tabellen)
2. FastAPI-Grundgerüst mit Health-Endpoint
3. Kernprofil-JSON aus eigenen Dokumenten extrahieren
4. Evaluierungs-Pipeline Stufe 2 (Claude Haiku)
   → Testen mit manuell eingegebenen Stellentexten
```

Ziel: Evaluierung funktioniert, bevor ein Scraper existiert.

### Phase 2 – Erster Scraper + RAG (Woche 2–3)

```
5. interamt.de Scraper (Typ A, stabil)
6. RAG-Pipeline (ChromaDB + nomic-embed-text)
7. Evaluierungs-Pipeline Stufe 1 (Ollama, mistral-nemo:12b)
8. Deduplizierung (Stufe 1 + 2)
9. Minimales Dashboard (Streamlit als Prototyp)
   → Erste echte Stellen sehen und bewerten
```

Ziel: Erster vollständiger Durchlauf, erste echte Daten.

### Phase 3 – Standort & Klärungsbedarf (Woche 3–4)

```
10. companies-Tabelle + ÖPNV-Pipeline (DB REST API)
11. Firmenwebsite-Suche (SearXNG + lokales Modell)
12. Klärungsbedarf-Queue
13. Docker Compose Setup (alle Services)
14. Cron-Job auf Host
```

### Phase 4 – Weitere Quellen (Woche 4–6)

```
15. service.bund.de RSS (Hessen + RLP, sofortiger Mehrwert)
16. StepStone + Indeed RSS
17. karriere.hessen.de (Typ B, Playwright)
18. karriere.rlp.de (Typ B)
19. XING
20. Generischer LLM-Scraper (Typ C) für Behörden-Liste
```

### Phase 5 – React Dashboard (Woche 6–8)

```
21. React-Projektsetup (Vite + shadcn/ui + TanStack)
22. Seite 1: Übersicht (Daily View)
23. Seite 2: Stellen + Detail-Panel
24. Seite 3: Klärungsbedarf
25. Streamlit ablösen
```

### Phase 6 – Anschreiben + Analytics (Woche 8–10)

```
26. Stil-Extraktion aus Beispiel-Anschreiben
27. Anschreiben-Generator (JSON-Struktur, Absatz-Regenerierung)
28. LaTeX-Export (Jinja2 + TeX Live Docker)
29. Qualitätsprüfung (Claude Haiku)
30. Analytics-Seite (Charts, Skill-Trends)
31. Feedback-Loop (Few-Shot ab 15 Einträgen)
32. Anonymisierter Export
```

### Phase 7 – Stabilisierung (Woche 10–12)

```
33. A/B-Test Evaluierungsstrategie auswerten
34. Fehlerbehandlung + Retry-Logik für alle Scraper
35. Heimserver-Migration testen (docker-compose.prod.yml)
36. Dokumentation + README
```

---

*Dieses Dokument wird parallel zur Implementierung gepflegt.
Entscheidungen die sich in der Praxis als falsch herausstellen,
werden hier mit Begründung aktualisiert.*
