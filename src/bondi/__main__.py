"""Support python -m bondi alongside the installed bondi command."""

from bondi._cli import main

if __name__ == "__main__":
    raise SystemExit(main())
