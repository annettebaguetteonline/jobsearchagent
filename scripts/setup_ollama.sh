#!/usr/bin/env bash
set -euo pipefail

# ─── Farben ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'  # No Color

echo -e "${GREEN}=== Ollama Setup ===${NC}"
echo ""

# ─── 1. Prüfe ob ollama installiert ist ──────────────────────────────────────
if ! command -v ollama &>/dev/null; then
    echo -e "${RED}Fehler: ollama ist nicht installiert.${NC}"
    echo ""
    echo "Installation:"
    echo "  Linux:  curl -fsSL https://ollama.com/install.sh | sh"
    echo "  macOS:  brew install ollama"
    echo ""
    echo "Dokumentation: https://ollama.com"
    exit 1
fi
echo -e "${GREEN}✓ ollama gefunden: $(ollama --version 2>/dev/null || echo 'Version unbekannt')${NC}"

# ─── 2. Prüfe ob ollama serve läuft ─────────────────────────────────────────
OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"

if ! curl -sf "${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then
    echo -e "${YELLOW}ollama serve ist nicht erreichbar unter ${OLLAMA_HOST}${NC}"
    echo -e "${YELLOW}Starte ollama serve im Hintergrund...${NC}"

    ollama serve &
    OLLAMA_PID=$!
    echo -e "${YELLOW}  PID: ${OLLAMA_PID}${NC}"

    # Warte bis der Server bereit ist (max 10 Sekunden)
    for i in $(seq 1 10); do
        if curl -sf "${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; then
            break
        fi
        if [ "$i" -eq 10 ]; then
            echo -e "${RED}Fehler: ollama serve konnte nicht gestartet werden nach 10s.${NC}"
            echo "Prüfe die Logs: ollama serve 2>&1"
            exit 1
        fi
        sleep 1
    done
fi
echo -e "${GREEN}✓ ollama serve läuft unter ${OLLAMA_HOST}${NC}"

# ─── 3. Benötigte Modelle ───────────────────────────────────────────────────
# mistral-nemo:12b  → Stage 1b (lokale Evaluierung)
# nomic-embed-text  → RAG Embeddings (ChromaDB)

MODELS=("mistral-nemo:12b" "nomic-embed-text")

echo ""
echo -e "${GREEN}=== Modelle prüfen ===${NC}"

for model in "${MODELS[@]}"; do
    if ollama list 2>/dev/null | grep -q "$model"; then
        echo -e "${GREEN}✓ ${model} bereits vorhanden${NC}"
    else
        echo -e "${YELLOW}↓ Lade ${model} herunter...${NC}"
        if ollama pull "$model"; then
            echo -e "${GREEN}✓ ${model} erfolgreich heruntergeladen${NC}"
        else
            echo -e "${RED}✗ Fehler beim Download von ${model}${NC}"
            exit 1
        fi
    fi
done

# ─── 4. Schnelltest ─────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}=== Schnelltest ===${NC}"

# Einfacher API-Test mit dem Embedding-Modell
if curl -sf "${OLLAMA_HOST}/api/embeddings" \
    -d '{"model": "nomic-embed-text", "prompt": "test"}' \
    -o /dev/null 2>&1; then
    echo -e "${GREEN}✓ Embedding-API antwortet korrekt${NC}"
else
    echo -e "${YELLOW}⚠ Embedding-Schnelltest fehlgeschlagen (Modell wird eventuell noch geladen)${NC}"
fi

# ─── 5. Zusammenfassung ─────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}=== Verfügbare Modelle ===${NC}"
ollama list 2>/dev/null || echo "(ollama list nicht verfügbar)"

echo ""
echo -e "${GREEN}=== Setup abgeschlossen ===${NC}"
echo ""
echo "Konfiguration in backend/.env oder Umgebungsvariablen:"
echo "  OLLAMA_HOST=${OLLAMA_HOST}"
echo "  OLLAMA_MODEL_STAGE1=mistral-nemo:12b"
echo "  OLLAMA_EMBED_MODEL=nomic-embed-text"
