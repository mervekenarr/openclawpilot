from pathlib import Path
import runpy
import sys

APP_DIR = Path(__file__).resolve().parent / "ops" / "openclaw"


def main():
    sys.path.insert(0, str(APP_DIR))
    runpy.run_path(str(APP_DIR / "setup_openclaw.py"), run_name="__main__")


if __name__ == "__main__":
    main()
