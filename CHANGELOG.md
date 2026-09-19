# Changelog

All notable changes to this project are documented in this file.

## [1.2.0] - 2026-09-19

### Fixed

- Handlers are now `@persistent`. Blender clears `bpy.app.handlers` every
  time a .blend file is loaded, so in a background render
  (`blender -b file.blend ...`) — which is how Blender Render Queue and every
  other queue tool run Blender — the add-on's handler was registered at
  startup and then silently dropped when the file opened. This is the actual
  reason queue renders never produced a video; the UI path only worked
  because the file was already open when the add-on registered.

### Added

- Render queue support with zero configuration. Tools such as Blender Render
  Queue drive Blender frame by frame from their own script, so Blender's
  `render_complete` handler never sees a whole sequence. The add-on now also
  listens to `render_write` in background sessions to remember where frames
  are going, and converts the sequence once when the background Blender
  process exits. Normal renders started from the Blender UI keep using
  `render_complete` as before.
- `render.to_mp4_now` operator to trigger the conversion explicitly from a
  script (e.g. a queue tool's post-render Python expression:
  `bpy.ops.render.to_mp4_now()`). Also exposed as `convert_scene(scene, force=True)`.

### Changed

- The ffmpeg `-start_number` is now taken from the lowest-numbered frame on
  disk instead of `scene.frame_start`, so a queue tool that alters the scene
  range per frame no longer produces a truncated video.
- Conversion is skipped when the same folder was already converted in this
  session, so the two hooks never encode the same sequence twice.

## [1.1.0] - 2026-09-19

### Fixed

- Output paths using Blender 5 file-output template variables
  (`{scene_name}`, `{camera_name}`, `{blend_name}`, ...) — as used by
  Blender Render Queue — were read literally, so the add-on looked for a
  folder named `{scene_name}` and silently skipped. The handler now resolves
  the real on-disk path via `RenderSettings.frame_path()`, the same way
  Blender does when writing frames.
- Frame padding, extension and file pkefix are now derived from the actual
  frame filename instead of a hard-coded format map, so every image format
  Blender can write to a sequence (including multilayer EXR) is handled.

### Changed

- When the output filename prefix is empty (frames are just numbers inside
  a per-scene/per-camera folder), the `.mp4` is named after that folder
  instead of the `.blend` file.

## [1.0.1] - 2026-09-19

### Changed

- Notification title now includes the version number — a small, visible
  test change to confirm the self-updating extension repository actually
  delivers updates end to end

## [Unreleased]

### Changed

- Restructured as a proper Blender Extension package
  (`render_to_mp4/blender_manifest.toml` + `__init__.py`) instead of a
  single loose `.py` file
- Added a GitHub Actions workflow that rebuilds `repo/index.json` on every
  push, turning this repo into a self-hosted Blender Extensions repository
  that Blender can subscribe to and pull updates from directly
- `scripts/generate_repo.py` builds the zip and `index.json` with only the
  Python standard library — no dependency on Blender itself or a
  third-party action to install it in CI
- README now documents subscribing via `Get Extensions > Repositories` and
  publishing new versions

## [1.0.0] - 2026-09-19

### Added

- Initial release
- `render_complete` handler that converts a rendered image sequence to `.mp4`
  via `ffmpeg`
- Auto-detection of `ffmpeg` binary location (Homebrew Apple Silicon/Intel,
  `/usr/bin`)
- Auto-detection of frame padding from rendered file names
- Add-on preferences panel: enable/disable, custom `ffmpeg` path, macOS
  notification toggle
- Skips single-frame stills and sequences already rendered directly to video
