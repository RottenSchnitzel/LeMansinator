# LeMansinator

*A tiny Windows tool that plays dramatic music at the start of Le Mans races in iRacing.*

Specifically: it plays **“Also sprach Zarathustra”** (or any audio file you want) at a configurable moment during the rolling start — because if you’re going to crawl behind a pace car for half a lap, you might as well make it cinematic.

This is completely unnecessary. That’s the point.

---

## What is this?

LeMansinator connects to iRacing’s telemetry and waits for a **Le Mans race session**.  
When the *“get on grid”* countdown reaches zero, it waits a user-defined number of seconds and then plays your chosen audio file **once**.

The idea is simple:  
the pace car speed is always the same → the timing is predictable → you can sync the music perfectly.

---

## Features

- Detects **Le Mans** tracks (all configs)
- Arms only for **race sessions** (no practice / quali nonsense)
- Configurable delay (0–300 s) after grid countdown ends
- Volume control + test playback
- Uses any `.wav` or `.mp3`
- Fires **once per race start**
- Saves your settings automatically
- Small window, no bloat

---

## Download

**[Download latest Windows .exe](../../releases/latest)**

No installer, no setup wizard.  
Download → run → done.

---

## Running from source

If you prefer Python over mysterious executables:

### Requirements

- Python 3.8+
- Windows
- iRacing (running)

### Install & run

```bash
git clone https://github.com/RottenSchnitzel/LeMansinator.git
cd LeMansinator

pip install -r requirements.txt
python le_mans_audio_trigger.py
