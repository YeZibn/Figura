"""Enable `python -m chartagent` to start the interactive chat session."""

import sys

from .cli import cli

if __name__ == "__main__":
    sys.exit(cli())