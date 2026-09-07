"""Thin script wrapper around the interactive chat REPL.

Usage: python scripts/chat_cli.py [--model <name>]
"""

import sys

from chartagent.cli import cli

if __name__ == "__main__":
    sys.exit(cli())