# JobFlow Backend

Run from the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
python -m jobflow.importer --old-db /path/to/legacy/jobs.sqlite3 --old-profile /path/to/legacy/search-profile.yaml
uvicorn jobflow.main:app --reload
```

The API listens on `http://127.0.0.1:8000`.

The installed `jobflow` command talks to that running API:

```bash
jobflow status
jobflow preferences get
jobflow jobs list --filter unanalyzed
jobflow jobs ingest --file job.json
jobflow jobs analyze <job_id> --file analysis.json
jobflow feedback set <job_id> --rating good --reason "Strong fit"
```

When API auth is enabled, set both `JOBFLOW_AUTH_USERNAME` and `JOBFLOW_AUTH_PASSWORD` for CLI calls. The CLI sends HTTP Basic credentials for agents; browser login uses the app-managed session cookie.
