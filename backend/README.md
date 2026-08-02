# JobFlow Backend

Run from the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
PYTHONPATH=backend python -m jobflow.importer
uvicorn jobflow.main:app --reload --app-dir backend
```

The API listens on `http://127.0.0.1:8000`.
