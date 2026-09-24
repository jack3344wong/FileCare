# FileCare

<div align="center">

**Disk Space Analysis, File Management & Local Search Tool for Windows**

[![Version](https://img.shields.io/badge/version-1.2.0-4a90e2.svg)](CHANGES.md)
[![Python](https://img.shields.io/badge/release%20runtime-Python%203.8-blue.svg)](requirements-win7.txt)
[![Platform](https://img.shields.io/badge/Windows-7%20SP1%20x64%2B-lightgrey.svg)](packaging/README.md)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

## Overview

FileCare is a local Windows file management tool designed for users who want to intuitively visualize disk usage, quickly locate files, and safely clean up space. Both filename and document content indexes are stored locally — no file content is ever uploaded.

## Key Features

- **File Management**: Browse, preview, copy paths, and safely delete files
- **Large File Cleanup**: Analyze large files and folders with actionable cleanup suggestions
- **Space Visualization**: Interactive Treemap view of files and folders with drill-down navigation
- **Quick Search**: Fully indexed disk directory entries with wildcard, format, and path filtering
- **Search Result Actions**: Open with default app, choose app, copy, cut, or open containing folder
- **Content Search**: Local full-text search across PDF, Word, Excel, PowerPoint, RTF, and common text files
- **Recycle Bin Management**: View, restore, or permanently delete items from the software recycle bin

## Installation for End Users

Download `FileCare-Setup-1.2.0.exe` from [GitHub Releases](https://github.com/jack3344wong/FileCare/releases), double-click to launch the installer, and follow the wizard. No Python or other runtime is required.

The installer offers the following options:

- Create a desktop shortcut
- Create a Start Menu folder with launch and uninstall entries

During installation, a borderless animated card demonstrates the scanning effect, and an initial filename index is built within approximately 20 seconds under the current logged-in user. The application continues completing the remaining index in the background after first launch.

## System Requirements

- Windows 7 SP1 64-bit or later 64-bit Windows
- At least 4 GB RAM recommended
- Windows 7 without SP1 and 32-bit Windows are not supported

## Running from Source

For development, we recommend 64-bit Python 3.8.10 to match the release build:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-win7.txt
python src\main.py
```

For daily development with other Python versions, install `requirements.txt`. The final release must use the pinned versions in `requirements-win7.txt`.

## Testing

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python test_win7_compatibility.py
python test_quick_search_completeness.py
python test_fulltext_search.py
python test_ui_smoke.py
```

Tests do not delete real user files; UI smoke tests use isolated temporary recycle bins and test user directories.

## Building the Installer

> **Inno Setup 7 is required.** Inno Setup 6 cannot compile this script: it uses
> the `NativeInt` type, which only exists in Inno Setup 7.

```powershell
python -m PyInstaller --clean --noconfirm packaging\FileCare.spec
& "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe" packaging\FileCare.iss
```

The generated installer is located at `installer-output\FileCare-Setup-<version>.exe`.
For the complete Win7 release environment and acceptance criteria, see [packaging/README.md](packaging/README.md).

## Releasing

Pushing a `vX.Y.Z` tag builds the portable bundle and the installer, then publishes
both to GitHub Releases (see `.github/workflows/release.yml`).

Two things are load-bearing for the in-app updater, and the workflow verifies/fails on both:

- The tag must match `APP_VERSION` in `src/version.py` (and `MyAppVersion` in
  `packaging/FileCare.iss`). Run `python tools/check_release_version.py` before tagging.
- The installer asset must be named `FileCare-Setup-<version>.exe` — that exact
  pattern is what the updater looks for on the release.

```powershell
python tools/check_release_version.py
git tag v1.3.0
git push origin v1.3.0
```

Release notes are taken from `CHANGES.md`, so keep a `## vX.Y.Z` section for each release.
Installed copies find the update via **设置 → 高级设置 → 立即检查更新** (or the tray menu).

## Project Structure

```text
src/                    Application source code
assets/                 Icons and installation animation resources
packaging/              PyInstaller and Inno Setup configuration
tools/                  Helper tools for reproducible resource generation
test_*.py               Functional and compatibility regression tests
requirements.txt        Development dependencies
requirements-win7.txt   Win7 release pinned dependencies
```

## Security & Privacy

- Index databases are stored in the current user's `~/.diskwise/` directory
- Scanning does not automatically delete files
- Permanent deletion requires explicit user confirmation and is irreversible
- Cloud drives, system directories, and program directories display additional risk warnings

## License

This project is licensed under the [MIT License](LICENSE). Issues and improvement suggestions can be submitted via GitHub Issues.
