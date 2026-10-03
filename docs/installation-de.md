# Installation auf macOS

Das Projekt richtet die Codex-Belegung der MX Master 4 automatisch ein: Maustasten, Daumenrad, Actions Ring, sechs Ring-Kürzel und den Diktier-Shortcut. Voraussetzung sind eine bereits eingerichtete Maus in Options+, Python 3.9 oder neuer und die im [README](../README.md) aufgeführten App-Versionen. Öffne den Actions Ring einmal, damit der Plugin-Dienst erkannt werden kann.

## Vorschau und Installation

Lade das GitHub-Projekt herunter und entpacke es. Im Terminal im Projektordner:

```sh
./codex-mx plan
./codex-mx install --apply --restart-logitech
```

`plan` liest nur. Auch `install` ohne `--apply` zeigt nur eine Vorschau. Alternativ führt ein Doppelklick auf `Install.command` die Installation aus. Die normalen macOS-Freigaben für heruntergeladene Programme und gegebenenfalls das Beenden von Options+ erfolgen durch dich.

Options+ und der Logi Plugin Service werden kurz angehalten und anschließend wieder gestartet. Die ursprünglichen Dateien sowie vollständige SQLite-Snapshots von `settings.db` und `macros.db` einschließlich WAL-Daten werden lokal gesichert. Globale Mausprofile, andere Anwendungen, Zeigergeschwindigkeit und Scroll-Einstellungen werden erhalten; nur die Zielbelegungen im Codex-Profil werden ersetzt.

Beende Codex nach Abschluss deiner laufenden Chats vollständig mit Cmd+Q und öffne es erneut, damit die neuen Tastenkürzel sicher aktiv sind. Der Installer beendet Codex nicht.

## Belegung

| Bedienelement | Aktion |
| --- | --- |
| Vor-Taste | Enter zum Bestätigen oder Senden |
| Zurück-Taste | Diktieren, Ctrl+Shift+D |
| Gestentaste | Neuer Chat, dann Sprachchat starten |
| Mitteltaste | Zu einem Chat wechseln, der Aufmerksamkeit benötigt |
| Daumenrad links/rechts | Vorheriger/nächster Chat |
| Haptische Ring-Taste | Codex Actions Ring mit acht Aktionen |

Enter wirkt auf das aktuell fokussierte Element. Das Daumenrad folgt der Codex-Reihenfolge und begrenzt sich nicht auf laufende Chats. Die Gestentaste sendet Cmd+N, wartet 750 ms und sendet Ctrl+Shift+V. Ctrl+Shift+V allein schaltet den Sprachchat im aktuellen Chat um. Die Folge ist als native Smart Action gespeichert. Falls der neue Chat auf deinem Mac länger zum Öffnen braucht, kannst du die Wartezeit unter Options+ → Smart Actions ändern.

Im geprüften Codex-Build ist Diktieren standardmäßig unbelegt. Der Installer setzt `globalDictationSingleTap` auf Ctrl+Shift+D. Dieses Kürzel wird von Codex systemweit registriert. Bei fehlenden macOS-Freigaben öffne Codex → Einstellungen → Tastaturkürzel, suche den Diktier-Eintrag und setze dort das Kürzel; der native Editor fordert die benötigten Freigaben an.

Im Ring liegen Planmodus, Fast-Modus, Chat verzweigen, Denkaufwand erhöhen und verringern, Mikrofon umschalten, Review und Aufmerksamkeit. Die sechs zusätzlichen Kürzel stehen in der [Keybindings-Dokumentation](codex-keybindings.md).

## Rücknahme

Der Installer zeigt den Sicherungsordner an. Setze dessen absoluten Pfad ein:

```sh
./codex-mx restore --backup '/Pfad/zur/Sicherung'
./codex-mx restore --backup '/Pfad/zur/Sicherung' --apply --restart-logitech
```

Die Rücknahme erhält unabhängige Änderungen, die du später vorgenommen hast. Die beobachtete automatische Normalisierung der Smart Action durch Options+ wird erkannt: weggelassene Standardwerte und die Umwandlung der Entwickler-Kategorie. Nicht erkannte Änderungen bleiben Konflikte. Wurde eine verwaltete Belegung später geändert, meldet sie einen Konflikt und schreibt nichts. Sicherungen enthalten lokale Einstellungen; veröffentliche sie nicht auf GitHub.

Auch die Rücknahme prüft die App-Versionen. Nach einem Update auf eine noch ungeprüfte Version stoppt sie ebenfalls. Bewahre die Sicherung bis zur Prüfung dieser Version oder für eine sorgfältige manuelle Wiederherstellung auf.

## Entwicklungsstand

Version 0.1.2 ist experimentell, weil der automatische Installer interne Dateiformate verwendet. Der echte Ring-Import, die korrigierte Installation auf einem Mac, die von Logitech eingelesenen Daten und eine anschließend unveränderte Vorschau wurden geprüft. Schreibfehler, parallele Änderungen und Rücknahme sind mit separaten Testdateien geprüft. Die tatsächlichen Mausaktionen sowie Sprache und Diktieren müssen nach dem Codex-Neustart noch am Gerät bestätigt werden. Unbekannte App-Versionen werden vor Änderungen abgelehnt.

Für den manuellen Weg stehen das `.lp5`-Ringprofil und acht einzeln importierbare Smart Actions unter `assets/` bereit. Eine offizielle universelle Options+-Importdatei für alle physischen Tasten ist dieses Paket nicht.
