# Tech Stack

- uv - package manager for Python.
- Python
- LangGraph
- Gnome SDK

# General rules

- When working with Python ensure you use a virtual environment managed by uv.
- Manage Python dependencies using uv, without pip.

# Running tests

uv run --extra dev python -m pytest tests/

# Running the application

python desktop.py # always run outside of uv

# Distributing

The application will be distributed as a Flatpak.
The Python version that comes with Gnome SDK 48 is 3.12, so ensure that the application is compatible with Python 3.12.