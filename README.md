# ScreenCoverDesktop

App-agnostic clone of [YouTubeScreenCover](https://github.com/stygian-uk/YouTubeScreenCover).
The browser extension only works on YouTube; this version is a system-tray app
that overlays anything on your desktop — Netflix in any browser, VLC, Twitch,
streaming apps, screenshares.

## Features

- **Top / bottom black bars** — drag to move, drag edges to resize, opacity slider
- **Mosaic regions** — pixelates whatever is behind them (~30 fps), intensity slider
- **Lock mode** — covers become click-through so they don't intercept your mouse
- **Tray icon** — add / remove / hide covers, quit
- **Global hotkeys** (when `pynput` is installed):
  - `Ctrl+Alt+H` — toggle show/hide all
  - `Ctrl+Alt+L` — toggle lock (click-through)
  - `Ctrl+Alt+M` — add a new mosaic region

## Run

```
pip install -r requirements.txt
python screen_cover.py
```

## How it works

The mosaic excludes itself from screen capture using the Win32
`SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` flag (Windows 10 2004+).
That lets the cover repeatedly grab the desktop area behind it without
feedback-looping its own pixels. Each frame is downscaled then upscaled with
nearest-neighbour to produce the chunky-block mosaic effect.

## Build a single-file .exe

```
pip install pyinstaller
pyinstaller --onefile --noconsole --name ScreenCoverDesktop screen_cover.py
```
