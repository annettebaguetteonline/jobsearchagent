# ADR-006: Kimeta Multi-Stage-Suche mit HTML-basierten Filtern

**Status:** Accepted
**Stand:** März 2026

---

## Kontext

Kimeta.de begrenzt Suchergebnisse auf maximal 15 Seiten (~225 Jobs) pro Suche. Bei einem Suchradius von z. B. 50 km um Frankfurt sind aber weit mehr als 225 Jobs relevant. Eine einzelne Suche ohne Keyword liefert deshalb nur einen Bruchteil aller verfügbaren Stellen.

Kimeta bietet über Filterkategorien (`&cat=position`, `&cat=contract`) sogenannte Positions- und Beschäftigungsart-Filter an. Diese Filter stehen als pf-URL-Parameter (`pf=position@Consultant (m/w/d)`) zur Verfügung und ermöglichen es, die Suche auf spezifische Teilmengen einzuschränken — und so das 15-Seiten-Limit pro Filter-Kombination zu umgehen.

---

## Entscheidung

### HTML-basierte Filter-Extraktion

Filter-Werte (pf-Parameter) werden aus dem rohen HTML der Suchergebnisseite extrahiert — nicht aus der Next.js-Datenstruktur (`__NEXT_DATA__` / PPA).

**Begründung:** Der Endpunkt `/search?loc=` befüllt die Keys `positions`/`areas` im PPA nicht (diese erscheinen nur auf standortspezifischen Seiten wie `/stellenangebote-frankfurt`). Das Filter-HTML ist jedoch immer verfügbar: `<a rel="nofollow" class="jsx-... pos" href="/search?...&pf=position%40Consultant%20(m%2Fw%2Fd)">`.

Extraktion via `_extract_pf_from_html(html)`:
- Sucht alle `<a rel="nofollow">` mit Klasse `pos`
- Liest den `pf=`-Parameter aus dem `href`-Attribut
- URL-dekodiert den Wert (`urllib.parse.unquote`)
- Dedupliziert via `seen`-Set

### Multi-Stage-Suchablauf

Für jeden Standort:

1. **Seite 0 manuell fetchen** (GET mit explizitem `&page=0`) — enthält Filter-HTML und erste Ergebnis-Batch
2. **`&cat=position` fetchen** — liefert bis zu 50 Positions-Keywords aus der erweiterten Filter-Ansicht; wird mit den aus Seite 0 extrahierten Werten gemergt
3. **Basissuche ab Seite 1** — paginiert alle Seiten ohne pf-Filter
4. **`&cat=contract` fetchen** — Beschäftigungsart-Filter (`beschäftigungsart@`, `zeitintensität@`)
5. **Sub-Suchen** — für jeden pf-Wert (`position@X`, `beschäftigungsart@Y`, `tätigkeitsbereich@Z`) wird eine eigene Paginierungsschleife gestartet; maximale Anzahl Sub-Suchen: 150

Alle Stufen teilen ein gemeinsames `seen_urls`-Set — Duplikate werden automatisch verworfen.

### Volltext-Abruf (iframe-URLs)

Für Jobs, deren `offerOriginalUrl` mit `https://www.kimeta.de/iframe/` beginnt (Kimeta-gehostete Beschreibungen), wird ein zusätzlicher HTTP-Fetch durchgeführt und der Volltext aus dem HTML extrahiert. Externe URLs (StepStone, Unternehmens-Websites) werden nicht gefetcht, um Bot-Detection zu vermeiden.

---

## Verworfene Alternativen

### PPA-basierte Filter-Extraktion

Der erste Ansatz versuchte, Filterwerte aus dem JSON-Payload `__NEXT_DATA__ → props.pageProps.__PPA__` zu lesen (Keys `positions`, `areas`, `searchFilters`). In Live-Tests lieferte der `/search?loc=`-Endpunkt jedoch immer `null` für diese Keys — die Debug-Daten stammten aus einem anderen Endpunkt (`/stellenangebote-frankfurt`). Dieser Ansatz wurde nach zweimaligem Scheitern zugunsten der HTML-Extraktion aufgegeben.

### Hardcodierte Keyword-Listen

Eine statische Liste von Berufsbezeichnungen wäre wartungsintensiv und würde Kimeta-spezifische Kategorisierungen verfehlen. Die dynamische Extraktion aus dem HTML ist sowohl aktueller als auch treffsicherer.

### Early-Stop bei bekannten Job-IDs

Ein ursprünglicher Mechanismus brach die Suche ab, wenn mehr als 75 % der gefundenen Jobs bereits in der Datenbank bekannt waren. In Tests zeigte sich, dass bei Folgeläufen 79–88 % der Jobs bereits bekannt waren und die Suche bereits nach Seite 1 abbrach — bevor neue pf-Werte überhaupt extrahiert werden konnten. Der Early-Stop wurde vollständig entfernt; Duplikat-Filterung erfolgt via `seen_urls`.

---

## Konsequenzen

- **Positiv:** Effektive Abdeckung steigt von ~225 Jobs/Standort (15 Seiten × 1 Suche) auf mehrere tausend Jobs durch Kombination aus Basissuche + Sub-Suchen
- **Positiv:** Filter-Werte werden dynamisch aus Kimeta's eigenem HTML gelesen — keine Wartung hardcodierter Listen
- **Negativ:** Signifikant mehr HTTP-Requests pro Standort (Basis + bis zu 150 Sub-Suchen × bis zu 15 Seiten); durch `_SUBSEARCH_SLEEP = 3.0s` und `_PAGE_SLEEP = 2.0s` Delays eingedämmt
- **Negativ:** Volltext nur für Kimeta-gehostete iframe-URLs verfügbar; externe URLs liefern `raw_text = None`
