# -*- coding: utf-8 -*-
"""
Vendor directory for third-party libraries bundled with the Lager CLI.

Directory Structure
-------------------
cli/vendor/
    PyCRC/          - CRC calculation library (CRC16, CRC32, CRCCCITT, etc.)

NOT in cli/vendor/:
    cli/elftools/   - pyelftools library for ELF/DWARF parsing
                      Import as: from cli.elftools import ...
                      (NOT from cli.vendor.elftools)

The elftools library is kept at cli/elftools/ (not under vendor/) for
historical reasons and import compatibility. The duplicate at
cli/vendor/elftools/ has been removed.

Usage Examples
--------------
    # Import PyCRC modules
    from cli.vendor.PyCRC.CRCCCITT import CRCCCITT
    from cli.vendor.PyCRC.CRC16 import CRC16
    from cli.vendor.PyCRC.CRC32 import CRC32

    # Import elftools (note: NOT from vendor)
    from cli.elftools.elf.elffile import ELFFile
    from cli.elftools.dwarf.dwarfinfo import DWARFInfo
"""

# Re-export PyCRC for convenient access
# Users can also import directly from cli.vendor.PyCRC.* submodules
from . import PyCRC

__all__ = ["PyCRC"]
