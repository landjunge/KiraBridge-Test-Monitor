# Architektur-, Entwicklungs- und Testplan v1

Auftrag: **monitor-codex-development-brief-20261029**. Stand: 2026-10-30.
Ziel: unabhängiger, ressourcenschonender lokaler Monitor zur Untersuchung
sporadischer Terminal-/MCP-Timeouts, falscher busy-Zustände und fehlender
Bestätigungen. Ein lokaler Probe-Erfolg beweist keine erfolgreiche MCP-Zustellung.

## Bestand und Grenzen

Ausgangscommit `7859f38`: ausschließlich LICENSE, sauberer Branch main,
origin https://github.com/landjunge/KiraBridge-Test-Monitor.
LICENSE bleibt bytegleich (Git-Blob c5020fe627e99069d5be723e6857538e69d3d511).
Nur dieses Repository bearbeiten; RC18, andere Repos und bestehende
Codex-Sitzungen weder ändern noch steuern. Keine KiraBridge-Integration,
keine kostenpflichtigen Dienste und keine automatischen Lastgeneratoren.

## Architektur v1

Python >=3.9, psutil als einzige Laufzeitabhängigkeit, unittest als Testbasis.
macOS Intel zuerst; portable psutil-Grunddaten, gekapselter macOS-Adapter
für Kernel-Speicherdruck. Linux/Windows bleiben Erweiterungs- und Prüfziele.
Keine Administratorrechte, kein Dienst, keine Shell-Konfiguration ändern.

- `metrics.py`: CPU nicht blockierend, RAM verfügbar/gesamt, Swap und
  kumulative Disk-/Netzwerkzähler sowie aus tatsächlichem monotonem Abstand
  berechnete Raten. Fehlende/gesperrte Werte als null plus Status, niemals 0
  erfinden. Prozessabfrage höchstens alle 5 s; nur feste Kategorien
  (Codex, KiraBridge, Terminal, Browser, Spotlight, Backup, sonstige hohe Last),
  Anzahl/CPU/RSS aggregieren. Keine argv, Umgebungen, Pfade, PIDs persistieren.
- `clock.py`: UTC-Wandzeit für externe Zuordnung, monotonic_ns für Laufzeiten,
  eindeutige Run-ID pro Start. Monotone Zeiten nur innerhalb desselben Runs
  direkt vergleichen; UTC-Sprünge und Abtastlücken sichtbar machen.
- `storage.py`: private neue Verzeichnisse (0700), Dateien (0600), exklusiver
  Run-Ordner; begrenzte JSONL-Rotation; CSV-Probedaten ebenfalls begrenzt.
  Ringpuffer mit fester Samplezahl; bei Fehler Snapshot mit Vorlauf und
  konfigurierbarem Nachlauf; überlappende Trigger zusammenfassen. Keine
  unbeschränkte Liste offener Vorfälle. Rotationsgrenze gilt auch Snapshots.
- `probe.py`: ausschließlich eingebaute harmlose synthetische Befehle;
  frische nicht interaktive Shell ohne Benutzer-Startdateien (POSIX),
  Windows später prüfen. stdout/stderr nach DEVNULL, keine Inhalte speichern,
  begrenzter Timeout, nur eigenen gestarteten Child-Prozess beenden/reapen.
  Keine fremden Prozesse signalisieren. Default 100 Wiederholungen, sequenziell.
- `report.py`: JSONL/CSV, Median, nearest-rank p95, Timeoutquote, Fehlerquote.
  Laufzeiten erfolgreicher Proben getrennt von Timeout-Zensierung.
- `cli.py`: `monitor`, `baseline`, `overhead`; begrenzte Dauer, Ctrl-C sauber,
  Logging an/aus; Eigen-CPU/RSS und Abtastkosten. Keine Telemetrie/Uploads.

Standard: 1 s Sampling, 120 Samples Vorlauf, 10 s Nachlauf,
1 MiB pro Datei plus 3 Backups je Stream. Eigenlastziel auf Ziel-iMac:
Median <1 % eines CPU-Kerns, RSS <80 MiB, Sampling p95 <100 ms bei 1 Hz.
Das sind zu messende Ziele, keine Zusagen. Prozessscan wird separat gedrosselt.

## Forschung und Beweiskriterien

H1 Systemlast: lokale Probe-Latenz/Timeout korreliert mit CPU, Druck, Swap oder
I/O. H2 Kommunikation: lokale Proben bleiben schnell, aber Annahme/Ergebnis
fehlen bei KiraBridge. H3 Zustands-/Reconnectfehler: busy/Bestätigung widerspricht
korrelierten Start-/Annahme-/Ergebnisereignissen. H4 Messartefakt: Monitor oder
Logging beeinflusst Messung. Alle vier sind zunächst Hypothesen.

Vorgehen: mindestens 100 Wiederholungen pro Bedingung; gleiche Probe/Timeout,
Warm-up kennzeichnen, Reihenfolge AB/BA oder randomisiert, mehrere unabhängige
Runs. Keine künstliche Hintergrundlast in dieser Umsetzung. Vergleich:
Probe allein; Sampling ohne Persistenz; Sampling mit Persistenz. Eigenlast
zusätzlich über längere Idle-Monitor-Runs messen. Median/p95/Timeoutquote und
Anzahl, Fehler, Sampling-Lücken, Version, OS/Arch und Parameter berichten.
Null Timeouts bei n=100 schließt seltene Fehler nicht aus (Faustregel obere
95-%-Grenze etwa 3 %). Korrelation beweist keine Kausalität; ohne externe
Werkzeugereignisse keine Diagnose von MCP oder falschem busy möglich.

Spätere Matrix (manuell vorbereitet, Monitor öffnet/steuert nichts): kurze
und lange synthetische Eingaben; 0/4 KiB/1 MiB Ausgabe; ein/mehrere Fenster;
0/1/2 bereits vom Betreiber bereitgestellte Codex-Instanzen. Keine Prompts
oder Nutzerinhalte. Anzahl Fenster/Instanzen als numerische Versuchsfaktoren,
nicht als automatisch hergestellte Situation. Für kausale Aussagen Zustände
gezielt wiederholen und alternative Erklärungen/Unsicherheit dokumentieren.

## Phasen und Akzeptanz

| Phase | Lieferumfang | Akzeptanz / Nachweis |
| --- | --- | --- |
| 1 Plan | Dieser Plan, Vergleichsrecherche, optionaler Ereignisvertrag | Bestand geprüft; Primärlinks und Hypothesen; Commit + Push vor Code |
| 2 Messkern | Clock, Sampler, private Rotation, Blackbox, Unit-Tests | Raten/Reset/null, Prozessschutz, Zeitkorrelation, Ring/Rotation/Vor-/Nachlauf/Dateimodi geprüft; Commit + Push |
| 3 Bedienbarer Monitor | CLI, Proben, Statistik, Eigenlastvergleich, README | 100 echte harmlose Proben; Timeout-/Fehlerpfade nur eigene Children; Logging an/aus; CLI- und Datenschutztests; Commit + Push |
| 4 Auswertung | lokale Baselines, Eigenlast, Abschlussbericht, CI | reproduzierbare Ergebnisse mit Grenzen; gesamte Testsuite; LICENSE-Blob gleich; Commit + Push; git status/HEAD/live Remote-HEAD belegen |

Jede abgeschlossene Phase erhält einen Ergebnisabschnitt in RESULTS.md.
Pushfehler als ungesichert melden und lösen, bevor Synchronität behauptet wird.

## Teststrategie

Deterministische Unit-Tests mit Fakes für Plattform/Permissionfehler,
Counterreset, wechselnde Uhr, verpasste Intervalle und CPU-Warm-up.
Integrationstests mit harmlosen eigenen Children für Erfolg/Exit/Timeout,
Rotation und abgeschlossenem Blackbox-Nachlauf. Keine fragile Behauptung
"fertig nach x Millisekunden": auf Prozessende warten, feste Obergrenzen.
CLI-Tests für ungültige Parameter, sauberen Stop und keine Content-Felder.
Lokaler Smoke-Test auf macOS Intel; Python-Versionen/Plattformen in CI prüfen.
Rohdaten bleiben ignoriert und privat; nur geprüfte numerische Ergebnisse
und synthetische Test-Fixtures versionieren. Vollständige Hardwarematrix
und echte MCP-Reproduktion später; keine Ursache ohne passende Evidenz.
