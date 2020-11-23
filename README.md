# FoundryToEncounter

Utility to convert Foundry modules/worlds to an EncounterPlus module.
- Scenes are converted to maps with an encounter for assinged tokens.
- Journal entries and Roll tables are converted to pages.
- Playlists are also converted into pages.
- Optionally, actors and items can be converted into compendium content.

## Install required modules

    pip install -r requirements.txt

## Usage

    usage: foundrytoencounter.py [-h] [-o OUTPUT] [srcfile] [-gui]

    Converts Foundry Modules/Worlds to EncounterPlus Modules

    positional arguments:
      srcfile     foundry file to convert

    optional arguments:
      -h, --help  show this help message and exit
      -o OUTPUT   output into given output (default: [name].module)
      -c          create compendium content with actors and items
      -gui        use graphical interface

## Examples

Convert a foundry module/world to an EncounterPlus module:

    python3 foundrytoencounter.py foundrymodule.zip

Or to include an compendium content from Actors and Items:

    python3 foundrytoencounter.py -c foundrymodule.zip

