"""Modbus TCP/RTU simulator entry point."""

import sys

from modbus_sim.ui.app import create_app


def main() -> None:
    sys.exit(create_app())


if __name__ == "__main__":
    main()
