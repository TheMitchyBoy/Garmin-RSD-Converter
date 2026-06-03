# AGENTS.md

## Cursor Cloud specific instructions

### Product overview

Single **Python 3.8+ CLI** (Garmin Sonar RSD Converter). No web server, database, Docker, or Node toolchain. All workflows are batch file I/O via `sonar_cli.py`.

### Dependencies

- `requirements.txt` only documents `python>=3.8`; it is **not** a pip package list. Running `pip install -r requirements.txt` fails because pip cannot install the interpreter as a package.
- The codebase uses the **Python standard library only** (no third-party wheels required).

### VM update script (automatic)

On each session start, the VM runs a Python version check only (see `.cursor` environment config). No `pip install` step is needed.

### Lint

No linter is configured (no ruff, flake8, black, mypy, or pre-commit). Skip lint unless you add tooling.

### Test

```bash
cd /workspace
python3 -m unittest test_converter.py -v
```

### Run (dev)

There is no dev server. Use the CLI from the repo root:

```bash
python3 sonar_cli.py convert path/to/Sonar000.RSD
python3 sonar_cli.py convert path/to/Sonar000.RSD --maps ply
python3 sonar_cli.py analyze sonar_data.csv
```

### Gotchas

- **`Upload_Sample.RSD`** in the repo is a ~29-byte stub; `convert` succeeds but extracts **0 frames**, so `--maps ply` errors with “No valid sonar point data”. Use a real Garmin `.RSD` or a CSV with sonar rows for meaningful demos.
- **`sonar_cli (1).py`** is an extended CLI documented in `FEATURES_GUIDE.md` / `README (1).md`; it imports missing `web_visualizer.py` and will not run until that module exists. Prefer **`sonar_cli.py`** for supported commands (`convert`, `analyze`).
- Duplicate `* (1).py` files are copies; edit the primary filenames without `(1)` unless intentionally working on the extended variant.

### Optional manual verification

After `convert` on real data, open generated `.ply` in CloudCompare/Meshlab or GeoJSON in a map viewer. Not required for automated tests.
