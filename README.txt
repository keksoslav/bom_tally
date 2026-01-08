BOM Tally
=========

Quick and dirty BOM grouping tool.

Written to avoid doing this in Excel ever again.

This script reads a BOM from an Excel (.xlsx) file, normalizes component
values (R/C/L/etc.), groups identical parts, and writes the result to log.txt.

Features
--------
- Groups components by family (R, C, L, pot, other)
- Normalizes values:
  - Resistors: 4k7, 4.7k, 4700 -> same
  - Capacitors: 3.3uF, 3,3 u, 3.3u -> same
  - Inductors: 10uH, 10 u -> same
- Handles messy Notes/Status fields (DNF, NP, ALT, etc.)
- Writes all output to log.txt
- Optional CSV export
- Auto-detects Excel sheet (or manual --sheet)

Requirements
------------
Python 3.9+
pandas
openpyxl

Usage
-----
Basic:
python bom_tally.py BOM.xlsx

Select sheet:
python bom_tally.py BOM.xlsx --sheet BOM

Ignore notes in grouping:
python bom_tally.py BOM.xlsx --notes none

Export CSV:
python bom_tally.py BOM.xlsx --csv result.csv

Help:
python bom_tally.py --help

Output
------
- log.txt is written next to the input Excel file (or custom path via --log)
- CSV is optional

Notes
-----
- This tool assumes standard Ref. Designators (R*, C*, L*, VR*, etc.).
- Column names are auto-detected but can be overridden via CLI flags.
- If grouping looks wrong, check the column mapping section in log.txt.

License
-------
Do whatever you want with it.
