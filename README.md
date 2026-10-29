# KiraBridge Test Monitor

Eigenständiger lokaler Python-Monitor für macOS Intel: Ressourcen zeitlich
mit harmlosen synthetischen Shell-Proben vergleichen. Keine Verbindung zu
KiraBridge, keine Steuerung bestehender Codex-Prozesse, keine externen Dienste.
Auftrag: `monitor-codex-development-brief-20261029`.

## Installation

Python 3.9 oder neuer (auf diesem Intel-Mac mit Python 3.11 geprüft).
Die vorhandene [LICENSE](LICENSE) gilt unverändert: Netzwerkpunkt Personal
Use License 1.0, keine Open-Source-Lizenz. psutil behält seine eigene Lizenz.

```sh
git clone https://github.com/landjunge/KiraBridge-Test-Monitor.git
cd KiraBridge-Test-Monitor
python3.11 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/kira-monitor --help
```

Keine Administratorrechte nötig. Installation braucht Internet für psutil
und Build-Werkzeuge; der Monitor selbst arbeitet offline. Auf einem älteren
macOS müssen Python und ein kompatibles psutil-Wheel vorhanden sein; bei
Source-Builds können die Apple Command Line Tools nötig sein.

## Starten

```sh
# 60 Sekunden Ressourcen, 1 Hz, Dateien unter ./runs/run-<zufällige ID>/
.venv/bin/kira-monitor monitor --duration 60

# 100 harmlose /bin/sh-Proben, monoton gemessen; keine Shell-Startdateien
.venv/bin/kira-monitor baseline

# Eigenlastvergleich: 2 Runden mit je 100 Proben pro Bedingung,
# reproduzierbar gemischte Reihenfolge; 600 Proben insgesamt
.venv/bin/kira-monitor overhead --rounds 2 --repetitions 100

# Sampling ohne Dateien bzw. Proben ganz ohne Sampling/Dateien
.venv/bin/kira-monitor monitor --duration 60 --no-logging
.venv/bin/kira-monitor baseline --mode memory
.venv/bin/kira-monitor baseline --mode off

# Manueller fester Fehlerzeitmarker: Vor-/Nachlauf ausprobieren
.venv/bin/kira-monitor monitor --duration 20 --marker --post 10
```

Ctrl-C und SIGTERM stoppen den Monitor und bereinigen den eigenen Testprozess.
Exitcode 0: abgeschlossen; 1: Probe-Timeout/-Fehler oder Worker-/Cleanupfehler;
2: ungültige Parameter oder lokaler Betriebsfehler; 130: abgebrochen.
`--duration` begrenzt den Monitor einschließlich Setup. Eine Baseline endet
nach allen Proben und ggf. dem Blackbox-Nachlauf. Keine Dauerdienste installiert.

Szenarien: `--scenario noop`, `long-input` (16 KiB synthetisches Argument),
`output-4k` und `output-1m`. Die beiden Ausgabetests starten den aktuellen Python-
Interpreter per Shell-`exec`; deren Latenz enthält den Interpreterstart.
Ausgabe geht direkt nach DEVNULL, wird nicht gelesen oder gespeichert. Dies
prüft **keinen** Terminal-Renderer, PTY oder MCP-Puffer. Windows-Proben sind noch
nicht implementiert; portable Ressourcenpfade sind für spätere Portierung da.

`--windows 2 --codex-instances 1` speichert ausschließlich manuell deklarierte
Versuchsfaktoren. Der Monitor öffnet keine Fenster, startet keine Codex-Instanz
und prüft diese Angaben nicht. Laufende Prozesse werden nur lesend abgefragt.
Weitere Varianten und Versuchsmatrix: [Plan](docs/PLAN.md).

## Daten und Bedeutung

Jeder persistierte Run hat `metadata.json`, `samples.jsonl`, `events.jsonl`,
`probes.csv`, `incidents.jsonl` und `summary.json`. JSONL enthält schema_version,
run_id, UTC und monotonic_ns; sequence ist die Reihenfolge der Übernahme im
Monitor. Quellzeit kann leicht von dieser Reihenfolge abweichen. CSV enthält
Probe-Zeiten und numerische Ergebnisse. Kein Netzwerkverkehr wird mitgeschnitten.

CPU ist systemweit in Prozent; Eigen- und Prozess-CPU beziehen sich auf einen
Kern (können >100 % sein). Disk/Netzwerk sind aggregierte Bytes und Bytes/s,
keine Verbindungen/Adressen. RAM-Verfügbarkeit ist kein Speicherdruck: auf
macOS wird zusätzlich der Kernelstatus abgefragt, sonst explizit unsupported.
Swap-in/out-Zähler sind unter Windows/OpenBSD (psutil <8) explizit unsupported.
Erstes CPU-/Raten-Sample ist null; Zählerreset oder fehlende Rechte ebenfalls.
Prozessgruppen werden alle 5 s erneuert, ihr Alter und übersprungene Prozesse
sind sichtbar. Nur feste Kategorien werden gespeichert, keine Namen oder PIDs.
Andere Prozesse mit mindestens 5 % eines Kerns werden zusammengefasst.
KiraBridge als Python-Prozess ist ohne Argumentabfrage möglicherweise nicht
eindeutig als KiraBridge erkennbar; das ist eine bewusste Datenschutzgrenze.

Summary: Median und nearest-rank p95 erfolgreicher Proben; alle Versuche separat,
Timeoutquote und Fehlerquote mit Nenner aller Versuche. Ein Timeout bedeutet, dass der Abschluss nicht innerhalb der monotonen
Deadline beobachtet wurde. Timeoutlaufzeiten enthalten auch Cleanup und sind zensierte Messungen. OS-Prozesserzeugung kann
nicht auf jeder Plattform unterbrochen werden; der Timeout ist keine harte
Garantie für die gesamte Walltime. Eigene CPU-Zeit umfasst Sampling, Writer,
Probe-Steuerung und Setup, **nicht** CPU-Zeit der Children. Beim `overhead`-Befehl
stehen alle Trial-Summaries auf stdout; nur die Bedingung logging erzeugt
Run-Dateien. Ausgabe für dauerhafte Auswertung bei Bedarf privat umleiten.

Sampling-Statistiken verwenden höchstens die letzten 3600 Samples, zusätzlich
werden Gesamtzahl und Lücken gezählt. Probelisten sind auf 10000 pro Run begrenzt.
Wandzeitabweichung und tatsächliche Sampleintervalle helfen Uhrsprünge oder
Abtastlücken zu erkennen. Monotone Werte verschiedener Run-IDs nicht subtrahieren.

## Blackbox und Datenschutz

Ringpuffer standardmäßig 120 **Records** (Samples und Probe-Ereignisse), also
bei Baselines nicht garantiert 120 Sekunden Vorlauf. Bei Probe-Timeout/-Fehler,
Abtastlücke >2 Intervalle oder `--marker` wird der Vorlauf in incidents.jsonl
kopiert und bis 10 Sekunden danach ergänzt. Überlappende Trigger werden in
einem Vorfall zusammengefasst, höchstens bis zum doppelten Nachlauf des ersten
Triggers. `post_window_complete` heißt Zeitfenster abgelaufen; es garantiert
keine lückenlose Abtastung. Vorzeitiger Stop wird als unvollständig markiert.

Vier Streams rotieren separat: Samples, Events, CSV, Incidents. Standard je
1 MiB + 3 Backups, zusammen höchstens 16 MiB, dazu je höchstens 64 KiB Metadaten
und Summary. `--max-bytes`, `--backups`, `--ring`, `--post` ändern die Grenzen.
Alte Teile eines Vorfalls können bei Rotation entfallen; Start/Ende und IDs
machen Ausschnitte nachvollziehbar. Keine unbegrenzte Vorfallliste im RAM.
Grenzen gelten **pro Run**; alte Run-Verzeichnisse bewusst selbst löschen.

Neue Run-Verzeichnisse 0700, Dateien 0600 unter POSIX. Bereits existierende
Elternverzeichnisse werden nicht umkonfiguriert. Keine Prompts, Secrets,
Terminalinhalte, argv, Umgebungen, Prozesspfade oder freien Fehlermeldungen.
Absolute Ausgabepfade erscheinen nur auf stdout; gespeicherte Summaries verwenden
nur den zufälligen Ordnernamen. Rohdaten können Nutzungszeiten/Last verraten:
`runs/` bleibt git-ignoriert. Keine automatischen Uploads. Vor Weitergabe prüfen.
Stromausfallfestigkeit wird nicht zugesagt (kein fsync pro Sample).

## Entwicklung und Forschungsstand

```sh
.venv/bin/python -m unittest discover -s tests -v
# Reproduzierbare numerische Forschungsmessung (ca. 4 Minuten auf diesem Mac):
.venv/bin/python scripts/measure_local.py
```

Die Forschungsmessung führt sechs 100er-Trials und zwei 60-s-Idle-Runs
sequenziell aus. Ein zusätzlicher privater Run-Ordner enthält report.json
(maximal 1 MiB), einschließlich Code-Commit und Dirty-Status. Standard-Runner
der CI prüfen macOS Intel, Linux (Python 3.9/3.13) und Windows-Ressourcenpfade;
Windows-Shell-Proben bleiben ausgenommen. Keine lokalen Rohdaten werden in CI
hochgeladen.

[Architektur/Phasen/Testplan](docs/PLAN.md), [Vergleichsrecherche](docs/RESEARCH.md),
[optionaler Ereignisvertrag](docs/EVENTS.md), [Ergebnisse](docs/RESULTS.md).
Die Ursachen in Desktop Commander sind Vergleichsmaterial, keine Diagnose von
KiraBridge. Ohne spätere Werkzeugereignisse kann dieser Monitor lokale Last und
Latenzen dokumentieren, aber Kommunikationsverluste oder falsches busy nicht
allein nachweisen. Mit 100 erfolgreichen Proben sind seltene Fehler weiter möglich.
