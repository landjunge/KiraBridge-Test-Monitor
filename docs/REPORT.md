# Abschlussbericht – erste Implementierung und Forschungsmessung

Auftrag: **monitor-codex-development-brief-20261029**. 2026-10-30 (Europe/Berlin).
Repository: https://github.com/landjunge/KiraBridge-Test-Monitor.

## Ergebnis und Akzeptanz

Versionierter Plan wurde vor Code erstellt und gepusht. Eigenständiger
Python-Monitor mit CPU/RAM/Kernel-Speicherdruck/Swap/Disk-/Netzwerkraten,
lesenden Prozesskategorien, Eigenlast, monotonen synthetischen Shell-Proben,
CSV/JSONL, begrenzter privater Blackbox und Rotation ist implementiert.
README enthält Installation, Bedienung, Datenbedeutung und Grenzen.
KiraBridge-Ereignisformat ist nur Entwurf; keine Integration vorgenommen.
Bestehende Codex-Prozesse/Sitzungen und RC18 wurden nicht gesteuert oder verändert.

| Schritt | Commit | Akzeptanz |
| --- | --- | --- |
| Plan und Primärrecherche | 19acc65 | vor Implementierung versioniert und gepusht |
| Messkern und Speichergrenzen | bb69bab | 14 lokale Tests bestanden; Push erfolgreich |
| CLI, Proben, Dokumentation | abc0775 | 29 lokale Tests, echte 100er-Baseline, Installation/pip check; Push erfolgreich |
| Cleanup, Deadlines, CI, Messskript | 93d3c73 | 38 lokale Tests; Push erfolgreich |
| Testregression zu zusätzlichen Lückenereignissen | 82257c1 | 39 lokale Tests; Push erfolgreich |
| Wiederholte monotone Ticks unter Windows | 73fd3f2 | 40 lokale Tests; Push erfolgreich |

Der abschließende Dokumentationscommit enthält diesen Bericht und die
numerischen Messdaten. Dessen SHA und Live-Remotevergleich stehen im sichtbaren
Abschluss und in der KiraBridge-Ergebnisnachricht; ein Commit kann seinen
eigenen Hash nicht im eigenen Inhalt festhalten.

## Reproduzierbare lokale Messung

```sh
.venv/bin/python scripts/measure_local.py
```

Messcode: `93d3c73309ddc3c53e7b5375b2c35a70a43257a8`, Arbeitsbaum bei Start
sauber. Laufzeitmodule danach unverändert; während der Messung nur Testkorrektur
bearbeitet, keine lokalen Tests/Lastgeneratoren ausgeführt. macOS 15.7.4,
Darwin 24.6.0, Intel x86_64, 4 physische/logische Kerne, 32 GiB RAM,
Python 3.11.15, psutil 7.2.2. Kein Nachweis einer separaten Hardwarematrix.
Bestehende Hintergrundlast und vorhandene Sitzungen nicht verändert.

Sechs sequenzielle 100er-Trials, /bin/sh mit `:`, Timeout 2 s, 1 Hz Sampling,
seed 20261029. Die erzeugte Reihenfolge war off/memory/logging/logging/memory/off.
Kein Probe-Warm-up ausgeschlossen; erstes CPU-/Raten-Sample null.

| Runde | Bedingung | n | Median ms | p95 ms | Timeouts / Fehler | System-CPU Median % |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Proben allein | 100 | 141.28 | 174.16 | 0 / 0 | nicht gemessen |
| 1 | Sampling im RAM | 100 | 140.59 | 171.20 | 0 / 0 | 52.01 |
| 1 | Sampling + Logging | 100 | 172.24 | 223.70 | 0 / 0 | 95.76 |
| 2 | Sampling + Logging | 100 | 206.44 | 447.34 | 0 / 0 | 99.75 |
| 2 | Sampling im RAM | 100 | 173.55 | 267.75 | 0 / 0 | 92.00 |
| 2 | Proben allein | 100 | 172.62 | 226.05 | 0 / 0 | nicht gemessen |

Alle **600 Proben erfolgreich**, kein Timeout, kein Ausführungs-/Cleanupfehler,
keine Samplinglücke. Das belegt diese lokalen Runs, keine MCP-Zuverlässigkeit.
Die Bedingungen hatten deutlich verschiedene Systemlast. Deshalb ist die
höhere Latenz der Logging-Trials **kein kausaler Nachweis für Loggingkosten**.
Für deren Quantifizierung Bedingungen unter vergleichbarer Last wiederholen.

Anschließend zwei sequenzielle 60-s-Idle-Monitor-Runs, jeweils 60 Samples:

| Bedingung | Eigen-CPU Median % eines Kerns | Eigen-CPU p95 % | CPU-Mittel % über gesamten Run | RSS max MiB | Sampling p95 ms |
| --- | --- | --- | --- | --- | --- |
| RAM | 0.198 | 5.372 | 1.160 | 24.95 | 54.43 |
| Logging | 0.205 | 5.248 | 1.111 | 25.97 | 52.65 |

Beide Runs ohne Lücken, Kernel-Speicherdruck immer normal. Die im Plan
festgelegten Ziele Median-CPU <1 %, RSS <80 MiB und Sampling-p95 <100 ms
wurden **auf diesem Host und in diesen Runs** eingehalten. Der CPU-Mittelwert
liegt bei etwa 1.1 % eines Kerns, nicht unter 1 %. Die 5-s-Prozessscans erzeugen
sichtbare Spitzen; höchster Samplingwert im RAM-Run 148.74 ms. CPU-Zeit der
Probe-Children ist in der Monitor-Eigenzeit nicht enthalten.

Numerische, auf feste Felder geprüfte Zusammenfassung:
[measurements/2026-10-30.json](measurements/2026-10-30.json).
Ursprünglicher lokaler Report unter ignored runs/ hat SHA-256
`744f68d341f50d124a4a2adc1b513282adcb42f4a3b0a212d6fc594f178c9358`.
Zwei Logging-Baselines und ein Logging-Idle-Run: 18 Dateien mit 0600,
Run-Ordner 0700, Dateigrenzen und gültige JSONL/Run-IDs geprüft. Zusätzlich ein
privater Forschungsreport-Ordner. Nur feste Prozesskategorien; keine Inhalte,
Namen, PIDs, Argumente oder Secrets in den veröffentlichten Aggregaten.

## Tests und Grenzen der Evidenz

40/40 lokale Tests bestanden (17.972 s). Getestet: echte 100 Proben und feste
Eingabe-/Ausgabevarianten, nur eigener Child-Cleanup, Deadline-/Spawn-/Exitfehler,
Ctrl-C/SIGTERM, Workerfehler, Vor-/Nachlauf, zusammengeführte Trigger,
Zählerreset, Uhrsprung, fehlende Rechte, PID-Wiederverwendung, Daten-/RAM-Grenzen,
Dateimodi, Rotation, fehlende Persistenz im off/memory-Modus, CLI-Parameter.

Der erste Remote-CI-Lauf zeigte einen Testfehler: zusätzliche sampling_gap-
Records wurden als Proben mitgezählt. Laufzeitverhalten war korrekt; Testzählung
und deterministische Regression korrigiert. Im zweiten Lauf bestand macOS;
Windows deckte eine weitere zu enge Testannahme auf: zwei monotone Reads dürfen
denselben Tick liefern. Nichtnegatives Intervall und Nullraten sind jetzt
explizit getestet. Beide Korrekturen betreffen nur Tests.

Abschließender [CI-Lauf 40975602856](https://github.com/landjunge/KiraBridge-Test-Monitor/actions/runs/40975602856)
für Commit `73fd3f26b0ef7453bbaac92513f1384f091ca31a`: **alle vier Jobs erfolgreich**.

| Plattform | Ergebnis |
| --- | --- |
| macOS 15 Intel / Python 3.11 | 40/40 bestanden, 4.573 s |
| Ubuntu 24.04 / Python 3.9 | 40/40 bestanden, 0.783 s |
| Ubuntu 24.04 / Python 3.13 | 40/40 bestanden, 0.606 s |
| Windows Server 2022 / Python 3.11 | 23 bestanden, 17 POSIX-Tests ausgelassen, 0.359 s |

Installation, pip check und LICENSE-Blobprüfung in allen vier Jobs erfolgreich.
Der abschließende Commit verändert nur Dokumentation und Messaggregate.

- **Beobachtet:** lokale Latenzen variieren, Systemlast war teils fast 100 %;
  in diesen 600 Proben kein Fehler. Monitor-Eigenlast ist numerisch erfasst.
- **Offen:** H1 Last als Fehlerursache nicht bewiesen, da keine Fehler
  auftraten; H2 Kommunikation und H3 busy/Bestätigungen mangels korrelierter
  Werkzeugereignisse nicht beurteilbar. H4 Loggingeinfluss durch Lastkonfundierung
  nicht isoliert. Keine nachgewiesene KiraBridge-Ursache.
- Kein Terminal-/PTY-/MCP-End-to-End-Test. DEVNULL-Ausgabe prüft Prozessausführung,
  nicht Transport-/Rendererpuffer. 100er-Tests schließen seltene Fehler nicht aus.
- Spätere manuelle Matrix: mehrere Fenster, kurze/lange synthetische Eingaben,
  Ausgabevolumen und 0/1/2 bereitgestellte Codex-Instanzen, wiederholte Runs mit
  vergleichbarer Last. Keine automatischen Änderungen an vorhandenen Sitzungen.
- Linux/Windows: CI prüft portable Grundpfade; vollständige Produktionsfreigabe,
  Windows-Shellproben und native Linux-/Windows-Druckadapter sind spätere Arbeit.
- Retention gilt pro Run; Alt-Runs manuell löschen. Rotation kann frühere
  Incident-Teile entfernen, Abbruch kann Nachlauf verkürzen. Keine fsync-Zusage.
- Optionaler KiraBridge-Vertrag bleibt Planung mit nonblocking/emissions-only-
  Regeln; dessen zukünftige Nichtbeeinträchtigung ist noch nicht implementiert
  oder gemessen.

## Versions- und Sicherungsnachweis

Jeder abgeschlossene Schritt wurde separat committed und nach origin/main
gepusht. Die LICENSE ist unverändert: Git-Blob
`c5020fe627e99069d5be723e6857538e69d3d511` wie im Ausgangscommit 7859f38.
Der finale Nachweis vergleicht `git rev-parse HEAD`, `origin/main` und das live
von GitHub gelesene `git ls-remote origin refs/heads/main` sowie einen leeren
`git status --porcelain`. Ignorierte private Messdaten/.venv gehören nicht zum
gepushten Bestand; die aggregierte Messung und alle Quellen/Tests/Pläne schon.
