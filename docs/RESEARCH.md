# Vergleichsrecherche und Hypothesen

Auftrag: monitor-codex-development-brief-20261029. Primärquellen am 2026-10-30
gelesen. Beschreibungen und Tests der Autoren sind Vergleichsevidenz für
Desktop Commander; sie wurden hier nicht unabhängig reproduziert.

| Primärquelle | Dokumentierter Mechanismus | Ableitung für dieses Projekt |
| --- | --- | --- |
| [PR 766](https://github.com/wonderwhy-er/DesktopCommanderMCP/pull/766) | Begrenzt Werkzeugwartezeiten; inkrementelles Auslesen und günstigere Eviction großer Ausgaben. Titel nennt 60 s, aktueller Beschreibungstext 50 s Obergrenze. | Eigene präzise Deadline; keine Ausgabe puffern; Prozessende statt Textmuster auswerten. |
| [PR 752](https://github.com/wonderwhy-er/DesktopCommanderMCP/pull/752) | Flüchtiges Wecksignal konnte bei Disconnect verloren gehen, dauerhafter Auftrag blieb pending; Reconnect scannt lebende Aufträge. | Start, Annahme und Ergebnis getrennt betrachten; ein schneller lokaler Test beweist keine Zustellung. |
| [PR 679](https://github.com/wonderwhy-er/DesktopCommanderMCP/pull/679) | Mehrere Prozesse konnten Konfiguration überschreiben; koordinierte Mutationen und atomare Writes. | Keine gemeinsame Konfiguration schreiben; jeder Run eigener Ordner. Instanzenzahl später als Faktor. |
| [PR 866](https://github.com/wonderwhy-er/DesktopCommanderMCP/pull/866) | Pagination-Tests warteten feste Zeiten und lasen vor tatsächlicher Ausgabe. | Auf beobachtetes Ereignis mit Deadline warten. |
| [PR 947](https://github.com/wonderwhy-er/DesktopCommanderMCP/pull/947) | Repro-Tests berücksichtigen langsamen Shellstart und stoppen ihre Children auch bei Fehlschlag. | Startkosten mitmessen; Timeout und Cleanup testen. |

Aus diesen Quellen folgt **keine nachgewiesene Ursache in KiraBridge**.
Insbesondere darf eine Lastspitze nicht als Beweis für Kommunikationsverlust
oder ein fehlendes ACK als Beweis für einen ausgebliebenen Prozess gelten.
Der Monitor kann lokale Verzögerungen und Ressourcenzustände belegen;
Kommunikationshypothesen brauchen später externe Ereignisse mit gemeinsamen IDs.
PR-Status und Implementierungen können sich ändern; keine Codeübernahme.
