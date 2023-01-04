# kobo2Calibre

Embed highlights from Kobo device in Calibre book. Tested on the books converted using [calibre-kobo-driver](https://github.com/jgoguen/calibre-kobo-driver). Books converted using a different tool will most probably not work.

The plugin will:

- import your highlights from the Kobo device DB
- try to match the highlights with books from your Calibre library
- insert highlights into the Calibre database so that you can further edit them using a fantastic Calibre book viewer

# Installation as Calibre plugin

Check the releases section, and download the latest `Kobo2Calibre.zip`. Install it as any other Calibre plugin. Make sure to add the plugin to `toolbar when a device is connected`.

# Installation for CLI usage

You can use `poetry install` to install all the dependencies:

```bash
poetry update && poetry install
```

## Usage of CLI

**Warning: this script is in the alpha stage; please back up your Calibre library before using it!**

Example:

```bash
poetry run python kobo2calibre.py {PATH_TO_KOBO_DEVICE} {PATH_TO_CALIBRE_LIBRARY}
```

For the complete list of arguments run:

```bash
poetry run python kobo2calibre.py --help
```

# Screenshots

![Kobo screenshot](/screenshots/screen_kobo.png "Kobo screenshot")
![Calibre screenshot](/screenshots/screen_calibre.png "Calibre screenshot")
