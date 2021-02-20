# FoundryToEncounter

Utility to convert Foundry modules/worlds to an EncounterPlus module.
- Scenes are converted to maps with an encounter for assinged tokens.
- Journal entries and Roll tables are converted to pages.
- Playlists are also converted into pages.
- Optionally, actors and items can be converted into compendium content.
- The follow features require [FFmpeg](https://ffmpeg.org) to be installed on your system
    - Convert video maps to a compatible format
    - Convert video tiles to sprite sheets
    - Convert sounds to a compatible format

## App Version

Download the [latest release](https://github.com/rrgeorge/FoundryToEncounter/releases/latest) for macOS or Windows

## Commandline Version

### Install required modules

    pip install -r requirements.txt

### Usage

    usage: foundrytoencounter.py [-h] [-o OUTPUT] [srcfile] [-gui]

    Converts Foundry Modules/Worlds to EncounterPlus Modules

    positional arguments:
      srcfile     foundry file to convert

    optional arguments:
      -h, --help  show this help message and exit
      -o OUTPUT   output into given output (default: [name].module)
      -c          create compendium content with actors and items
      -j          convert WebP to JPG instead of PNG
      -gui        use graphical interface

### Examples

Convert a foundry module/world to an EncounterPlus module:

    python3 foundrytoencounter.py foundrymodule.zip

Or to include an compendium content from Actors and Items:

    python3 foundrytoencounter.py -c foundrymodule.zip

## Support

If you enjoy this project, please consider [Sponsoring Me](https://github.com/sponsors/rrgeorge)
