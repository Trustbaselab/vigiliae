# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **igiliae/watchdog.py** — looks for work that is stuck, looping, waiting
  on a human, or running without a heartbeat. Read-only by design: it reports,
  it does not act. Run it standalone with python -m vigiliae.watchdog
  (--json for machine output, exit code 1 when something needs a human).
- **.env support** — config.py now loads .env from the repo root or the
  current working directory. Real environment variables still win.

### Fixed
- config.py documented .env usage but never read the file, so every
  setting was silently ignored unless manually exported.

### Docs
- Chinese README aligned with English: split Contributing/License, added
  Acknowledgements.

## [0.1.0] - 2026-10-27

Initial public release.
