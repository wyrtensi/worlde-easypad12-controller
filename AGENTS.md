# AGENTS Instructions for WORLDE EASYPAD.12 Controller

This document defines contributor conventions for the entire repository.
If you add new directories, they inherit these rules unless a nested
`AGENTS.md` overrides them.

## Project Overview

- **Purpose**: Desktop controller for the WORLDE EASYPAD.12 MIDI keyboard on
  Windows 10/11.
- **Entry Point**: `run.py` creates a `QApplication` and launches
  `MIDIKeyboardApp` from `app/main.py` using `qasync` to integrate the Qt event
  loop with `asyncio`.
- **Core Modules** (located in `app/`):
  - `main.py` – Qt user interface and high‑level application logic.
  - `midi_controller.py` – handles MIDI device connections and message
    processing with `rtmidi`.
  - `system_actions.py` – wrappers around system‑level features such as volume
    control, keyboard shortcuts, and command execution.
  - `notifications.py` – toast notifications built with PySide6 widgets.
  - `text_to_speech.py` – speech synthesis via `yandex_tts_free` or OpenAI
    APIs.
  - `webos_tv.py` – optional LG webOS TV integration using `aiowebostv`.
  - `utils.py` – logging setup, theme loading, config helpers, and miscellaneous
    utility functions.
- **Support Directories**:
  - `assets/` – icons and other static resources.
  - `config/` – persisted configuration files.
  - `logs/` – runtime log files created via `utils.setup_logging()`.
  - `run.spec` – PyInstaller build spec for generating a Windows executable.

## Environment Setup

1. Use **Python 3.12**.
2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   pip install -r requirements.txt
   ```
3. Some packages require Windows (e.g. `pywin32`, `winrt`, `pycaw`). When
   developing on other platforms, mock or guard Windows‑specific code paths.

## Coding Standards

- Adhere to **PEP 8** style guidelines with **4‑space indents** and a preferred
  **max line length of 100 characters**.
- Use **type hints** for function signatures and important variables.
- Include **docstrings** (triple double quotes) for modules, classes, and
  public functions. Follow a concise Google‑style or NumPy‑style layout.
- Favor **dataclasses** when representing structured data.
- Always use the **logging** module instead of `print` for runtime information.
  Obtain loggers with `logging.getLogger(__name__)` and rely on
  `utils.setup_logging()` for configuration.
- Keep functions small and focused. Extract helpers when logic exceeds ~40 lines.

## Development Guidelines

- Place new UI components in `app/main.py` or split into new modules within
  `app/` if they become large. Each module should expose a clear API for the
  rest of the application.
- For new MIDI interactions, extend `MIDIController` or add methods that map
  incoming messages to application actions. Persist mappings using the helpers
  in `utils.py`.
- When adding new system features (e.g., launching programs), create the logic
  in `system_actions.py` and keep platform‑specific code isolated.
- Update `requirements.txt` when adding or removing dependencies. Use pinned
  versions where stability is critical.
- Store persistent user data under `config/` and avoid committing generated
  files or directories such as `logs/` or build artifacts.

## Testing and Verification

Before committing, run the following checks:

1. **Syntax check for all Python files**
   ```bash
   python -m py_compile $(git ls-files '*.py')
   ```
2. **Optional linters (if installed)**
   ```bash
   flake8
   black --check .
   ```
3. **Manual smoke test** – launch the application
   ```bash
   python run.py
   ```
   Ensure the main window opens without errors and core features still work.

## Documentation and Commit Messages

- Update `README.md` or inline documentation when features or workflows change.
- Keep this `AGENTS.md` up to date with any new conventions.
- Write commit messages in the *imperative present tense* with a short summary
  (<50 characters) and, if necessary, a detailed body explaining the rationale.

## Packaging

To build the Windows executable, use the PyInstaller command described in the
README:

```bash
pyinstaller --onefile --noconsole --icon=icon.ico --version-file version.txt \
           --exclude-module PyQt5 --exclude-module PyQt6 run.py
```

## Notes

- This `AGENTS.md` applies to the entire repository. Add additional
  `AGENTS.md` files in subdirectories if more specific rules are needed.
