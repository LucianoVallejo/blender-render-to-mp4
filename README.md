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
- Adds **View > Viewport Render Animation to MP4** for one-click playblasts
- Temporarily adds `_playblast` to the output path while a playblast runs,
  then restores the original path automatically
- Keeps playblast frames and videos separate from final-render output without
  requiring you to rename the output path manually
- Optional macOS notification on success or failure
- Toggle on/off anytime from the add-on preferences, no need to uninstall

## Requirements

- Blender 4.2+ (uses the Extensions system; see [Install](#install) below)
- [`ffmpeg`](https://ffmpeg.org/) installed on your Mac (`brew install ffmpeg`
  if you don't have it yet)
- macOS (the notification feature uses `osascript`; the conversion itself
  works cross-platform as long as `ffmpeg` is found)

## Install

This repo is set up as a **Blender Extensions repository**, so Blender can
install and update it directly — no manual file downloads after the first
setup.

1. In Blender: `Edit > Preferences > Get Extensions > Repositories`
2. Click **+ Add Repository** > **Add Remote Repository**
3. Paste this URL:
   ```
   https://raw.githubusercontent.com/LucianoVallejo/blender-render-to-mp4/main/repo/index.json
   ```
4. Back in the Get Extensions tab, find **Render to MP4** and click
   **Install**.

From then on, whenever this repo is updated, Blender's Get Extensions tab
will show an available update for it — no reinstalling by hand.

Once installed, open the add-on's preferences (`Preferences > Add-ons >
Render to MP4`) to:
   - Confirm it's **Enabled**
   - Set a custom **ffmpeg path** if auto-detection doesn't find yours
   - Toggle the **macOS notification** on/off

## Playblast to MP4

In a 3D View, choose:

`View > Viewport Render Animation to MP4`

The add-on runs Blender's native viewport animation render, using the active
viewport, shading, overlays, resolution, preview range, frame step, and scene
FPS. It temporarily redirects the Output path by adding `_playblast`, creates
the MP4, and then restores the exact original path.

Examples:

- `//renders/shot_010/` becomes `//renders/shot_010_playblast/`
- `//renders/shot_010/beauty_` becomes
  `//renders/shot_010/beauty_playblast_`

The resulting video is named from that temporary path, such as
`shot_010_playblast.mp4` or `beauty_playblast.mp4`. Only frames written by the
current playblast are encoded. If the playblast is cancelled or incomplete,
no MP4 is created. The image sequence is kept.

The playblast command expects an image-sequence output format such as PNG,
JPEG, EXR, or TIFF. If the scene already outputs a movie format, use Blender's
normal Viewport Render Animation command instead. The wrapper temporarily
enables **Overwrite** so repeat playblasts refresh every frame, then restores
the original Overwrite setting together with the original output path.

### Manual install (fallback)

If you'd rather not add a remote repository, you can still install it
manually: download the latest `.zip` from this repo's
[Releases](../../releases) (or from `repo/render_to_mp4.zip` in this repo),
then in Blender go to `Edit > Preferences > Get Extensions > Install from
Disk...` and select the zip. You won't get automatic update notifications
this way.

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

Viewport playblasts use Blender's separate `render.opengl` job and do not use
the normal completion handler. The add-on's playblast operator launches that
native job, waits for its own job to finish, restores the original Output
path, and converts the exact frame list from that run.

## Known limitations

- Only triggers on animations/sequences, not single-frame stills
- Assumes a consistent numeric frame padding across the sequence
- If `ffmpeg` isn't found anywhere (auto-detected or manually set), the
  conversion is skipped and a message is printed to Blender's console

## Publishing an update

To ship a new version:

1. Edit `render_to_mp4/__init__.py` with your change
2. Bump `version` in `render_to_mp4/blender_manifest.toml`
3. Commit and push to `main`

A GitHub Actions workflow (`.github/workflows/build-repo.yml`) automatically
repackages the extension and rebuilds `repo/index.json` on every push, and
commits the result back to the repo — so the moment the workflow finishes,
anyone subscribed to this repository in Blender sees the update available.

The workflow doesn't depend on Blender itself, or any third-party action
that installs it — `scripts/generate_repo.py` builds the zip and computes
the `index.json` fields (hash, size, manifest data) using only Python's
standard library, matching the schema Blender's own extension platform
uses. The only actions involved are GitHub's own official
`actions/checkout` and `actions/setup-python`.

## Roadmap ideas

- [ ] Auto-move the resulting `.mp4` into an Eagle-watched folder
- [ ] Configurable video codec / container (currently hardcoded to H.264 mp4)
- [ ] Whole-queue-completion hook, not just per-render

## License

MIT — see [LICENSE](LICENSE).
