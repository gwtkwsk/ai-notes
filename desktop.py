import logging
import sys


def _run() -> int:
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )

    try:
        from app.desktop.main import main
    except ModuleNotFoundError as exc:
        if exc.name == "gi":
            print("Brakuje modułu 'gi' (PyGObject).")
            print(
                "Na Fedorze doinstaluj: sudo dnf install -y python3-gobject gtk4 libadwaita"
            )
            print("Następnie uruchom aplikację systemowym Pythonem: python3 desktop.py")
            return 1
        raise

    main()
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
