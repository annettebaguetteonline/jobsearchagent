# ADR-007: Datenbankdesign

**Status:** Accepted
**Stand:** März 2026

---

## Kontext

### Technologiewahl: SQLite

SQLite wurde als einzige relationale Datenbank gewählt:

- **Kein separater Service** — die DB ist eine einzelne Datei (`data/jobs.db`), kein Datenbankserver nötig
- **Portabel** — Backup ist ein `cp`-Befehl, Migration auf einen Heimserver ist trivial
- **WAL-Modus** (`PRAGMA journal_mode=WAL`) erlaubt gleichzeitige Reads während eines Writes — ausreichend für diesen Single-User-Use-Case
- **Ausreichende Performance** — bei erwartetem Datenvolumen (~10.000–100.000 Jobs) keine Engpässe

### Kein ORM

Bewusste Entscheidung gegen SQLAlchemy oder ähnliche ORMs:

- Das Schema ist stabil und komplex genug, dass rohe SQL-Kontrolle Vorteile hat
- ORM-Overhead und Mapping-Komplexität nicht gerechtfertigt für diesen Use Case
- Pydantic-Modelle übernehmen die Validierung und Serialisierung

### aiosqlite

`aiosqlite` wraps SQLite für asyncio — notwendig da FastAPI async ist und Blocking-I/O den Event Loop blockieren würde. `row_factory = aiosqlite.Row` gibt dict-artige Zugriffe auf Zeilen.

---

## Migrations-System

Implementiert in `backend/app/db/database.py`:

```
_migrations/           Tabelle in der DB — trackt angewandte Migrationen
                       (filename TEXT PRIMARY KEY, applied_at TEXT)

migrations/
  001_initial_schema.sql   → vollständiges Basis-Schema
  002_source_job_id_and_sector.sql → Ergänzungen
  003_multi_user.sql       → geplant (Block 3)
```

**Ablauf bei `init_db()`:**
1. `_migrations`-Tabelle anlegen (falls nicht vorhanden)
2. Alle `.sql`-Dateien im `migrations/`-Verzeichnis **alphabetisch sortiert** durchlaufen
3. Pro Datei: prüfen ob bereits in `_migrations` eingetragen → wenn ja: überspringen
4. SQL ausführen → Dateiname in `_migrations` eintragen

**Idempotent:** `init_db()` kann beliebig oft aufgerufen werden — bereits angewandte Migrationen werden übersprungen.

---

## ER-Diagramm

```
companies (1) ──────────────────────────── jobs (N)
    │                                        │
    │  transit_cache (N)                     │
    └──────────────────                      │
                                             │
                              job_sources (N)┘
                              (UNIQUE url)

jobs (1) ──── evaluations (1)   [1:1, noch nicht befüllt]
jobs (1) ──── feedback (N)      [1:N, noch nicht befüllt]
jobs (1) ──── cover_letters (N) [1:N, noch nicht befüllt]
jobs (1) ──── job_skills (N)    [1:N]

scrape_runs                     [eigenständig, kein FK]
clarification_queue             [entity_id → jobs oder companies, soft-FK]
skill_trends                    [eigenständig, aggregiert]
preference_patterns             [eigenständig]
```

**Foreign Keys sind aktiviert** (`PRAGMA foreign_keys=ON` in jeder Verbindung).

---

## Tabellen-Referenz

### `companies` (Migration 001)

Zentrale Firmendatenbank — wird bei jedem Scrape-Durchlauf befüllt.

| Spalte | Typ | Constraint | Beschreibung |
|--------|-----|-----------|-------------|
| `id` | INTEGER | PK | Auto-Increment |
| `name` | TEXT | NOT NULL | Originalname |
| `name_normalized` | TEXT | NOT NULL | Lowercase, normalisiert (für Dedup) |
| `name_aliases` | TEXT | | JSON-Array alternativer Namen |
| `address_street` | TEXT | | Straße (nach Adressrecherche) |
| `address_city` | TEXT | | Stadt |
| `address_zip` | TEXT | | PLZ |
| `lat` | REAL | | Breitengrad (nach Geocoding) |
| `lng` | REAL | | Längengrad |
| `address_status` | TEXT | DEFAULT 'unknown' | `unknown`\|`found`\|`failed` |
| `address_source` | TEXT | | `db`\|`impressum`\|`searxng`\|`nominatim` |
| `agent_findings` | TEXT | | JSON: Zwischenergebnisse der Adressrecherche |
| `remote_policy` | TEXT | DEFAULT 'unknown' | `unknown`\|`remote`\|`hybrid`\|`onsite` |
| `careers_url` | TEXT | | Karriereseite des Unternehmens |
| `ats_system` | TEXT | | `lever`\|`greenhouse`\|`personio`\|`softgarden`\|… |
| `created_at` | TEXT | NOT NULL | ISO-8601 UTC |
| `updated_at` | TEXT | NOT NULL | ISO-8601 UTC |

---

### `transit_cache` (Migration 001)

ÖPNV-Reisezeiten-Cache. Die Heimatadresse wird **nie im Klartext** gespeichert.

| Spalte | Typ | Constraint | Beschreibung |
|--------|-----|-----------|-------------|
| `company_id` | INTEGER | FK → companies | |
| `origin_hash` | TEXT | NOT NULL | SHA256 der Heimatadresse |
| `transit_minutes` | INTEGER | NOT NULL | Fahrzeit in Minuten |
| `api_used` | TEXT | | `db_rest`\|`transport_rest` |
| `cached_at` | TEXT | NOT NULL | ISO-8601 UTC |
| `expires_at` | TEXT | NOT NULL | ISO-8601 UTC (TTL: 90 Tage) |
| | | UNIQUE(company_id, origin_hash) | |

---

### `jobs` (Migration 001 + 002)

Kernentität. Jeder deduplizierte Job erscheint genau einmal.

| Spalte | Typ | Constraint | Beschreibung |
|--------|-----|-----------|-------------|
| `id` | INTEGER | PK | Auto-Increment |
| `canonical_id` | TEXT | UNIQUE NOT NULL | SHA256(norm_title\|norm_company\|norm_ort_ohne_PLZ) |
| `title` | TEXT | NOT NULL | Stellenbezeichnung (Original) |
| `company_id` | INTEGER | FK → companies | |
| `location_raw` | TEXT | | Ortsangabe im Original-Format |
| `location_status` | TEXT | DEFAULT 'unknown' | `unknown`\|`resolved`\|`failed` |
| `work_model` | TEXT | | `remote`\|`hybrid`\|`onsite`\|`unknown` |
| `hybrid_days_hint` | INTEGER | | Tage/Woche vor Ort (falls bekannt) |
| `salary_raw` | TEXT | | Gehaltsangabe im Original-Format |
| `salary_min` | INTEGER | | Untere Gehaltsgrenze (normalisiert) |
| `salary_max` | INTEGER | | Obere Gehaltsgrenze (normalisiert) |
| `deadline` | TEXT | | Bewerbungsfrist (ISO-8601) |
| `first_seen_at` | TEXT | NOT NULL | ISO-8601 UTC |
| `last_seen_at` | TEXT | NOT NULL | ISO-8601 UTC — aktualisiert bei Duplikat-Treffer |
| `status` | TEXT | DEFAULT 'new' | `new`\|`reviewed`\|`applying`\|`applied`\|`interview`\|`offer`\|`rejected`\|`expired`\|`ignored` |
| `is_active` | INTEGER | DEFAULT 1 | Boolean (1/0); Soft Delete |
| `content_hash` | TEXT | | SHA256 des Inhalts für Änderungserkennung |
| `raw_text` | TEXT | | Volltext der Stellenanzeige |
| `change_history` | TEXT | | JSON-Array von Änderungen |
| `created_at` | TEXT | NOT NULL | ISO-8601 UTC |
| `updated_at` | TEXT | NOT NULL | ISO-8601 UTC |
| `sector` | TEXT | | `public`\|`private`\|NULL — **Migration 002** |

---

### `job_sources` (Migration 001 + 002)

Jede URL unter der ein Job gefunden wurde. Ein Job kann mehrere Quellen haben (aggregatorübergreifend).

| Spalte | Typ | Constraint | Beschreibung |
|--------|-----|-----------|-------------|
| `id` | INTEGER | PK | Auto-Increment |
| `job_id` | INTEGER | FK → jobs NOT NULL | |
| `url` | TEXT | UNIQUE NOT NULL | Quell-URL |
| `source_name` | TEXT | NOT NULL | `service_bund`\|`interamt`\|`kimeta`\|… |
| `source_type` | TEXT | NOT NULL | `aggregator`\|`portal`\|`direct`\|`ats` |
| `is_canonical` | INTEGER | DEFAULT 0 | Boolean: kanonische URL des Jobs |
| `first_seen_at` | TEXT | NOT NULL | ISO-8601 UTC |
| `last_seen_at` | TEXT | NOT NULL | ISO-8601 UTC |
| `last_checked_at` | TEXT | | ISO-8601 UTC |
| `is_available` | INTEGER | | Boolean, NULL = unbekannt |
| `content_hash` | TEXT | | Für Änderungserkennung pro Quelle |
| `source_job_id` | TEXT | | Quell-native Job-ID für Stage-0-Dedup — **Migration 002** |

---

### `evaluations` (Migration 001)

Noch nicht befüllt — Evaluierungs-Pipeline ist ausstehend.

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `id` | INTEGER PK | |
| `job_id` | INTEGER UNIQUE FK → jobs | Aktuell 1:1 — wird in Migration 003 zu (job_id, user_id) UNIQUE |
| `eval_strategy` | TEXT | `full_profile`\|`structured_core`\|`rag_hybrid` |
| `stage1_pass` | INTEGER | Boolean: Ollama-Vorfilter |
| `stage1_reason` | TEXT | Begründung |
| `stage1_model` | TEXT | Verwendetes Ollama-Modell |
| `stage1_ms` | INTEGER | Latenz in ms |
| `stage2_score` | REAL | 1.0–10.0 |
| `stage2_score_breakdown` | TEXT | JSON: {skills, level, domain, location, potential} |
| `stage2_recommendation` | TEXT | `APPLY`\|`MAYBE`\|`SKIP` |
| `stage2_match_reasons` | TEXT | JSON-Array |
| `stage2_missing_skills` | TEXT | JSON-Array |
| `stage2_salary_estimate` | TEXT | |
| `stage2_summary` | TEXT | |
| `stage2_application_tips` | TEXT | JSON-Array |
| `stage2_model` | TEXT | Verwendetes Claude-Modell |
| `stage2_tokens_used` | INTEGER | |
| `stage2_ms` | INTEGER | |
| `location_score` | REAL | |
| `location_effective_minutes` | INTEGER | |
| `evaluated_at` | TEXT | ISO-8601 UTC |
| `profile_version` | TEXT | Hash des Kernprofils zum Evaluierungszeitpunkt |
| `needs_reevaluation` | INTEGER | Boolean DEFAULT 0 |

---

### `feedback` (Migration 001)

Noch nicht befüllt.

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `id` | INTEGER PK | |
| `job_id` | INTEGER FK → jobs | |
| `decision` | TEXT NOT NULL | `APPLY`\|`MAYBE`\|`IGNORE`\|`SKIP` |
| `reasoning` | TEXT | Privat — wird beim Export entfernt |
| `model_score` | REAL | |
| `model_recommendation` | TEXT | |
| `score_delta` | REAL | decision_score − model_score |
| `job_snapshot` | TEXT | JSON (anonymisiert exportierbar) |
| `model_reasoning_snapshot` | TEXT | |
| `decided_at` | TEXT | ISO-8601 UTC |
| `feedback_version` | INTEGER | |
| `is_seed` | INTEGER | Boolean DEFAULT 0 |

---

### `preference_patterns` (Migration 001)

Noch nicht befüllt.

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `id` | INTEGER PK | |
| `pattern_type` | TEXT NOT NULL | `avoid_keyword`\|`prefer_size`\|… |
| `pattern_key` | TEXT NOT NULL | |
| `pattern_value` | TEXT | |
| `confidence` | REAL | |
| `sample_count` | INTEGER | |
| `last_updated` | TEXT | ISO-8601 UTC |
| `is_active` | INTEGER | Boolean DEFAULT 1 |

---

### `cover_letters` (Migration 001)

Noch nicht befüllt.

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `id` | INTEGER PK | |
| `job_id` | INTEGER FK → jobs | |
| `version` | INTEGER | DEFAULT 1 |
| `subject` | TEXT | |
| `salutation` | TEXT | |
| `body` | TEXT NOT NULL | JSON mit Absätzen (strukturiert, nicht Fließtext) |
| `closing` | TEXT | |
| `model_used` | TEXT | |
| `tokens_used` | INTEGER | |
| `profile_version` | TEXT | |
| `rag_chunks_used` | TEXT | JSON-Array |
| `feedback_examples_used` | INTEGER | |
| `quality_score` | REAL | |
| `quality_feedback` | TEXT | JSON: Verbesserungshinweise |
| `is_sent` | INTEGER | Boolean DEFAULT 0 |
| `sent_at` | TEXT | ISO-8601 UTC |
| `notes` | TEXT | |
| `created_at` | TEXT | ISO-8601 UTC |
| `is_active` | INTEGER | Boolean DEFAULT 1 |

---

### `job_skills` (Migration 001)

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `job_id` | INTEGER FK → jobs | |
| `skill` | TEXT NOT NULL | |
| `skill_type` | TEXT | `required`\|`nice_to_have`\|`mentioned` |
| `confidence` | REAL | |
| | PRIMARY KEY (job_id, skill) | |

---

### `skill_trends` (Migration 001)

Aggregierte Skill-Häufigkeiten pro Zeitraum.

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `skill` | TEXT NOT NULL | |
| `period_start` | TEXT NOT NULL | ISO-8601 Wochen-/Monatsanfang |
| `job_count` | INTEGER | |
| `avg_salary_min` | INTEGER | |
| `source_mix` | TEXT | JSON: {stepstone: 5, kimeta: 12} |
| | PRIMARY KEY (skill, period_start) | |

---

### `scrape_runs` (Migration 001)

Log jedes Scraping-Durchlaufs.

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `id` | INTEGER PK | |
| `started_at` | TEXT NOT NULL | ISO-8601 UTC |
| `finished_at` | TEXT | ISO-8601 UTC |
| `status` | TEXT | `running`\|`finished`\|`failed` |
| `sources_run` | TEXT | JSON-Array: ["service_bund", "kimeta", …] |
| `stats` | TEXT | JSON: {fetched, new, duplicate, skipped, errors, expired} |
| `error_log` | TEXT | JSON-Array von Fehlermeldungen |

---

### `clarification_queue` (Migration 001)

Offene Klärungsbedarfe (unbekannte Adressen, fehlende Websites, etc.).

| Spalte | Typ | Beschreibung |
|--------|-----|-------------|
| `id` | INTEGER PK | |
| `entity_type` | TEXT NOT NULL | `job`\|`company` |
| `entity_id` | INTEGER NOT NULL | Soft-FK (kein harter Constraint) |
| `issue_type` | TEXT NOT NULL | `address_unknown`\|`website_unknown`\|`salary_parse`\|… |
| `priority` | TEXT | `high`\|`normal`\|`low` DEFAULT 'normal' |
| `severity` | TEXT | `red`\|`yellow` DEFAULT 'yellow' |
| `attempts` | TEXT | JSON-Array: [{stage, tried_at, result}] |
| `last_attempt_at` | TEXT | ISO-8601 UTC |
| `resolved` | INTEGER | Boolean DEFAULT 0 |
| `resolved_at` | TEXT | ISO-8601 UTC |
| `resolved_by` | TEXT | `manual`\|`stage4_llm`\|`auto` |
| `resolution_note` | TEXT | |
| `created_at` | TEXT | ISO-8601 UTC |

---

## Designprinzipien

### Soft Deletes
Nichts wird physisch gelöscht. `is_active = 0` markiert inaktive Einträge. Jobs behalten ihren Status-Wert (`expired`, `ignored`) zusätzlich zu `is_active`.

### JSON für volatile Strukturen
Felder wie `change_history`, `agent_findings`, `score_breakdown`, `attempts` werden als JSON-Text gespeichert. Vorteil: Schema-Erweiterungen ohne Migration. Nachteil: keine SQL-Filterung auf JSON-Inhalte ohne json_extract().

### Anonymisierung by Design
- Die Heimatadresse des Nutzers wird **niemals** gespeichert — nur ihr SHA256-Hash als `origin_hash` in `transit_cache`
- Persönliche Begründungen in `feedback.reasoning` werden beim anonymisierten Export entfernt
- `job_snapshot` in `feedback` ist für anonymisierten Community-Export konzipiert (Firmennamen durch Branchenkategorie ersetzt)

### profile_version
`evaluations.profile_version` und `cover_letters.profile_version` speichern den SHA256-Hash des Kernprofils zum Zeitpunkt der Evaluierung/Generierung. Wenn sich das Profil ändert, können veraltete Einträge über `needs_reevaluation = 1` identifiziert werden.

### TEXT für Timestamps
Alle Zeitstempel werden als ISO-8601 UTC Strings gespeichert (`2026-03-16T07:00:00Z`), nicht als SQLite `DATETIME`. Vorteile: explizit, portabel, keine SQLite-spezifischen Datums-Funktionen nötig.

### INTEGER für Boolean
SQLite kennt keinen Boolean-Typ. Alle Boolean-Felder verwenden `INTEGER` (0/1). Pydantic-Modelle konvertieren automatisch.

---

## Indizes

```sql
-- jobs
idx_jobs_status       ON jobs(status)          -- Dashboard-Filter nach Status
idx_jobs_canonical    ON jobs(canonical_id)     -- Stage-1-Dedup
idx_jobs_company      ON jobs(company_id)       -- Stage-2-Dedup (Fuzzy nach Firma)
idx_jobs_deadline     ON jobs(deadline)         -- mark_expired_jobs()

-- evaluations
idx_eval_score        ON evaluations(stage2_score)      -- Sortierung im Dashboard
idx_eval_strategy     ON evaluations(eval_strategy)     -- A/B-Test-Auswertung
idx_eval_profile      ON evaluations(profile_version)   -- Re-Evaluierung nach Profiländerung

-- feedback
idx_feedback_decision ON feedback(decision)    -- Feedback-Analyse
idx_feedback_delta    ON feedback(score_delta) -- Modell-Kalibrierung

-- clarification_queue
idx_clarif_open       ON clarification_queue(resolved, priority)

-- companies
idx_companies_name    ON companies(name_normalized)   -- Company-Lookup bei Dedup

-- transit_cache
idx_transit_company   ON transit_cache(company_id, origin_hash)

-- job_sources (Migration 002)
idx_job_sources_source_job_id
    ON job_sources(source_name, source_job_id)
    WHERE source_job_id IS NOT NULL             -- Stage-0-Dedup
```

---

## Bekannte Lücken und geplante Erweiterungen

### Multi-User-Support (Migration 003 — ausstehend)

Aktuell ist die Datenbank für einen einzelnen Nutzer ausgelegt. Geplante Änderungen in Migration 003:

- Neue Tabelle `users` (UUID PK, name, profile_json, profile_version, folder)
- `ALTER TABLE evaluations ADD COLUMN user_id TEXT REFERENCES users(id)`
  - UNIQUE-Constraint von `(job_id)` auf `(job_id, user_id)` ändern (erfordert Tabellen-Neuerstellung wegen SQLite-Limitation)
- `ALTER TABLE feedback ADD COLUMN user_id TEXT REFERENCES users(id)`
- `ALTER TABLE cover_letters ADD COLUMN user_id TEXT REFERENCES users(id)`
- `ALTER TABLE preference_patterns ADD COLUMN user_id TEXT REFERENCES users(id)`

Tabellen ohne User-Kontext (geteilte Daten): `jobs`, `companies`, `job_sources`, `transit_cache`, `scrape_runs`, `clarification_queue`, `job_skills`, `skill_trends`.

### Evaluierungs-Pipeline (implementiert, März 2026)
`evaluations`, `feedback`, `job_skills` werden durch die Evaluierungs-Pipeline befüllt (AP-01–AP-17).
`cover_letters`, `preference_patterns`, `skill_trends` sind im Schema vorhanden, aber noch nicht befüllt.

---

### Datenlage-Status (März 2026)

Analysierbar mit `scripts/data_quality_report.py --verbose`.

**Bekannte Datenlücken (qualitativ):**
- `raw_text = NULL`: Kimeta, Jooble, Adzuna, Stellenmarkt liefern keinen Volltext (kein Detail-Fetching implementiert)
- `content_hash`: Im Schema vorhanden, aber nicht befüllt (Änderungserkennung inaktiv)
- `change_history`: Im Schema vorhanden, aber nicht befüllt
- `work_model = NULL`: Jobs ohne explizite Homeoffice-Angabe im Scraper-Output
- `companies.address_status = 'unknown'`: Viele Firmen noch nicht geocoded

**Imputation aus Duplikaten:**
Für Jobs die von mehreren Scrapern gefunden wurden (`job_sources.job_id` mit mehreren Einträgen)
können fehlende Felder ggf. durch erneutes Scraping einer anderen Quelle befüllt werden.
Das `data_quality_report.py`-Script quantifiziert dieses Potenzial pro Feld.

**LLM-Feldextraktion (Entscheidung ausstehend):**
Für Jobs mit vorhandenem `raw_text` könnten fehlende Felder (`work_model`, `salary_raw`,
`location_raw`) per LLM aus dem Volltext extrahiert werden. Timing-Entscheidung:
Stage 1b (Ollama), Stage 2 (Claude), oder eigenständiger Pre-Processing-Schritt.
Implementierungsstrategie: Abfrage der NULL-Felder pro Job → Prompt-Injektion
`"Fülle dieses JSON {missing_fields: None} aus dem Volltext"`.

**Filter-Impact:**
Jobs ohne `raw_text` können Stage 1b (Ollama LLM-Filter) nicht durchlaufen.
Jobs ohne Firmen-Koordinaten erhalten keinen Pendel-Score in Stage 2.
Das `filter_impact`-Feld im Quality-Report quantifiziert diese Auswirkungen.
