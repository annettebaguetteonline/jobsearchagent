# ADR-002: PLZ-Normalisierung in der canonical_id-Berechnung

**Status:** Accepted
**Stand:** März 2026

---

## Kontext

service.bund.de liefert Ortsangaben im Format `"PLZ Stadt"` (z.B. `"34117 Kassel"`).
StepStone und andere Aggregatoren liefern für denselben Ort nur `"Kassel"`.

Ohne Normalisierung ergibt sich für dieselbe Stelle bei gleicher Firma:

```
service.bund.de: SHA256("sachbearbeiter|landesamt|34117 kassel") = AAA...
StepStone:       SHA256("sachbearbeiter|landesamt|kassel")         = BBB...
```

→ Stufe-1-Dedup schlägt fehl, die Stelle wird doppelt eingetragen.

## Entscheidung

Vor der Hash-Berechnung wird führende PLZ (4–5 Stellen gefolgt von Leerzeichen) entfernt:

```python
def _strip_plz(location: str) -> str:
    return re.sub(r"^\d{4,5}\s+", "", location)
```

Implementiert in `app/scraper/base.py`, aufgerufen in `compute_canonical_id()`.

Ergebnis:
```
"34117 Kassel" → "kassel"  (nach normalize_text)
"Kassel"       → "kassel"  (nach normalize_text)
→ gleicher Hash → Stufe-1-Dedup greift
```

## Konsequenzen

- `_strip_plz()` betrifft nur den Hash, nicht das gespeicherte `location_raw`
  (das behält das Original-Format `"34117 Kassel"` für die Anzeige)
- 4-stellige PLZ (z.B. Österreich `"1010 Wien"`) werden ebenfalls normalisiert —
  konsistentes Verhalten falls internationale Quellen ergänzt werden
- Edge case: `"Frankfurt am Main 60311"` (PLZ am Ende) wird nicht normalisiert —
  akzeptiertes Risiko, da deutsches Standard-Format PLZ vorne hat

## Alternativen verworfen

- **PLZ-Geocoding:** Aufwendig, API-abhängig — übertrieben für Normalisierung
- **Nur Stadt im canonical_id:** Würde echte Mehrfachstandorte (Berlin ≠ Berlin-Mitte)
  schlechter unterscheiden
- **PLZ aus location_raw entfernen beim Speichern:** Verlust der Präzisionsinformation
  die die Evaluation-Pipeline nutzen könnte
