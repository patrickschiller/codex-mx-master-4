# Die Mausbelegung in 32 Sekunden

[Video als MP4 herunterladen](https://github.com/patrickschiller/codex-mx-master-4/releases/download/v0.1.3/codex-mx-master-4-demo.mp4) · [Animierte GIF ansehen](media/codex-mx-master-4-demo.gif) · [Zur Anleitung](installation-de.md)

Die Animation erklärt die Belegung der MX Master 4 für Codex auf macOS. Sie verwendet deutsche Texteinblendungen und hat keinen Ton. Maus und App sind vereinfachte Illustrationen; das Video enthält keine privaten Chats und zeigt keinen aufgezeichneten Test am Gerät.

## Textfassung

| Zeit | Gezeigte Funktion |
| --- | --- |
| 0–3 Sekunden | Überblick: Codex mit der MX Master 4 bedienen. Die Maus links und ein Beispielchat rechts zeigen, welche Taste welche Aktion auslöst. |
| 3–8 Sekunden | **Zurück-Taste → Diktieren starten.** `Ctrl+Shift+D` startet die Texteingabe per Sprache. Die gesprochenen Wörter erscheinen im Eingabefeld. Erneutes Drücken kann das Diktieren stoppen. |
| 8–13 Sekunden | **Obere Daumen-Seitentaste → Sprachchat starten.** `Ctrl+Shift+V` startet den Sprachchat im aktuellen Chat. Erneutes Drücken kann einen aktiven Sprachchat stoppen. |
| 13–18 Sekunden | **Vor-Taste → Enter.** Die Taste bestätigt ein fokussiertes Bestätigungsfeld oder sendet den Text, wenn das Chat-Eingabefeld den Fokus hat. |
| 18–23 Sekunden | **Daumenrad → vorheriger oder nächster Chat.** `Cmd+Option+Links/Rechts` folgt der Navigationsreihenfolge von Codex. **Mittlere Taste → Chat mit Handlungsbedarf**, über `Cmd+Option+A`. |
| 23–29 Sekunden | **Haptische Daumenfläche → Actions Ring anzeigen.** Der Ring bietet Planmodus, Fast-Modus, Chat abzweigen, Denkleistung erhöhen, Denkleistung verringern, Mikrofon stummschalten, Review und Handlungsbedarf. |
| 29–32 Sekunden | Die Belegung im Überblick: Diktieren, Sprachchat, Enter, Chatwechsel und Actions Ring direkt an der Maus. |

Die Mausbelegung gilt, während Codex die aktive Anwendung ist. Das Daumenrad navigiert zwischen Chats gemäß Codex-Reihenfolge; es filtert keine laufenden Sessions. Die hinterlegten Diktier- und Sprachkürzel schalten die jeweilige Funktion um. Welche Aktion verfügbar ist, hängt vom aktuellen Codex-Fenster und Zustand ab.

## Belegung und Tastenkürzel

| Bedienelement | Aktion | Tastenkürzel |
| --- | --- | --- |
| Zurück-Taste | Diktieren starten | `Ctrl+Shift+D` |
| Obere Daumen-Seitentaste | Sprachchat starten im aktuellen Chat | `Ctrl+Shift+V` |
| Vor-Taste | Bestätigen oder senden bei passendem Fokus | `Enter` |
| Mittlere Taste | Chat mit Handlungsbedarf öffnen | `Cmd+Option+A` |
| Daumenrad links / rechts | Vorheriger / nächster Chat | `Cmd+Option+Links/Rechts` |
| Haptische Daumenfläche | Actions Ring anzeigen | Native Options+-Aktion |

| Aktion im Ring | Tastenkürzel |
| --- | --- |
| Planmodus | `Ctrl+Option+Shift+P` |
| Fast-Modus | `Ctrl+Option+Shift+F` |
| Chat abzweigen | `Ctrl+Option+Shift+B` |
| Denkleistung erhöhen | `Ctrl+Option+Shift+Pfeil hoch` |
| Denkleistung verringern | `Ctrl+Option+Shift+Pfeil runter` |
| Mikrofon stummschalten / Stummschaltung aufheben | `Ctrl+Option+Shift+M` |
| Review | `Ctrl+Shift+G` |
| Handlungsbedarf | `Cmd+Option+A` |

Die Animation erklärt die konfigurierte Logik. Hinweise zur Installation, zu erforderlichen Berechtigungen und zur Aktivierung neuer Codex-Kürzel stehen in der [Installationsanleitung](installation-de.md).

## Animation neu erzeugen

Das optionale Werkzeug [tools/render_demo.py](../tools/render_demo.py) zeichnet alle Szenen selbst. Es liest keine Bildschirmaufnahme oder persönlichen Einstellungen. Benötigt werden Python mit Pillow, FFmpeg mit `libx264` sowie Arial oder DejaVu Sans. Geprüft wurde die Ausgabe mit Pillow 12.3.0 und FFmpeg 9.0.2; diese Werkzeuge werden ausschließlich zum Erstellen der Demo benötigt.

Im Projektordner:

```sh
python3 tools/render_demo.py \
  --mp4 ../codex-mx-master-4-demo.mp4 \
  --gif docs/media/codex-mx-master-4-demo.gif
```

Die MP4 hat 1280 × 720 Pixel, 24 Bilder pro Sekunde und H.264 mit `yuv420p`. Die GIF-Vorschau hat 960 × 540 Pixel und 12 Bilder pro Sekunde. Beide dauern 32 Sekunden. Mit `--previews /Pfad/zum/Vorschauordner` lassen sich zusätzlich sieben Szenenbilder für die Sichtprüfung speichern. Das README zeigt die GIF; die verlinkte MP4 liegt als Asset beim Release v0.1.3.
