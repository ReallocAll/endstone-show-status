# Changelog

All notable changes to this project are documented here.

## [Unreleased]

## [0.2.2] - 2026-09-30

### Added

- Add the player-accessible `/showstatus` command with an Endstone `StepSlider` form.
- Add per-player TPS/MSPT/PING display intervals: continuous, 2, 3, 5, 10, 15, 30, or 60 seconds, plus disabled.
- Persist player preferences by UUID in `player_settings.json`.

### Changed

- Keep a single one-second status scheduler and throttle delivery per player instead of creating per-player tasks.
- Treat `tip_interval_ticks` as the fallback interval for players without a saved preference while `tip_enabled` remains the administrator-wide master switch.
- Preserve Endstone 0.11 compatibility.

## [0.2.1] - 2026-09-17

### Added

- Include Spark's rolling system CPU metric in status snapshots when available.

### Changed

- Pin the runtime dependency to Endstone 0.11.11 and retain Python 3.10 support.
