# FoundryToEncounter

Utility to convert Foundry modules/worlds to an EncounterPlus module

## Install required modules

    pip install -r requirements.txt

## Usage

    usage: foundrytoencounter.py [-h] [-o OUTPUT] srcfile

    Converts Foundry Modules/Worlds to EncounterPlus Modules

    positional arguments:
      srcfile     foundry file to convert

    optional arguments:
      -h, --help  show this help message and exit
      -o OUTPUT   output into given output (default: [name].module)

## Example

    python3 foundrytoencounter.py foundrymodule.zip
