# Changelog

All notable changes to this project are documented in this file.

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
