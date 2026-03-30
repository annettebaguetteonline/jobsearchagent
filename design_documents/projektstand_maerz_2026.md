# Job Search Agent – Projektstand März 2026

**Stand:** 29. März 2026
**Version:** 1.1

---

## Inhaltsverzeichnis

1. [Gesamtübersicht](#1-gesamtübersicht)
2. [Implementierungsstand nach Modul](#2-implementierungsstand-nach-modul)
3. [Datenbankschema – Aktueller Stand](#3-datenbankschema--aktueller-stand)
4. [Offene Arbeiten](#4-offene-arbeiten)
5. [Offene Grundsatzentscheidungen](#5-offene-grundsatzentscheidungen)
6. [Tech-Stack-Handlungsbedarf](#6-tech-stack-handlungsbedarf)
7. [Priorisierte nächste Schritte](#7-priorisierte-nächste-schritte)

---

## 1. Gesamtübersicht

```
Modul                        Status
─────────────────────────────────────────────────────
Scraping-Pipeline            ✅ Teilweise live (9 Quellen)
Location-Pipeline            ✅ Vollständig implementiert
Evaluierungs-Pipeline        ✅ Vollständig implementiert
Dashboard / Frontend         ✅ Vollständig implementiert (AP-18–AP-33)
Anschreiben-Generator        🔲 Stub (nicht implementiert)
Infrastruktur / Docker       ⚠️  Dev-Setup vorhanden, Prod fehlt
Datenbank-Analyse            🔲 Noch nicht durchgeführt
Multi-User-Support           🔲 Architektur definiert, nicht gebaut
```

---

## 2. Implementierungsstand nach Modul

### 2.1 Scraping-Pipeline

**Implementiert (9 Quellen live):**

| Quelle | Typ | Volltext | Status |
|---|---|---|---|
| service.bund.de | RSS | ✅ | ✅ Live |
| Bundesagentur für Arbeit | REST JSON API | ✅ Detail-API | ✅ Live |
| Arbeitnow | REST JSON API | ✅ | ✅ Live |
| Jooble | REST JSON API | ⚠️ Snippet | ✅ Live |
| Adzuna | REST JSON API | ⚠️ Snippet | ✅ Live |
| Kimeta | Next.js SSR + HTML-Filter | ⚠️ Nur iframe-URLs | ✅ Live |
| Jobbörse.de | httpx + BeautifulSoup | ✅ Detail-Seite | ✅ Live |
| Stellenmarkt.de | RSS-Feed | ⚠️ Snippet | ✅ Live |
| interamt.de | Playwright + httpx | ✅ Detail-Seite | ✅ Live |

**Deduplizierung:**
- Stufe 0 (Source-Job-ID): ✅ implementiert
- Stufe 1 (Hash, canonical_id): ✅ implementiert
- Stufe 2 (Fuzzy-Match, difflib ≥ 85%): ✅ implementiert
- Stufe 3 (LLM, Grenzfälle): 🔲 reserviert, nicht implementiert

**Noch fehlende Scrapers:**

| Quelle | Typ | Technologie |
|---|---|---|
| karriere.hessen.de | B (konfigurierbar) | Playwright |
| karriere.rlp.de | B (konfigurierbar) | Playwright |
| Indeed | A (strukturiert) | RSS-Feed |
| XING | B (konfigurierbar) | Playwright |
| academics.de | B (konfigurierbar) | Playwright |
| Individuelle Behörden | C (generisch) | LLM-Extraktion |
| Firmen-Karriereseiten | C (generisch) | LLM-Extraktion |

**Bekannte Verbesserungen (aus nächste_schritte.txt):**
- Kimeta: Position + Contract kombiniert filtern (effizienter, mehr Treffer)
- Kimeta: Vollständige Contract-Filter implementieren (Vertragsart, Arbeitszeit, Berufsqualifikation, Zeitarbeit)
- Änderungserkennung (`content_hash`, `change_history`): im Schema definiert, aber noch nicht aktiv genutzt
- Scraping läuft seriell – Parallelisierung sinnvoll

---

### 2.2 Location-Pipeline

**Vollständig implementiert** (Block 1, Tasks 1.1–2.8 ✅)

Dateien: `backend/app/location/`

| Komponente | Datei | Status |
|---|---|---|
| Adress-Parser | `parser.py` | ✅ |
| Geocoding-Client (Nominatim) | `geocoding.py` | ✅ |
| ÖPNV-Client (DB REST API) | `transit.py` | ✅ |
| Adress-Resolver (4-stufig) | `resolver.py` | ✅ |
| Pipeline-Orchestrator | `pipeline.py` | ✅ |
| DB-Modelle & Queries | `models.py` | ✅ |
| API-Endpoints | `backend/app/api/location.py` | ✅ |

**Hybrid-Score-Gewichtung** nach Arbeitsmodell (Full Remote → Onsite) ist implementiert.
**Privacy**: Heimatadresse wird nie in DB gespeichert, nur SHA256-Hash als Cache-Key.

---

### 2.3 Evaluierungs-Pipeline

**Vollständig implementiert** (Block 2, AP-01 bis AP-17 ✅)

Dateien: `backend/app/evaluator/`

| Komponente | Datei | AP | Status |
|---|---|---|---|
| DB-Modelle & Queries | `evaluator/models.py` | AP-01 | ✅ |
| Konfigurationserweiterung | `core/config.py` | AP-02 | ✅ |
| Ollama-Client | `ollama_client.py` | AP-03 | ✅ |
| Dokument-Parser | `document_parser.py` | AP-04 | ✅ |
| Kernprofil-Extraktion | `profile_extractor.py` | AP-05 | ✅ |
| Stage 1a (deterministischer Filter) | `stage1.py` | AP-06 | ✅ |
| Stage 1b (Ollama LLM-Filter) | `stage1.py` | AP-07 | ✅ |
| RAG-Pipeline (ChromaDB) | `rag.py` | AP-08 | ✅ |
| Stage 2 (Claude Tiefanalyse) | `stage2.py` | AP-09 | ✅ |
| Anthropic Batch API | `batch.py` | AP-10 | ✅ |
| Pipeline-Orchestrator | `pipeline.py` | AP-11 | ✅ |
| API-Endpoints | `api/evaluation.py` | AP-12 | ✅ |
| Feedback-Seed-Mechanismus | `feedback_seed.py` | AP-13 | ✅ |
| Migration 005 (evaluation_batches) | `db/migrations/` | AP-14 | ✅ |
| Ollama-Setup-Script | Skript | AP-15 | ✅ |
| E2E-Tests | `tests/integration/` | AP-16 | ✅ |
| Dokumentation & ADRs (008–010) | `docs/adr/` | AP-17 | ✅ |

**Evaluierungs-Flow:**
```
Neue Stelle
  → Stage 1a: Keyword-Ausschluss (deterministisch, kein LLM)
  → Stage 1b: Ollama LLM-Filter (binär: PASS / SKIP, mistral-nemo:12b)
  → Stage 2:  Claude Tiefanalyse (Score 1–10, 5 Dimensionen, claude-haiku-4-5)
```

**A/B-Strategie-Test** (`full_profile` | `structured_core` | `rag_hybrid`) ist eingebaut.

---

### 2.4 Anschreiben-Generator

**Nicht implementiert** – nur Stub-Dateien vorhanden:

| Datei | Inhalt | Status |
|---|---|---|
| `backend/app/writer/generator.py` | 1 Zeile (leer) | 🔲 |
| `backend/app/writer/latex.py` | 1 Zeile (leer) | 🔲 |
| `backend/app/api/cover_letters.py` | 5 Zeilen (Stub) | 🔲 |

**Geplante Architektur:**
- Stufe 1: Kontext-Aufbereitung (RAG-Chunks, Stil-Profil, Tonalitäts-Profil)
- Stufe 2: Generierung via Claude Sonnet → JSON-Absatz-Struktur
- Stufe 3: Qualitätsprüfung via Claude Haiku (Score + Hinweise)
- LaTeX-Export via Jinja2-Templates + `pdflatex`
- 3 Templates: privat, Behörde, Hochschule

**Fehlt komplett:**
- Stil-Extraktion aus Beispiel-Anschreiben
- Employer-Type-Klassifikation
- Absatz-Regenerierung mit Kontext-Hint
- LaTeX-Templates (`templates/` leer)

---

### 2.5 Dashboard / Frontend

**Vollständig implementiert** (Block 3, AP-18 bis AP-33 ✅)

#### Backend-APIs (neu, AP-18–AP-21)

| Komponente | Datei | AP | Status |
|---|---|---|---|
| Jobs API (Filter, Pagination, Feedback) | `api/jobs.py` | AP-18 | ✅ |
| Companies API | `api/companies.py` | AP-19 | ✅ |
| Clarification Queue API | `api/clarifications.py` | AP-20 | ✅ |
| Analytics Aggregation API | `api/analytics.py` | AP-21 | ✅ |

#### Frontend-Infrastruktur (AP-22–AP-24)

| Komponente | AP | Status |
|---|---|---|
| OpenAPI Types + API Client (TanStack Query) | AP-22 | ✅ |
| shadcn/ui Base Components (Button, Badge, Card, …) | AP-23 | ✅ |
| App Shell (React Router, Layout, Header) | AP-24 | ✅ |

#### Seiten (AP-25–AP-31)

| Seite | Datei | AP | Status |
|---|---|---|---|
| Übersicht / Daily View | `pages/uebersicht.tsx` | AP-25 | ✅ |
| Stellenliste (Table + Filters) | `pages/stellen.tsx` | AP-26 | ✅ |
| Job Detail Panel (Score-Breakdown, Recharts) | `components/jobs/job-detail-panel.tsx` | AP-27 | ✅ |
| Steuerung (Scraping je Quelle, Evaluation, Feedback) | `pages/steuerung.tsx` | AP-28 | ✅ |
| Klärungsbedarf-Drilldown | `pages/klaerungsbedarf.tsx` | AP-29 | ✅ |
| Analytics Charts (Funnel, Salary, Calibration, …) | `pages/analytics.tsx` | AP-30 | ✅ |
| Skill-Netzwerk (D3.js Force-Graph) | `components/analytics/skill-network.tsx` | AP-31 | ✅ |

**Weitere implementierte Features (AP-32–AP-33):**
- Polling (automatische Aktualisierung bei laufenden Scraping-Jobs)
- Optimistic Updates für Feedback-Aktionen
- Error Boundaries + Loading States
- Per-Source-Scraping-Steuerung mit Cancel-Support (`useScrapeRun`, `useCancelScrape`)
- **89 Tests** in 9 Testdateien, **81% Line Coverage** (Threshold: 60%) – alle TypeScript + ESLint-Checks bestehen
- ADR-011: Frontend-Architektur (React 18, Vite, TanStack Query, shadcn/ui, Recharts, D3.js)

---

### 2.6 Infrastruktur

| Komponente | Status |
|---|---|
| `docker-compose.yml` (Dev-Setup) | ✅ vorhanden |
| Backend-Dockerfile | ✅ vorhanden |
| GitHub Actions CI/CD | ✅ vorhanden |
| `docker-compose.prod.yml` | 🔲 nicht erstellt |
| LaTeX-Templates | 🔲 nicht erstellt |
| Cron-Job-Setup (Host) | 🔲 nicht eingerichtet |
| `config.example.yaml` | ✅ vorhanden |
| Docker Secrets (anthropic_key) | ✅ im Compose definiert |

---

## 3. Datenbankschema – Aktueller Stand

### Implementierte Tabellen (Migrationen 001–005)

| Tabelle | Beschreibung | Status |
|---|---|---|
| `jobs` | Stellenanzeigen (canonical_id, title, work_model, salary, …) | ✅ |
| `job_sources` | URL-Quellen pro Stelle (source_name, is_canonical, …) | ✅ |
| `companies` | Unternehmen mit Adresse, Geocoding-Koordinaten | ✅ |
| `transit_cache` | ÖPNV-Reisezeiten (company_id + origin_hash) | ✅ |
| `evaluations` | Evaluierungsergebnisse (stage1/2, score, strategy) | ✅ |
| `evaluation_batches` | Anthropic Batch API Tracking | ✅ |
| `feedback` | Nutzerentscheidungen (APPLY/MAYBE/IGNORE/SKIP) | ✅ |
| `preference_patterns` | Erkannte Präferenzmuster | ✅ |
| `scrape_runs` | Scraping-Log | ✅ |
| `clarification_queue` | Ungeklärte Adressen / Firmenwebsites | ✅ |

### Noch fehlende Tabellen (geplant, noch nicht migriert)

| Tabelle | Beschreibung | Abhängigkeit |
|---|---|---|
| `cover_letters` | Anschreiben (JSON-Absatz-Struktur, LaTeX-Export) | Anschreiben-Generator |
| `job_skills` | Skills pro Stelle (required / nice_to_have) | Analytics |
| `skill_trends` | Aggregierte Skill-Trends über Zeit | Analytics |
| `users` | Multi-User-Support | Grundsatzentscheidung |

### Bekannte Datenlücken (aus nächste_schritte.txt)

- Viele Jobs haben `raw_text = NULL` (Kimeta, Jooble, Adzuna, Stellenmarkt)
- `content_hash` und `change_history` sind im Schema vorhanden, aber nicht befüllt
- Fehlende Firmen-Informationen → viele `address_status = 'unknown'`
- Es fehlt eine systematische Analyse, welche Felder NULL oder leer sind

---

## 4. Offene Arbeiten

### Priorität 1: Datenbankanalyse (Grundlage für alles weitere)

- [ ] Welche Felder sind NULL / leer – und wie häufig?
- [ ] Können fehlende Felder aus doppelten Jobs imputiert werden?
- [ ] Welche fehlenden Felder brechen die Filter?
- [ ] Können fehlende Felder aus dem `raw_text` per LLM extrahiert werden?
- [ ] Welches Format brauchen aggregierte Informationen fürs Dashboard?

### Priorität 2: Kernprofil erstellen und Evaluierung live testen

- [ ] Kernprofil-JSON aus CV/Zeugnissen einmalig extrahieren (Profile Extractor ist fertig)
- [ ] Arbeitszeugnisse aufbereiten (dekodieren + narratives Stärkenprofil)
- [ ] RAG-Index befüllen (ChromaDB)
- [ ] Feedback-Seed-Einträge anlegen (5–8 Stück in `feedback_seed.yaml`)
- [ ] Ersten End-to-End-Lauf der Evaluierungs-Pipeline durchführen

### Priorität 3: Anschreiben-Generator

- [ ] Stil-Profil aus Beispiel-Anschreiben extrahieren
- [ ] `writer/generator.py` implementieren (3-stufige Pipeline)
- [ ] `writer/latex.py` implementieren (Jinja2 → pdflatex)
- [ ] LaTeX-Templates erstellen (`templates/`)
- [ ] `api/cover_letters.py` implementieren
- [ ] Migration für `cover_letters`-Tabelle

### Priorität 4: Dashboard ✅ Vollständig implementiert

Alle 5 Seiten + APIs implementiert (AP-18–AP-33). Siehe Abschnitt 2.5.

### Priorität 5: Scraping-Erweiterungen

- [ ] Kimeta: Position + Contract-Filter kombinieren
- [ ] Kimeta: Vollständige Contract-Kategorien implementieren (Vertragsart, Arbeitszeit, Berufsqualifikation)
- [ ] Änderungserkennung (`content_hash` befüllen, LLM-Diff bei Änderung)
- [ ] Parallelisierung der Scraper
- [ ] karriere.hessen.de, karriere.rlp.de, Indeed, XING, academics.de
- [ ] Typ-C-Scrapers (LLM-basiert für Behörden/Firmen)

### Priorität 6: Infrastruktur

- [ ] `docker-compose.prod.yml` erstellen (nginx, restart: always, feste Ollama-IP)
- [ ] Cron-Job auf dem Host einrichten
- [ ] Python 3.12 → 3.13 Upgrade planen (3.12 ist Security-Only)

---

## 5. Offene Grundsatzentscheidungen

Diese Entscheidungen beeinflussen die Architektur und sollten **vor** der Implementierung getroffen werden:

### 5.1 Multi-User-Support

Die Datenbankarchitektur für Multi-User ist definiert (ADR-007), aber noch nicht implementiert:
- Tabelle `users` (uuid, name, surname, folder)
- `evaluations`, `feedback`, `cover_letters`, `preference_patterns` erhalten `user_id`-FK
- Shared-Tabellen (`jobs`, `companies`, etc.) bleiben ohne `user_id`
- Default-User `00000000-…-000000000001` als Einzeluser-Fallback

**Entscheidung benötigt:** Direkt mit Multi-User-Support starten oder zuerst als Einzelnutzer und später migrieren?

### 5.2 LLM-Feld-Extraktion aus `raw_text`

Das erste LLM-Modell, das den Volltext sieht (Stage 1b oder Stage 2), könnte fehlende DB-Felder befüllen:
- Abfrage: welche Felder sind NULL für diesen Job?
- Prompt-Injektion: `"Fülle dieses JSON {missing_fields: None} aus dem Volltext"`

**Entscheidung benötigt:** In Stage 1b, Stage 2, oder als eigener Pre-Processing-Schritt?

### 5.3 Evaluierungs-Strategie

Drei Strategien laufen parallel im A/B-Test:
- `full_profile` (~25.000 Token, ~$0.031/Stelle)
- `structured_core` (~400 Token, ~$0.008/Stelle)
- `rag_hybrid` (~4.300 Token, ~$0.014/Stelle)

**Entscheidung benötigt:** Nach wie vielen Wochen/Stellen wird die A/B-Auswertung durchgeführt und eine Strategie festgelegt?

### 5.4 Prompt-Optimierung / Modell-Testing

**Frage:** Gibt es Frameworks für systematisches Prompt-Optimization?
Sinnvolle Metriken wären `score_delta` (Differenz Modell-Score vs. eigene Entscheidung).

### 5.5 Datenbankdokumentation

Laut nächste_schritte.txt fehlt noch:
- ADR für das Datenbankdesign als dediziertes Dokument mit Tabellen-Übersicht, Feldbeschreibungen, und Designentscheidungen
- Ein Script für strukturierte Datenbankanalyse (Feldvollständigkeit, Qualitätsbericht)

---

## 6. Tech-Stack-Handlungsbedarf

Aus dem Tech-Stack-Audit (März 2026), priorisiert nach Dringlichkeit:

### Kritisch (Sicherheit)
- **Ollama:** `OLLAMA_HOST=127.0.0.1` setzen – aktuell lauscht es auf `0.0.0.0:11434`
- **LiteLLM:** Nur als Library nutzen, nicht als Proxy-Server; oder durch direkte SDK-Nutzung ersetzen
- **GitHub Actions:** Alle Actions auf Commit-SHAs pinnen (nicht `@v4`-Tags)
- **Jinja2:** Auf 3.1.6 upgraden (CVE-2025-27516 Sandbox-Escape)

### Empfohlen
- **Python 3.12 → 3.13:** 3.12 ist Security-Only; 3.13 als konservativer nächster Schritt
- **React 18 → 19:** Ökosystem hat aufgeholt (Router v7, shadcn/ui, TanStack)
- **ESLint → Flat Config:** ESLint v10 hat Legacy-Format entfernt
- **Tailwind v3 → v4:** 5× schnellere Builds, CSS-first Konfiguration
- **mistral-nemo:12b → Qwen 2.5 14B:** Besser bei Reasoning/Coding für Stage 1b

---

## 7. Priorisierte nächste Schritte

```
1. Datenbankanalyse durchführen
   → Feldvollständigkeit, NULL-Analyse, Qualitätsbericht
   → Entscheidungsgrundlage für LLM-Feld-Extraktion

2. Kernprofil erstellen & erste Evaluierung live testen
   → Profile Extractor ist fertig, braucht Eingabedokumente
   → RAG-Index befüllen, Feedback-Seed anlegen
   → End-to-End-Lauf der Pipeline

3. GitHub-Stand aktualisieren
   → Schrittweise Commits für Block 3 (AP-18–AP-33)
   → Aktuellen Projektstand commiten

4. Kimeta-Scraper verbessern
   → Position + Contract kombinieren
   → Vollständige Contract-Filter implementieren

5. Anschreiben-Generator implementieren
   → Abhängig von: funktionierender Evaluierung + Kernprofil

6. Infrastruktur produktionsreif machen
   → docker-compose.prod.yml erstellen
   → Cron-Job auf dem Host einrichten
```

---

*Erstellt aus: `planning/00_overview.md`, `design_documents/job_agent_design.md`, `design_documents/teck_stack_audit_march_2026.md`, `nächste_schritte.txt`, `docs/adr/`, Analyse der Dateistruktur.*
*Aktualisiert am 29. März 2026: Block 3 Dashboard/Frontend (AP-18–AP-33) vollständig abgeschlossen.*
