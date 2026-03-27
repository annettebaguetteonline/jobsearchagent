# ADR-009: Kernprofil-Extraktion mit Claude Sonnet

**Status:** Accepted
**Stand:** März 2026

---

## Kontext

Das Nutzerprofil wird aus hochgeladenen Dokumenten (Lebenslauf, Arbeitszeugnisse, Zertifikate) extrahiert und als strukturiertes `Kernprofil`-Objekt gespeichert. Deutsche Arbeitszeugnisse verwenden eine kodierte Sprache ("stets zur vollsten Zufriedenheit" = Note 1, "zu unserer Zufriedenheit" = Note 3-4), die korrekt interpretiert werden muss. Das Profil dient als Referenz für alle Evaluierungsstufen.

## Entscheidung

Die Kernprofil-Extraktion erfolgt durch Claude Sonnet (cloud-basiert) mit einem strukturierten Prompt, der folgende Felder extrahiert:

- `skills: SkillSet` — Programmiersprachen, Frameworks, Tools, Domänen
- `experience: Experience` — Gesamtjahre, aktuelles Level, Führungserfahrung
- `preferences: Preferences` — Work-Model, Gehaltsvorstellung, Pendelzeit
- `narrative_profile: str` — 2-3 Sätze Zusammenfassung des Profils
- `certifications: list[str]` — Zertifizierungen
- `projects_summary: list[str]` — Projektübersicht

Das Profil wird als JSON in `users.profile_json` gespeichert, mit einem SHA256-Hash als `profile_version` für Change-Detection.

## Begründung

- **Sprachverständnis**: Claude Sonnet versteht die kodierte Sprache deutscher Arbeitszeugnisse und kann Nuancen korrekt interpretieren.
- **Strukturierter Output**: JSON-Mode von Claude liefert direkt das gewünschte Schema.
- **Einmalkosten**: Profil-Extraktion wird nur bei Upload neuer Dokumente ausgeführt (nicht pro Job), daher sind Cloud-Kosten (~$0.05 pro Extraktion) vernachlässigbar.
- **Qualität**: Claude Sonnet liefert signifikant bessere Ergebnisse als lokale Modelle bei der Interpretation komplexer deutscher Texte.

## Konsequenzen

### Positiv
- Hochwertige Profil-Extraktion aus deutschen Dokumenten
- Einmalige Kosten pro Profiländerung (nicht pro Job-Evaluierung)
- SHA256-Versionierung ermöglicht Change-Detection für Re-Evaluierungen
- Strukturiertes `Kernprofil` als Single Source of Truth

### Negativ
- Erfordert Anthropic-API-Key und Internet-Verbindung
- Keine Offline-Profil-Extraktion möglich
- Datenschutz: Persönliche Dokumente werden an externe API gesendet

## Alternativen verworfen

- **Lokales LLM (mistral-nemo:12b):** Profil-Extraktion mit Ollama. Verworfen: Unzureichende Qualität bei deutscher Zeugnissprache. In Tests wurden Bewertungscodes falsch interpretiert (z.B. "bemühte sich" als positiv eingestuft).
- **Manuelle Eingabe:** User füllt strukturiertes Formular aus. Verworfen: Hoher Aufwand für User, keine automatische Aktualisierung bei neuen Dokumenten.
- **NER + Pattern Matching:** Regel-basierte Extraktion. Verworfen: Zu fragil für die Vielfalt deutscher Lebenslauf-Formate.
