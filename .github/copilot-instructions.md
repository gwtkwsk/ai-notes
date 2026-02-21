# Tech Stack

- uv - package manager for Python.
- Python
- LangGraph
- Gnome SDK
- sqlite3 with sqlite-vec extension for vector search

# General rules

- When working with Python ensure you use a virtual environment managed by uv.
- Manage Python dependencies using uv, without pip.
- After introducing code changes always run tests and linters.
- Use type hints in Python code everywhere.
- While debugging application issues always prefer writing tests instead of running the application.
- Before implementing a task use a subagent to provide a detailed plan.
- Use another subagent to implement the task based on the plan.
- After implementing a feature or fixing a bug run code review in subagent for modified code. Subagent should provide a list of found issues. Then run another subagent to fix the issues. 
- After code review use subagents with a minimal context to run and fix linters and tests after making code changes to preserve the main context. Pass a minimal context to the subagent to ensure it can understand code changes.

# Modular RAG Architecture
This project follows a modular RAG architecture. While implementig new functionalities for RAG, ensure that you create separate modules for each component of the RAG architecture. 
- Each module should be easy to test in separation.
- The final RAG should be composed from individual modules.
- Modules can be easily replaced or updated without affecting the overall system.

# Running tests

uv run --group dev python -m pytest tests/

# Running linting

uv run --group dev ruff check
uv run --group dev ruff format
uv run --group dev pyright

# Running the application

python desktop.py # always run outside of uv

# Distributing

The application will be distributed as a Flatpak.
The Python version that comes with Gnome SDK 48 is 3.12, so ensure that the application is compatible with Python 3.12.