# Changelog

All notable changes to this project are documented in this file.

## [1.1.0] - 2026-09-19

### Fixed

- Output paths using Blender 5 file-output template variables
  (`{scene_name}`, `{camera_name}`, `{blend_name}`, ...) — as used by
  Blender Render Queue — were read literally, so the add-on looked for a
  folder named `{scene_name}` and silently skipped. The handler now resolves
  the real on-disk path via `RenderSettings.frame_path()`, the same way
  Blender does when writing frames.
- Frame padding, extension and file prefix are now derived from the actual
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
