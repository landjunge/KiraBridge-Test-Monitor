# Phasenergebnisse

Auftrag: monitor-codex-development-brief-20261029.

## Phase 1 – Plan

Bestand: ausschließlich unveränderte LICENSE, main und origin/main auf 7859f38.
Architektur, Teststrategie, Forschungsfaktoren und Beweiskriterien vor Code
festgehalten. Fünf Desktop-Commander-Primärquellen gelesen; keine KiraBridge-
Ursache daraus behauptet. Ereignisvertrag bleibt optionaler Entwurf.
Akzeptanz: Dokumentprüfung bestanden. Push wird über Git-Historie und finalen
Live-Remotevergleich nachgewiesen.

## Phase 2 – Messkern

Implementiert: Dual-Clock/Run-ID, nicht blockierendes CPU-Delta, RAM/Swap,
Disk-/Netzwerkraten mit Null bei Reset/fehlendem Wert, gekapselter Darwin-
Kernel-Speicherdruck, read-only Prozesskategorien alle 5 s, Eigen-CPU/RSS.
Private exklusive Run-Verzeichnisse, bytebegrenzte JSONL-/CSV-Rotation,
Ringpuffer und ein zusammengeführter Vor-/Nachlaufvorfall.

Akzeptanz: `python3.11 -m unittest discover -s tests -v`: 14 Tests bestanden
auf macOS 15.7.4 x86_64, Python 3.11.15, psutil 7.2.2. Geprüft wurden echte
read-only Samples, Warm-up, Counterreset, fehlende Rechte, Scan-Drosselung,
Wandzeitsprung, feste Kategorien, Rotation/CSV-Header, Dateimodi, exklusives
Öffnen/Symlinkschutz, Ringgrenze sowie Vor-/Nachlauf. Ein initialer Syntaxfehler
wurde vor dem Commit korrigiert. Keine fremden Prozesse gestartet/beendet.

## Phase 3 – CLI, Proben und Installation

`monitor`, `baseline` und `overhead` implementiert, inklusive 100er-Default,
vier festen synthetischen Szenarien, nur eigener Child-Prozess/DEVNULL,
privaten Rohdaten, Median/nearest-rank-p95 und getrennten Timeout-/Fehlerquoten.
Ein Writer-Eventloop übernimmt Probe-Ereignisse vom begrenzten Worker-Queue;
SIGTERM/Ctrl-C und abgebrochener Nachlauf sind sichtbar. Setup/README und
lokale Editable-Installation erfolgreich, `pip check` ohne Konflikte.

Akzeptanz: `.venv/bin/python -m unittest discover -s tests -v`: **29/29**
bestanden (17.496 s). Darunter eine echte 100er-Baseline (100 erfolgreiche
Shell-Proben), alle Szenarien, eigener Timeout-Cleanup mit weiterlaufendem
Kontrollprozess, Nichtnull-Exit, fehlendes Executable, Cancellation, begrenzte
Statistik, CLI-Validierung, Workerfehler, keine Dateien in off/memory,
unvollständiger Stop und vollständiger Blackbox-Nachlauf. Test-Tempdateien
werden ab dieser Phase ausschließlich unter Repository/.tmp angelegt.

Präzisierungen gegenüber Plan v1: Ringkapazität zählt Records (Samples und
Ereignisse), keine zugesicherte Sekundendauer. Vier rotierende Streams mit
zusammen standardmäßig höchstens 16 MiB pro Run; Metadaten/Summary je 64 KiB.
Historische Runs werden nicht automatisch gelöscht. Streaming-Sample-Statistik
auf die letzten 3600 Samples begrenzt; Probezahl auf 10000. Ausgabevolumentests
gehen nach DEVNULL und bilden PTY/Renderer/MCP-Puffer nicht nach. Windows-
Proben bleiben ausdrücklich späteres Ziel. Kernel-Speicherdruck hier normal/ok.
Die Forschungs-Baselines und längere Eigenlastmessung folgen in Phase 4.

## Phase 4a – Zuverlässigkeit vor den Forschungsmessungen

Collector wartet auf Queue-Ereignisse und monotone Deadlines statt regelmäßig
nachzusehen. Timeout ist explizit ein nicht innerhalb der Deadline beobachteter
Abschluss; langsame OS-Prozesserzeugung bleibt als Einschränkung dokumentiert.
Incident-Wrapper tragen dieselbe Run-ID und eigene Dual-Clock-Zeitstempel.
API-Grenzen, CPU-Counterreset und PID-Wiederverwendung werden abgefangen.

Akzeptanz: **38/38 Tests bestanden** in 19.446 s mit der installierten .venv.
Neu geprüft: echter SIGTERM-Abbruch des eigenen CLI-Prozesses inklusive
Summary/Blackbox-Footer, KeyboardInterrupt-Cleanup, sichtbarer Cleanupfehler,
endlicher überlappender Nachlauf, CPU-Reset, Kernelabfragefehler,
Prozesskategorien ohne private Namen, PID-Wiederverwendung und RAM-Grenze.
GitHub-CI für macOS Intel, Linux Python 3.9/3.13 und Windows-Grundpfade
konfiguriert; zum Zeitpunkt dieses Commits noch kein Remote-Testnachweis.
Standard-Runner nur bei öffentlichem Repository aktiviert, keine Rohdaten-
Uploads. `scripts/measure_local.py` ermöglicht die folgende sequenzielle
Forschungsmessung mit Commit-Nachweis; `requirements-tested.txt` pinnt psutil.
