# ADR-003: service.bund.de ohne Ortsfilter scrapen

**Status:** Accepted
**Stand:** März 2026

---

## Kontext

Das ursprüngliche Design-Dokument sah einen Ortsfilter für service.bund.de vor
("Hessen + RLP"). Bei der Implementierung stellte sich heraus, dass der RSS-Feed
von service.bund.de keine funktionierenden Query-Parameter für Bundesland-Filterung
anbietet — der Feed liefert immer alle bundesweiten Stellen.

Die RSS-URL hat keine wirksamen Filter-Parameter:
```
https://www.service.bund.de/Content/Globals/Functions/RSSFeed/RSSGenerator_Stellen.xml
```

Optionen:
1. Nur Stellen aus bestimmten Bundesländern anhand des Orts-Feldes nachträglich filtern
2. Alle Stellen scrapen, Filterung der Evaluation-Pipeline überlassen
3. Andere Quelle für regionale Öffentlicher-Dienst-Stellen suchen

## Entscheidung

**Option 2: Alle Stellen scrapen, Evaluation entscheidet.**

- Die Evaluation-Pipeline bewertet Stellen ohnehin anhand des Nutzerprofils (Standort,
  Pendelzeit via ÖPNV-API)
- Eine nachträgliche Bundesland-Filterung im Scraper wäre fragil
  (Ort-Feld enthält "34117 Kassel" → Bundesland nicht direkt ableitbar ohne Geocoding)
- Öffentlicher Dienst bundesweit kann interessant sein — Remote-Stellen oder
  attraktive Behörden in anderen Bundesländern sollten nicht vorab ausgeschlossen werden
- Der Scraper selbst ist zustandslos und günstig — kein Grund zur künstlichen Einschränkung

## Konsequenzen

- service.bund.de liefert deutlich mehr Jobs als StepStone (bundesweit, alle Branchen)
- Die Evaluation-Pipeline muss Pendelzeiten und Ortsrelevanz eigenständig bewerten
  (ist ohnehin geplant via DB REST API / Nominatim)
- Das Design-Dokument (Abschnitt 2, Quellen-Tabelle) wurde entsprechend korrigiert:
  "Hessen + RLP" → "bundesweit (kein Ortsfilter)"
- `scrape_posted_within_days` begrenzt das Volumen zeitlich (Standard: 2 Tage)
