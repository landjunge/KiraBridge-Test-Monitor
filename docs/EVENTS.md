# Optionaler KiraBridge-Ereignisvertrag – Entwurf v1

Auftrag: monitor-codex-development-brief-20261029.
Nur Planung, kein Sender, Empfänger, Watcher oder KiraBridge-Patch implementiert.

Ein Ereignis ist maximal 1 KiB UTF-8 JSON plus Newline:

```json
{"schema_version":1,"source":"kirabridge","run_id":"opaque-uuid","task_id":"opaque-uuid","session_id":"opaque-uuid","event_id":"opaque-uuid","sequence":1,"phase":"start","utc":"2026-10-30T00:00:00.000000Z","monotonic_ns":123456789,"status":"ok"}
```

`phase`: start / accepted / result / timeout. `status`: ok / error / unknown.
IDs zufällig/opaque, keine Nutzertexte. Keine Prompts, Ergebnisse, Werkzeug-
argumente, Terminalinhalte, Pfade, Hosts, Secrets, Umgebungen oder freie Meldungen.
Monotone Werte nur innerhalb source+run_id vergleichen; Rechneruhren benötigen
UTC-Offset-/Unsicherheitsnachweis. sequence macht Lücken sichtbar, event_id
ermöglicht Deduplizierung; arrival_utc getrennt von Quellzeit aufzeichnen.

KiraBridge emittiert ausschließlich bei Werkzeugaktivität. Kleiner begrenzter
In-Memory-Queue, nicht blockierendes offer, begrenzter lokaler Worker-Transport,
bei vollem Puffer verwerfen und Zähler erhöhen. Keine Retries im Werkzeugpfad,
keine synchronen Datei-/Socketwrites dort, keine kontinuierlichen Abfragen.
Monitor fehlt, Queue voll oder Worker defekt: Werkzeug läuft unverändert weiter.
Keine Laufzeitabhängigkeit KiraBridge → Monitor. Transport, Authentisierung,
Dropzähler und Lastbudget erst in gesonderter Integrationsphase festlegen.

Spätere Akzeptanz: Werkzeuglatenz mit/ohne Empfänger vergleichen, Empfänger
beenden/Queue fluten, keine Werkzeugblockade; Lücken/Duplikate/Reorder erkennen;
Tests mit synthetischen IDs. Ein receipt belegt Empfang, kein Arbeitsergebnis.
