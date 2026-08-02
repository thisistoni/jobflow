# JobFlow

JobFlow is a clean, single-user, self-hosted job-search review loop. This first slice proves the core path:

1. Import preserved jobs from the old read-only SQLite database.
2. Review jobs in a mobile-first installable PWA.
3. Mark each job Good, Maybe, or Bad with quick reasons and a note.
4. Persist feedback, preferences, and local activity.

There is no SaaS account model, billing, organization UI, external application submission, recruiter contact automation, or job-board connection layer in this slice.

## Run Locally

From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn jobflow.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

In another shell:

```bash
npm install --prefix frontend
npm run dev --prefix frontend -- --port 5173
```

Open `http://127.0.0.1:5173/`.

## Data

The app uses `data/jobflow.sqlite3` by default. The importer opens the old database in SQLite read-only mode and copies the latest useful job fields, fit evidence, missing information, score, source URL, and profile-derived preferences into the new simple schema.

Importing a legacy installation is optional:

```bash
PYTHONPATH=backend python -m jobflow.importer \
  --old-db /path/to/legacy/jobs.sqlite3 \
  --old-profile /path/to/legacy/search-profile.yaml
```

You can point the backend at another database with:

```bash
JOBFLOW_DB=/path/to/jobflow.sqlite3 uvicorn jobflow.main:app --app-dir backend
```

## Tests

```bash
. .venv/bin/activate
PYTHONPATH=backend pytest backend/tests/test_feedback.py
npm run build --prefix frontend
```

## Deferred

Future slices can add recurring discovery, agent-operated CLI/skills, AI fit analysis refresh, feedback-learning prompts, and CV/application-letter preparation. Manual external submission remains explicit.
