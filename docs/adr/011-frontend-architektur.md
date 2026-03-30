# ADR-011: Frontend-Architektur

## Status
Accepted (2026-03-28)

## Kontext
Das Dashboard benötigt eine React-Architektur für 5 Seiten mit Echtzeit-Daten,
Server-Side Pagination und interaktiven Visualisierungen (Recharts, D3.js).

## Entscheidungen

### Kein globaler State Manager
TanStack Query verwaltet allen Server-State. Lokaler UI-State (Selected Job,
Filter, Panel open/closed) bleibt in React useState. Redux/Zustand wäre
Overhead für ein Dashboard ohne komplexen Client-State.

### Fetch-Wrapper statt generiertem SDK
openapi-typescript generiert Types aus dem FastAPI-Schema. Ein dünner
fetch()-Wrapper (api-client.ts) nutzt diese Types. Kein codegen-Client
(openapi-fetch, orval) — hält das Bundle klein (~1KB vs ~15KB+) und ist
einfacher zu debuggen.

### Server-Side Filtering + URL-synced Params
Die Job-Liste kann tausende Einträge haben. Alle Filter und Pagination werden
als Query-Params an die API gesendet. Filter sind in URL Search Params
gespeichert → bookmarkbar, Browser-Back funktioniert.

### D3.js via useRef
D3 und React wollen beide das DOM kontrollieren. Lösung: React rendert einen
SVG-Container, D3 manipuliert die SVG-Inhalte via useRef + useEffect. Die
Force-Simulation wird bei unmount gestoppt.

### Code-Splitting per Seite
Jede Seite ist ein React.lazy()-Import. Analytics mit D3 (~200KB) wird erst
bei Navigation geladen.

### shadcn/ui ohne Radix
Komponenten folgen dem shadcn/ui-Pattern (cva + cn), nutzen aber native
HTML-Elemente statt Radix Primitives. Spart ~50KB Bundle-Größe.

## Konsequenzen
- Kein Offline-Support (Server-State-first)
- Filter-Reset bei Seiten-Refresh (beabsichtigt — URL-Params bleiben)
- D3-Code ist imperativer als der Rest — akzeptabler Trade-off für die
  Force-Simulation
