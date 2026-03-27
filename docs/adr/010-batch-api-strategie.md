# ADR-010: Anthropic Batch API für Stage 2

**Status:** Accepted
**Stand:** März 2026

---

## Kontext

Stage 2 der Evaluierung sendet 20-200 Jobs pro Durchlauf an Claude zur detaillierten Bewertung. Die Standard-API (synchron) kostet $0.003 pro Request (Haiku) bzw. $0.015 (Sonnet). Die Anthropic Batch API bietet 50% Rabatt bei asynchroner Verarbeitung mit einem SLA von 24 Stunden. Da die Evaluierung nicht echtzeitkritisch ist (Jobs werden max. 1x täglich bewertet), ist die Batch API geeignet.

## Entscheidung

Stage-2-Evaluierungen werden über die Anthropic Batch API als asynchroner Batch-Job eingereicht:

1. **Submission**: Alle Stage-1-PASS-Jobs werden als Batch-Request an die API gesendet.
2. **Tracking**: Batch-ID, Status und Fortschritt werden in `evaluation_batches` gespeichert.
3. **Polling**: Background-Task pollt den Batch-Status bis `ended` oder `failed`.
4. **Ergebnis-Import**: Einzelergebnisse werden per Job in `evaluations` gespeichert.

Status-Übergänge:
```
submitted → processing → ended    (Erfolg)
                       → failed   (API-Fehler)
                       → expired  (24h SLA überschritten)
```

Die `evaluation_batches`-Tabelle trackt:
- `batch_api_id`: Von Anthropic zurückgegebene Batch-ID
- `status`: Aktueller Verarbeitungsstatus
- `job_count` / `completed_count` / `error_count`: Fortschritt
- `error_log`: JSON mit Fehlermeldungen pro Job

## Begründung

- **50% Kosteneinsparung**: Batch-Preis ist halb so hoch wie synchrone API. Bei 100 Jobs/Tag und Haiku: $0.15/Tag statt $0.30/Tag = $4.50/Monat gespart.
- **Keine Echtzeit-Anforderung**: Jobs werden 1x täglich evaluiert — 24h SLA ist akzeptabel.
- **Automatische Retry**: Die Batch API wiederholt fehlgeschlagene Requests intern.
- **Rate-Limit-freundlich**: Kein Risiko von 429-Fehlern bei hohem Durchsatz.

## Konsequenzen

### Positiv
- 50% Kostenersparnis gegenüber synchroner API
- Kein Rate-Limiting-Risiko
- Eingebaute Retries durch die Batch API
- Sauberes Status-Tracking in der Datenbank

### Negativ
- Asynchrone Verarbeitung: Ergebnisse sind nicht sofort verfügbar (bis zu 24h)
- Komplexeres Error-Handling (Batch-Level + Job-Level Fehler)
- Polling-Mechanismus benötigt Background-Task
- Batch-API hat eigene Limitierungen (max. 10.000 Requests pro Batch)

## Alternativen verworfen

- **Synchrone API-Calls:** Direkte Aufrufe an Claude Messages API. Verworfen: Doppelt so teuer, Rate-Limiting bei >50 Requests/Minute, keine eingebauten Retries.
- **Gemischte Strategie:** Synchron für <10 Jobs, Batch für ≥10. Verworfen: Erhöht Komplexität ohne signifikanten Vorteil. Auch bei wenigen Jobs ist die Batch API günstiger und robuster.
- **Eigene Job-Queue (Redis/Celery):** Asynchrone Verarbeitung mit eigenem Queue-System. Verworfen: Overengineering für den Anwendungsfall. Die Batch API bietet die Queue-Funktionalität bereits nativ mit Kostenvorteil.
