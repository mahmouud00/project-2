"""Entry point of the compiled server executable (mytech-server.exe): the same commands as `python -m app.cli`."""
import sys

from app.cli import main

if __name__ == "__main__":
    sys.exit(main())
