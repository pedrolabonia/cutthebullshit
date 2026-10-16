import sys

from .cli import main

if __name__ == "__main__":      # multiprocessing workers re-import this module (Windows, macOS spawn)
    sys.exit(main())
