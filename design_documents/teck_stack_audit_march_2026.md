# Tech-Stack-Audit: Python/React-Projekt, März 2026

Dieser Stack ist insgesamt solide und modern aufgebaut — die Kernentscheidungen (FastAPI, Pydantic v2, httpx, Vite, shadcn/ui, TanStack Query) gehören zu den besten Optionen im Ökosystem. Allerdings gibt es **mehrere sicherheitskritische Punkte**, die sofortiges Handeln erfordern: LiteLLM hat eine alarmierende CVE-Historie mit RCE- und SQL-Injection-Schwachstellen, Ollama bietet keinerlei eingebaute Authentifizierung, und die Playwright-Sandbox muss korrekt konfiguriert werden. Zusätzlich stehen wichtige Upgrades an — insbesondere React 18 → 19, Tailwind v3 → v4 und die ESLint-Flat-Config-Migration. Python 3.12 befindet sich bereits in der Security-Only-Phase und sollte auf 3.13 oder 3.14 aktualisiert werden.

---

## 1 · Kritische Probleme — sofort beheben

### LiteLLM: Zahlreiche schwere Sicherheitslücken

LiteLLM (aktuell stabil: **v1.81.14**) hat seit 2024 über **10 schwerwiegende CVEs** angesammelt — darunter Remote Code Execution (CVE-2024-6825), mehrere SQL-Injections (CVE-2024-5225, CVE-2024-4890, CVE-2025-45809), SSRF, Server-Side Template Injection und API-Key-Leakage. Die meisten betreffen die **Proxy-Server-Komponente**, nicht die Library-API.

**Sofortmaßnahmen:**
- LiteLLM **ausschließlich als Library** nutzen (`litellm.completion()`), niemals den Proxy-Server exponieren
- Auf die **neueste stabile Version pinnen** und mindestens monatlich updaten
- `pip-audit` in die CI-Pipeline integrieren, um neue CVEs sofort zu erkennen
- Ernsthaft prüfen, ob LiteLLM überhaupt nötig ist: Für nur zwei Provider (Ollama + Anthropic) ist **direkte SDK-Nutzung** (`anthropic` SDK + `ollama` Python-Paket) sicherer und weniger komplex

### Ollama: Keine Authentifizierung, kritische CVE-Historie

Ollama (aktuell: **v0.17.7**) bietet **keinerlei eingebaute Authentifizierung**. Standardmäßig lauscht es auf `0.0.0.0:11434` — jeder im Netzwerk hat vollen Zugriff. Dazu kommen kritische CVEs: RCE via Path Traversal (CVE-2024-37032 „Probllama"), RCE via manipulierte Modelldateien, und fehlende Auth für alle API-Endpoints (CVE-2025-63389).

**Sofortmaßnahmen:**
- `OLLAMA_HOST=127.0.0.1` setzen — zwingend nur Localhost-Binding
- Firewall-Regeln für Port 11434 einrichten
- Auf v0.17.7 aktualisieren (alle bekannten CVEs gefixt)
- Bei Netzwerk-Exposure einen Reverse-Proxy mit Authentifizierung vorschalten

### API-Keys: Docker-Secrets statt Umgebungsvariablen

Anthropic API-Keys in `environment:`-Direktiven im Docker-Compose-File sind über `docker inspect`, Prozess-Environment und Logs einsehbar.

**Sofortmaßnahmen:**
- Docker Compose `secrets:` mit dateibasierten Mounts (`/run/secrets/`) verwenden
- In GitHub Actions: **Environment Secrets** mit Reviewer-Approval nutzen, nicht Repository-Secrets
- `.env`-Dateien in `.gitignore` und `.dockerignore` aufnehmen
- `git-secrets` oder GitGuardian als Pre-Commit-Hook einrichten
- Langfristig: externen Secrets-Manager evaluieren (Vault, SOPS)

### Playwright: Sandbox aktivieren, nicht als Root

Ohne Sandbox kann eine bösartige Website bei Browser-Exploits aus dem Renderer-Prozess ausbrechen und auf Server-Dateien, Secrets und interne Dienste zugreifen.

**Sofortmaßnahmen:**
- Playwright **niemals als Root** ausführen — dedizierten `pwuser` im Dockerfile anlegen
- Chromium-Sandbox explizit aktivieren: `chromium.launch(chromium_sandbox=True)`
- Seccomp-Profil anwenden (`--security-opt seccomp=seccomp_profile.json`)
- Netzwerkisolation: interne IP-Ranges (169.254.0.0/16, 10.0.0.0/8, 172.16.0.0/12) blockieren
- URL-Whitelist implementieren — keine Navigierung zu beliebigen URLs ohne Validierung

### SearXNG: Nicht ins Internet exponieren

SearXNG (aktuell: **2026.3.10**) sollte bei internem Einsatz **niemals öffentlich erreichbar** sein. Sonst drohen Bot-Missbrauch, IP-Blacklisting durch Suchmaschinen und Reputationsschäden.

**Sofortmaßnahmen:**
- In Docker Compose auf internes Netzwerk beschränken, **keine Port-Mappings** zum Host
- `secret_key` auf einen starken Zufallswert setzen (nicht `"ultrasecretkey"`)
- `server.limiter = true` und `server.public_instance = false` in `settings.yml`
- Rate-Limiter mit Redis/Valkey aktivieren (ohne Redis funktioniert der Limiter nicht)

### Jinja2: CVE-2025-27516 — Template-Injection-Fix

Jinja2 3.1.5 und älter haben eine Sandbox-Escape-Schwachstelle über den `|attr`-Filter. **Sofort auf 3.1.6 upgraden.** Prüfen, ob irgendwo Nutzer-Input als Jinja2-Template gerendert wird — falls ja, `SandboxedEnvironment` nutzen.

### GitHub Actions: Supply-Chain-Angriffe 2025

2025 war ein katastrophales Jahr für GitHub-Actions-Sicherheit: **tj-actions/changed-files** wurde kompromittiert (CISA-gelistet), der Shai-Hulud-Wurm infizierte 20.000+ Repos, und GhostAction stahl 3.325 Secrets aus 817 Repos.

**Sofortmaßnahmen:**
- **Alle Actions auf vollständige Commit-SHAs pinnen** — niemals Tags wie `@v4` verwenden
- `permissions`-Key mit minimalen Rechten in jedem Workflow setzen
- Niemals `pull_request_target` mit `actions/checkout` des PR-Codes kombinieren
- Workflow-Dateien mit `zizmor` oder `actionlint` statisch analysieren

---

## 2 · Empfehlungen pro Komponente

### Backend-Stack

| Komponente | Im Einsatz | Aktuell stabil | Handlungsbedarf |
|---|---|---|---|
| **Python** | 3.12 | **3.14.0** (3.12 ist Security-Only) | Upgrade auf 3.13 oder 3.14 planen |
| **FastAPI** | ? | **0.135.x** | Upgraden; `strict_content_type` testen |
| **Pydantic** | v2 | **2.12.5** | Aktuell halten; V1-Shims vor Python 3.14 entfernen |
| **httpx** | ? | **0.28.1** | Aktuell halten; beste Wahl für FastAPI |
| **ruff** | ? | **0.15.5** | Aktuell halten; ersetzt Black+isort+Flake8 vollständig |
| **mypy** | ? | **1.19.1** | Weiternutzen; **ty** (Astral, Rust) als Alternative beobachten |
| **pytest** | ? | **9.0.x** | Upgrade auf v9; native TOML-Config nutzen |
| **respx** | ? | **0.22.0** (inaktiv) | ⚠️ Migration auf **pytest-httpx** empfohlen |
| **pytest-mock** | ? | **3.15.1** | Stabil; weiternutzen |
| **anthropic SDK** | ? | **0.84.0** | Aktuell halten; keine Sicherheitsprobleme |

**Python 3.12 → 3.13/3.14:** Python 3.12.13 (März 2026) erhält nur noch Sicherheits-Patches (Source-Only). Python 3.13 bietet free-threaded Mode (experimentell) und bessere Performance. Python 3.14 bringt Deferred Annotations (PEP 649) und Template-String-Literals. Empfehlung: **Python 3.13 als konservativer Schritt**, 3.14 für neue Projekte.

**respx → pytest-httpx:** respx wird als „inaktiv" eingestuft (kein Pull-Request-Aktivität). **pytest-httpx** (aktiv gewartet, unterstützt Python 3.10–3.14) bietet eine `httpx_mock`-Fixture und ist der empfohlene Ersatz.

### SQLite: WAL-Modus ist Pflicht, PostgreSQL-Migrationspfad vorbereiten

SQLite ist für **Single-Server, read-heavy Workloads** absolut vertretbar — aber nur mit korrekter Konfiguration. Der Engpass ist die **Single-Writer-Beschränkung**: nur eine Schreibtransaktion gleichzeitig.

**Erforderliche PRAGMAs:**
- `PRAGMA journal_mode=WAL;` — ermöglicht parallele Leser bei laufendem Schreibvorgang
- `PRAGMA busy_timeout=5000;` — mindestens 5 Sekunden Wartezeit statt sofortigem Fehler
- `PRAGMA synchronous=NORMAL;` — guter Kompromiss aus Speed und Durability im WAL-Modus
- `PRAGMA cache_size=-20000;` — ~160 MB Cache

**Migrationsschwelle zu PostgreSQL:** Mehr als **10 konkurrierende Schreiboperationen/Sekunde**, mehr als **100 gleichzeitige Nutzer**, oder **Multi-Server-Deployment**. Schreibtransaktionen müssen kurz gehalten werden — niemals LLM-Calls oder Netzwerkanfragen innerhalb einer Write-Transaction.

### ChromaDB: Backup-Strategie implementieren

ChromaDB (aktuell: **1.5.4**, Rust-Backend seit v1.0) speichert Daten in `chroma.sqlite3` plus HNSW-Index-Dateien pro Collection. Es gibt **kein eingebautes Backup/Restore-Tool**, und naives Kopieren während des Betriebs kann korrupte Backups erzeugen.

- Automatisierte Backups via SQLite `.backup`-Kommando oder Filesystem-Snapshots (LVM, ZFS)
- **Nie einfach `cp` im laufenden Betrieb** — SQLite-Konsistenz erfordert atomare Snapshots
- Die Fähigkeit beibehalten, ChromaDB aus Quelldokumenten komplett neu aufzubauen (Disaster Recovery)
- ChromaDB 1.0+ hat keine Abwärtskompatibilität bei Migrationen — vor Upgrades Daten sichern
- Alternativen: **LanceDB** für bessere Embedded-Performance, **pgvector** wenn PostgreSQL ohnehin geplant ist

### Lokale Modelle: Qwen 2.5 14B als Upgrade-Kandidat

| Modell | Status | Empfehlung |
|---|---|---|
| **mistral-nemo:12b** | Funktionsfähig, aber veraltet (Juli 2024) | **Qwen 2.5 14B** übertrifft es bei Reasoning/Coding |
| **nomic-embed-text** | V2 mit MoE-Architektur verfügbar | ✅ Exzellente Wahl; für Multilingual: bge-m3 |
| **llama3.1:8b** | Solide als Fallback | Llama 3.2 3B als leichtere Alternative testen |

**Mistral NeMo → Qwen 2.5 14B:** Im 10–14B-Parameterbereich ist Qwen 2.5 14B inzwischen die stärkere Wahl für Reasoning und Coding. Mistral Small 3 (24B) wäre ein deutliches Upgrade, falls die Hardware es erlaubt. Für die spezifischen Tasks (Stufe-1-Filter, Scraping-Extraktion, Adress-Extraktion) lohnt sich ein Benchmark-Vergleich.

### Cloud-Modelle: Aktuell und gut gewählt

**claude-haiku-4-5** ($1/$5 pro MTok) und **claude-sonnet-4-6** ($3/$15 pro MTok) sind beide aktuell. Sonnet 4.6 ist das **neueste Sonnet-Modell** (Februar 2026), wird von 70% der Entwickler gegenüber Sonnet 4.5 bevorzugt und bietet das beste Preis-Leistungs-Verhältnis. Haiku 4.5 ist optimal für hochvolumige Klassifikation und Routing. Batch-API bietet **50% Rabatt**, Prompt-Caching **90% Rabatt** auf Cache-Reads — beides evaluieren.

### Frontend-Stack

| Komponente | Im Einsatz | Aktuell stabil | Handlungsbedarf |
|---|---|---|---|
| **React** | 18 | **19.2.1** | ⚠️ Upgrade planen (s.u.) |
| **TypeScript** | ? | **5.9** (TS 7.0 in Go-Preview) | Auf 5.9 halten; TS 7.0 beobachten |
| **Vite** | ? | **7.3.1** (Vite 8 Beta mit Rolldown) | Auf 7.3.x upgraden |
| **Tailwind CSS** | ? (vermutlich v3) | **v4.x** | Upgrade planen (5× schneller) |
| **shadcn/ui** | ? | CLI v4 (März 2026) | Aktualisieren; Tailwind v4 Support |
| **TanStack Query** | v5 | **5.90.x** | ✅ Aktuell halten |
| **TanStack Table** | v8 | **8.21.3** | ✅ Stabil |
| **React Router** | ? | **v7.x** | Upgrade evaluieren (Remix-Merger) |
| **Recharts** | ? | **v3.8.0** | Upgrade auf v3 planen |
| **D3.js** | ? | **7.9.0** | ✅ Feature-complete, kein Upgrade nötig |
| **Vitest** | ? | **4.0.18** | Upgrade auf v4 (stable Browser Mode) |
| **ESLint** | ? | **10.0.3** | ⚠️ Flat-Config-Migration (s.u.) |
| **Prettier** | ? | **3.5.x** | Stabil; Biome als Alternative evaluieren |
| **openapi-typescript** | ? | **7.13.0** | ✅ Beste Option; `openapi-fetch` evaluieren |

### React 18 → 19: Das wichtigste Frontend-Upgrade

React 19 ist seit Dezember 2024 stabil, und das Ökosystem (React Router v7, shadcn/ui, TanStack) hat vollständig aufgeholt. **React 18.3.1 war das letzte React-18-Release** (April 2024) und erhält keine neuen Features mehr.

Wichtige React-19-Features: Actions API, `use()`-Hook, React Compiler (stable seit Oktober 2025, eliminiert manuelles `useMemo`/`useCallback`), `<Activity>`-Komponente. Breaking Changes: `ReactDOM.render` entfernt (auf `createRoot` umstellen), String-Refs und `defaultProps` auf Funktionskomponenten entfernt. Migration mit `react-codemod` automatisierbar.

**Hinweis:** Falls React Server Components genutzt werden, gab es eine **RCE-Schwachstelle** — gefixt in 19.0.1, 19.1.2 und 19.2.1. Bei reinem Client-Side-Rendering nicht relevant.

### ESLint: Flat-Config-Migration ist überfällig

ESLint v10.0.0 (Februar 2026) hat das Legacy-`.eslintrc`-Format **vollständig entfernt**. Nur noch `eslint.config.js` (Flat Config) wird unterstützt. Die Migration ist mit dem **Configuration Migrator** automatisierbar. `defineConfig` und `extends` erleichtern die Konfiguration. Alle großen Plugins unterstützen inzwischen Flat Config.

**Biome als Alternative zu ESLint + Prettier:** Biome ist **10–25× schneller** (Rust-basiert), vereint Linting und Formatting in einem Tool, und deckt 97%+ der Prettier-Formatierung sowie 80%+ der ESLint-Regeln ab. Limitierungen: kein GraphQL/Vue-Template-Support, JSON-only Config, kleineres Plugin-Ökosystem. Für bestehende Projekte mit komplexer ESLint-Config: bei ESLint + Prettier bleiben. Für neue Projekte: Biome ernsthaft evaluieren.

### Tailwind v4: Deutliches Performance-Upgrade

Tailwind v4 (Januar 2025) bringt **5× schnellere Full-Builds und 100×+ schnellere Incremental-Builds**. Die Konfiguration erfolgt nun CSS-first via `@theme`-Direktive statt `tailwind.config.js`. Automatische Content-Detection eliminiert das `content`-Array. Ein automatisiertes Upgrade-Tool existiert. shadcn/ui unterstützt Tailwind v4 seit Februar 2025.

---

## 3 · Was gut ist und bleiben kann

**FastAPI + Pydantic v2 + httpx** bilden das beste Python-API-Stack-Trio in 2026. FastAPI ist de-facto Standard für async Python APIs, Pydantic v2 ist konkurrenzlos bei Datenvalidierung, und httpx ist der ideale HTTP-Client (sync + async, HTTP/2, perfekte FastAPI-Testintegration via `ASGITransport`). Keine Änderungen nötig.

**ruff** hat Black, isort, Flake8 und diverse andere Tools vollständig ersetzt. Mit **0.15.5** ist es das schnellste und umfassendste Linting/Formatting-Tool im Python-Ökosystem. Die Kombination mit pre-commit via `ruff-pre-commit` ist vorbildlich. Astrals neuer Type-Checker **ty** (Rust, 10–60× schneller als mypy) ist in Beta — sobald stabil, könnte er mypy ablösen.

**TanStack Query v5** bleibt die dominante Lösung für Server-State-Management in React mit über **17 Millionen** wöchentlichen npm-Downloads. TanStack Table v8 ist das beste Headless-Table-Library und integriert sich nahtlos mit shadcn/ui. Kein Migrationsbedarf.

**shadcn/ui + Tailwind CSS** ist der richtige Ansatz für komponentenbasiertes UI. shadcn/ui ist 2026 mit CLI v4, fünf Design-Styles, Base-UI-Support und MCP-Integration für AI-Coding-Agents aktiver denn je. Das Copy-Paste-Modell vermeidet Dependency-Lock-in.

**Vitest + Testing Library** ist die Standardkombination für Vite-basierte Projekte. Vitest v4 bringt stabilen Browser-Mode via Playwright — Angular 21 hat Vitest sogar als Default-Testrunner gewählt und Jest damit abgelöst. Upgrade auf v4 empfohlen, aber kein dringender Handlungsbedarf.

**openapi-typescript** (v7.13.0) bleibt der beste Ansatz für Typ-Generierung aus OpenAPI-Schemas — Zero Runtime Cost, aktiv gewartet. Ergänzend lohnt sich ein Blick auf **openapi-fetch** (2 KB typesafe Fetch-Wrapper) und **@hey-api/openapi-ts** für vollständige SDK-Generierung mit TanStack-Query-Hooks.

**Docker Compose + GitHub Actions + pre-commit** ist ein solides CI/CD-Setup. Compose V2 nutzen, Health-Checks für alle Services, `depends_on` mit `condition: service_healthy`. Pre-commit mit Ruff-Hooks ist die effizienteste Konfiguration.

**Recharts + D3.js** ist eine sinnvolle Aufteilung: Recharts v3 für Standard-Charts (aktiv gewartet, 62 Mio. monatliche Downloads), D3.js v7.9 für komplexe Custom-Visualisierungen. D3 gilt als feature-complete; kein Upgrade-Druck.

**nomic-embed-text** bleibt eine exzellente Wahl für lokale RAG-Embeddings via Ollama. V2 mit MoE-Architektur bietet **86,2% Top-5-Accuracy** auf BEIR. Für multilinguale Anforderungen wäre bge-m3 besser, aber für den beschriebenen Use-Case ist nomic-embed-text optimal.

---

## Fazit: Priorisierte Handlungsübersicht

Der Stack ist architektonisch gut konzipiert. Die drei **dringendsten Maßnahmen** sind: (1) LiteLLM-Sicherheit evaluieren und auf Library-Only beschränken oder durch direkte SDK-Nutzung ersetzen, (2) Ollama auf Localhost binden und Netzwerkzugriff absichern, (3) Docker-Secrets für API-Keys und Non-Root-Container durchsetzen. Auf der Upgrade-Seite sind React 19, ESLint Flat Config und Tailwind v4 die wirkungsvollsten Verbesserungen. Python 3.12 sollte vor dem Ende des Bugfix-Supports auf mindestens 3.13 aktualisiert werden. Die Grundentscheidungen — FastAPI, Pydantic, httpx, Vite, shadcn/ui, TanStack — sind erstklassig und zukunftssicher.