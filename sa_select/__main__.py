"""Entry point for ``python -m sa_select``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
