# JobFlow

JobFlow is a clean, single-user, self-hosted job-search review loop. This first slice proves the core path:

1. Import preserved jobs from the old read-only SQLite database.
2. Review jobs in a mobile-first installable PWA.
3. Mark each job Good, Maybe, or Bad with quick reasons and a note.
4. Persist feedback, preferences, and local activity.
5. Let an already-running agent discover candidates, ingest chosen job facts, and persist structured analysis through a documented HTTP CLI.

There is no SaaS account model, billing, organization UI, external application submission, recruiter contact automation, LLM inside JobFlow, or automatic job-board ingestion in this slice.

## Run Locally

From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
uvicorn jobflow.main:app --host 127.0.0.1 --port 8000
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
python -m jobflow.importer \
  --old-db /path/to/legacy/jobs.sqlite3 \
  --old-profile /path/to/legacy/search-profile.yaml
```

You can point the backend at another database with:

```bash
JOBFLOW_DB=/path/to/jobflow.sqlite3 uvicorn jobflow.main:app
```

## Deterministic Discovery

Discovery uses Firecrawl as a deterministic provider controlled by the agent. Configure:

```bash
export FIRECRAWL_API_KEY=...
export FIRECRAWL_API_URL=https://api.firecrawl.dev
```

`FIRECRAWL_API_URL` may point at a private HTTP endpoint, such as a Tailscale-hosted proxy. Discovery queries and per-query limits are stored in Preferences. Raw search results are candidates, not jobs: `jobflow discovery run` canonicalizes and deduplicates URLs, returns `matched_queries`, and does not ingest anything. The agent decides which candidates to scrape, analyze, and convert into deterministic `jobflow jobs ingest` payloads.

## Agent CLI

The `jobflow` command talks to the running HTTP API. It does not access SQLite directly. Set `JOBFLOW_URL` to override the default `http://127.0.0.1:8000`.

```bash
jobflow status
jobflow preferences get
jobflow jobs list --filter unanalyzed --limit 10
jobflow jobs show <job_id>
jobflow discovery search --query "site:example.com/jobs python vienna" --limit 5
jobflow discovery run
jobflow discovery scrape --url https://example.com/jobs/123
jobflow activity --limit 20
```

Use `-` to pass JSON over stdin:

```bash
printf '%s\n' '{"source_url":"https://example.com/jobs/123?utm_source=x","title":"Software Engineer","company":"Example GmbH"}' \
  | jobflow jobs ingest --file -

printf '%s\n' '{"score":82,"verdict":"strong","confidence":"medium","summary":"Good backend fit with salary still unclear.","fit_evidence":{"role":[{"text":"Builds internal workflow APIs"}]},"missing_info":["Salary range"],"requirements":["Python"],"responsibilities":["Own backend services"],"technologies":["Python","FastAPI"],"source_evidence":{"description":["Builds internal workflow APIs"]}}' \
  | jobflow jobs analyze <job_id> --file -

jobflow feedback set <job_id> --rating maybe --reason "Salary unclear" --note "Review after clarification"
```

## Tests

```bash
. .venv/bin/activate
pytest backend/tests
npm run build --prefix frontend
```

## Deferred

Future slices can add recurring discovery, feedback-learning prompts, and CV/application-letter preparation. Manual external submission remains explicit.
