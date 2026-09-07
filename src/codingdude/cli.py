"""CodingDude command-line entry point."""

import argparse
import sys

from . import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='codingdude')
    parser.add_argument('--version', action='version', version=f'codingdude {__version__}')
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
