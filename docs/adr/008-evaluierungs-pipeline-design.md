# ADR-008: Evaluierungs-Pipeline Design

**Status:** Accepted
**Stand:** März 2026

---

## Kontext

Die Evaluierungs-Pipeline muss täglich 100-500 Stellenangebote bewerten und in eine Rangliste bringen. Die Kosten für Cloud-LLM-Aufrufe (Anthropic Claude) sind signifikant — bei 500 Jobs pro Tag und $0.003/Request summiert sich das auf $45/Monat allein für die Evaluierung. Gleichzeitig gibt es viele offensichtliche Nicht-Matches (falsches Berufsfeld, zu niedriges Level, Ausschluss-Keywords), die keinen teuren LLM-Aufruf rechtfertigen.

## Entscheidung

Die Evaluierung erfolgt in drei aufeinander aufbauenden Stufen:

1. **Stage 1a — Deterministische Filter** (lokal, <1ms pro Job)
   - Keyword-Ausschlüsse (z.B. "Chefarzt", "Praktikum", "Werkstudent")
   - Titel-Pattern-Matching gegen konfigurierbare Listen
   - Keine externen API-Calls, kein LLM

2. **Stage 1b — Lokale LLM-Vorfilterung** (Ollama, mistral-nemo:12b, ~500ms pro Job)
   - Fachgebiet-Abgleich (IT vs. Medizin vs. Handwerk)
   - Grobe Skill-Plausibilitätsprüfung
   - Feld-Extraktion: Gehalt, Work-Model, fehlende Metadaten
   - Binäre Entscheidung: PASS oder SKIP

3. **Stage 2 — Cloud-LLM-Bewertung** (Anthropic Claude, ~3s pro Job)
   - Detaillierter Score (1.0-10.0) mit 5 Subdimensionen
   - Empfehlung (APPLY/MAYBE/SKIP) mit Begründung
   - Match-Analyse, fehlende Skills, Gehaltsschätzung
   - Bewerbungstipps

## Begründung

- **Kostenoptimierung**: Stage 1a (kostenlos) und Stage 1b (lokal, kostenlos) filtern 60-80% der Jobs vor Cloud-Aufrufen heraus. Erwartete Kostensenkung: 60-80%.
- **Geschwindigkeit**: Deterministische Filter in <1ms. Ollama lokal in ~500ms. Nur die vielversprechendsten Jobs (20-40%) gehen an die Cloud.
- **Qualität**: Die finale Bewertung durch Claude Sonnet/Haiku liefert die höchste Qualität mit strukturiertem Output (Score-Breakdown, Begründung, Tipps).
- **Failsafe**: Bei Ollama-Ausfall fallen Jobs durch zu Stage 2 (false positive, teurer aber kein Informationsverlust). Bei Anthropic-Ausfall bleiben Stage-1-Ergebnisse erhalten.

## Konsequenzen

### Positiv
- 60-80% Kosteneinsparung gegenüber reiner Cloud-LLM-Lösung
- Schnelles Feedback für offensichtliche Nicht-Matches (<1s)
- Offline-fähig für Stage 1a + 1b (nur lokale Ressourcen)
- Extrahierte Felder (Gehalt, Work-Model) verbessern die Datenbasis

### Negativ
- Höhere Systemkomplexität (3 Stufen statt 1)
- Ollama benötigt ~7GB RAM/VRAM für mistral-nemo:12b
- Deterministische Filter müssen regelmäßig gepflegt werden
- Stage-1b-Qualität ist niedriger als Cloud-LLM — mögliche False Negatives

## Alternativen verworfen

- **Nur Cloud-LLM:** Alle Jobs direkt an Claude senden. Verworfen: Zu teuer ($45+/Monat), zu langsam (3s × 500 = 25min).
- **Nur deterministische Filter + Cloud-LLM:** Ohne lokales LLM. Verworfen: Keyword-Filter allein fangen nur ~30% der Nicht-Matches. Fachgebiet-Erkennung ("Zahntechniker" ≠ IT) braucht Sprachverständnis.
- **Embedding-basiertes Scoring:** Cosine-Similarity zwischen Profil und Job. Verworfen: Zu grob für nuancierte Bewertung, keine strukturierte Begründung.
