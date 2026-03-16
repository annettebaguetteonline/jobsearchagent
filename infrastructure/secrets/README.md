# Secrets-Verzeichnis

Hier werden Docker-Secrets als Plaintext-Dateien abgelegt.

| Datei | Inhalt |
|-------|--------|
| `anthropic_key.txt` | Anthropic-API-Key (`sk-ant-...`) |
| `adzuna_app_id.txt` | Adzuna App-ID (kostenlos: developer.adzuna.com) |
| `adzuna_app_key.txt` | Adzuna App-Key |
| `jooble_api_key.txt` | Jooble API-Key (kostenlos: jooble.org/api/about) |

Dieses Verzeichnis ist gitignored (*.txt, *.key, *.pem).
Dateien werden read-only in Container gemountet unter `/run/secrets/`.

**NIEMALS echte Schlüssel committen.**
