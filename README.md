# kobo2Calibre

Embed highlights from Kobo device into Calibre and wise-versa.

Supports kepubs created with the KTE plugin or native Calibre kepubify (version 8+).

## Installation

1. Download the latest `Kobo2Calibre.zip` from the [releases page](https://github.com/degiz/kobo2calibre/releases)
2. In Calibre, go to **Preferences** → **Plugins** → **Load plugin from file**
3. Select the downloaded zip file and restart Calibre
4. Add the plugin button to your toolbar: **Preferences** → **Toolbars** → drag the plugin to `toolbar when a device is connected`

## Usage

1. Connect your Kobo device to your computer
2. In Calibre, select a book
3. Click the kobo2Calibre button in the toolbar
4. Transfer highlights

## Configuration

When using the plugin, you'll see a checkbox to select your kepub format:

- **New format** (recommended): For kepubs created with native Calibre kepubify (Calibre 8+)
- **Old format**: For kepubs created with the KTE plugin

**Not sure which to choose?** If you're using Calibre 8 or newer and haven't installed the KTE plugin separately, use the new format.


## AI Agent Development

This project supports AI coding agents (Claude Code, Cursor, etc.). See `AGENTS.md` for technical reference including commands, code patterns, and troubleshooting.

Available skills in `.agents/skills/`:
- `debug-highlights` - Diagnose highlight conversion issues
- `clear-highlights` - Remove highlights from databases

## Support

Found a bug or have a question? [Open an issue](https://github.com/degiz/kobo2calibre/issues) on GitHub.

## Screenshots

![Screenshot](/screenshots/image.jpg "Screenshot")
