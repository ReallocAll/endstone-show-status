# Changelog

## 0.3.0 (2026-11-05)

- Split the public HTTP API into [endstone-status-api](https://github.com/ReallocAll/endstone-status-api).
- Retain the in-game HUD, form, and UUID-based preferences; remove the web UI, legacy endpoints, HTTP/auth/security collectors, system metrics, Spark dependency, and irrelevant configuration.
- Read TPS/MSPT directly from Endstone; use a dedicated, strict `hud.toml` configuration.
- Preserve existing player settings in their original location. No old HTTP API compatibility.

## Earlier releases

The historical changelog is available in Git history and the existing GitHub releases.
