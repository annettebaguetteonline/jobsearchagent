# Secrets-Verzeichnis

Hier werden Docker-Secrets als Plaintext-Dateien abgelegt.

| Datei | Inhalt |
|-------|--------|
| `anthropic_key.txt` | Anthropic-API-Key (`sk-ant-...`) |

Dieses Verzeichnis ist gitignored (*.txt, *.key, *.pem).
Dateien werden read-only in Container gemountet unter `/run/secrets/`.

**NIEMALS echte Schlüssel committen.**
