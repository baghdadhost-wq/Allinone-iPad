#!/usr/bin/env python3
"""Allinone entry point.

    python allinone.py            interactive menu
    python allinone.py help       all commands

On Windows you can simply run  allinone  (allinone.cmd), on macOS/Linux  ./allinone
"""

import os
import sys

if sys.version_info < (3, 10):
    sys.stderr.write("Allinone needs Python 3.10 or newer (found %s).\n" % sys.version.split()[0])
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from controller.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
