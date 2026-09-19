# Render to MP4

A small Blender add-on that watches for the end of a render and automatically
converts the rendered image sequence into an `.mp4` file, saved in the same
folder — using `ffmpeg` under the hood.

Built to pair with [Blender Render Queue](https://blender-render-queue.com/)
or any other queue tool, since it hooks into Blender's own
`render_complete` handler rather than any particular render manager. It fires
no matter what launched the render.

## Features

- Converts the just-rendered PNG/JPEG/EXR/TIFF/BMP sequence to `.mp4`
  (H.264, `yuv420p`) automatically when rendering finishes
- Skips single still-frame renders (only triggers on sequences/animations)
- Skips gracefully if Blender already rendered directly to a video format
- Auto-detects frame padding (`0001`, `00001`, etc.) from the rendered files
- Auto-detects `ffmpeg` in common install locations (Homebrew on Apple
  Silicon/Intel, `/usr/bin`), or you can point it at a specific binary
- Uses the scene's own render FPS automatically (a 25fps scene produces a
  25fps mp4, no configuration needed)
- Optional macOS notification on success or failure
- Toggle on/off anytime from the add-on preferences, no need to uninstall

## Requirements

- Blender 3.0+
- [`ffmpeg`](https://ffmpeg.org/) installed on your Mac (`brew install ffmpeg`
  if you don't have it yet)
- macOS (the notification feature uses `osascript`; the conversion itself
  works cross-platform as long as `ffmpeg` is found)

## Install

1. Download `render_to_mp4.py` from this repo (or clone it).
2. In Blender: `Edit > Preferences > Add-ons > Install...`
3. Select `render_to_mp4.py` and enable the checkbox next to
   **Render to MP4** in the add-on list.
4. Open the add-on's preferences (click the arrow to expand it) to:
   - Confirm it's **Enabled**
   - Set a custom **ffmpeg path** if auto-detection doesn't find yours
   - Toggle the **macOS notification** on/off

## How it works

Blender fires a `render_complete` handler after every render, regardless of
whether it was started manually, from a script, or by an external render
queue tool. This add-on hooks into that handler, looks at the render output
settings to figure out the file pattern and frame padding, and runs:

```
ffmpeg -y -framerate <fps> -start_number <first_frame> \
  -i <output_pattern> -c:v libx264 -pix_fmt yuv420p <output>.mp4
```

The resulting `.mp4` is written into the same folder as the rendered
sequence, named after the output filename prefix (or the `.blend` file name
if that's empty).

## Known limitations

- Only triggers on animations/sequences, not single-frame stills
- Assumes a consistent numeric frame padding across the sequence
- If `ffmpeg` isn't found anywhere (auto-detected or manually set), the
  conversion is skipped and a message is printed to Blender's console

## Roadmap ideas

- [ ] Auto-move the resulting `.mp4` into an Eagle-watched folder
- [ ] Configurable video codec / container (currently hardcoded to H.264 mp4)
- [ ] Whole-queue-completion hook, not just per-render

## License

MIT — see [LICENSE](LICENSE).
