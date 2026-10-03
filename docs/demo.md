# The mouse controls in 32 seconds

[Download the MP4 video](https://github.com/patrickschiller/codex-mx-master-4/releases/download/v0.1.3/codex-mx-master-4-demo.mp4) · [View the animated GIF](media/codex-mx-master-4-demo.gif) · [Installation guide in German](installation-de.md)

The animation explains the MX Master 4 controls for Codex on macOS. All captions are in English, and the video has no sound. The mouse and app are simplified illustrations; the video contains no private chats or recorded hardware test.

## Transcript

| Time | Function shown |
| --- | --- |
| 0–3 seconds | Overview: control Codex with the MX Master 4. The mouse on the left and a sample chat on the right show which control triggers each action. |
| 3–8 seconds | **Back button → Start dictation.** `Ctrl+Shift+D` starts speech-to-text input. Spoken words appear in the composer. Pressing again can stop dictation. |
| 8–13 seconds | **Upper thumb-side button → Start voice chat.** `Ctrl+Shift+V` starts voice in the current chat. Pressing again can stop an active voice chat. |
| 13–18 seconds | **Forward button → Enter.** The button confirms a focused confirmation control or sends text when the chat composer has focus. |
| 18–23 seconds | **Thumb wheel → Previous or next chat.** `Cmd+Option+Left/Right` follows Codex's navigation order. **Middle button → Chat needing attention**, using `Cmd+Option+A`. |
| 23–29 seconds | **Haptic thumb pad → Open Actions Ring.** The ring offers Plan mode, Fast mode, Fork chat, Increase reasoning effort, Decrease reasoning effort, Mute microphone, Review and Needs attention. |
| 29–32 seconds | The controls at a glance: dictation, voice chat, Enter, chat navigation and Actions Ring, all on the mouse. |

The mouse assignments apply while Codex is the active application. The thumb wheel follows Codex's chat order; it does not filter to running sessions. The dictation and voice shortcuts toggle their respective functions. Action availability depends on the current Codex screen and state.

## Controls and shortcuts

| Control | Action | Shortcut |
| --- | --- | --- |
| Back button | Start dictation | `Ctrl+Shift+D` |
| Upper thumb-side button | Start voice chat in the current chat | `Ctrl+Shift+V` |
| Forward button | Confirm or send when the relevant control has focus | `Enter` |
| Middle button | Open a chat needing attention | `Cmd+Option+A` |
| Thumb wheel left / right | Previous / next chat | `Cmd+Option+Left/Right` |
| Haptic thumb pad | Open Actions Ring | Native Options+ action |

| Ring action | Shortcut |
| --- | --- |
| Plan mode | `Ctrl+Option+Shift+P` |
| Fast mode | `Ctrl+Option+Shift+F` |
| Fork chat | `Ctrl+Option+Shift+B` |
| Increase reasoning effort | `Ctrl+Option+Shift+Up` |
| Decrease reasoning effort | `Ctrl+Option+Shift+Down` |
| Mute / unmute microphone | `Ctrl+Option+Shift+M` |
| Review | `Ctrl+Shift+G` |
| Needs attention | `Cmd+Option+A` |

The animation explains the configured behavior. See the [installation guide in German](installation-de.md) for setup, required permissions and activation of newly installed Codex shortcuts.

## Recreate the animation

The optional [tools/render_demo.py](../tools/render_demo.py) script draws every scene itself. It does not read screen recordings or personal settings. It requires Python with Pillow, FFmpeg with `libx264`, and Arial or DejaVu Sans. Output has been checked with Pillow 12.3.0 and FFmpeg 9.0.2; these tools are needed only to create the demo.

From the project directory:

```sh
python3 tools/render_demo.py \
  --mp4 ../codex-mx-master-4-demo.mp4 \
  --gif docs/media/codex-mx-master-4-demo.gif
```

The MP4 is 1280 × 720 pixels at 24 frames per second, encoded as H.264 with `yuv420p`. The GIF preview is 960 × 540 pixels at 12 frames per second. Both last 32 seconds. Use `--previews /path/to/preview-directory` to save seven scene images for visual inspection. The README displays the GIF; the linked MP4 is an asset on release v0.1.3.
