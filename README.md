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

Local Vite development remains split across the Vite dev server and FastAPI. Unless `JOBFLOW_AUTH_USERNAME` and `JOBFLOW_AUTH_PASSWORD` are both set, local development is unauthenticated.

## Run With Docker

Build and run the single production image:

```bash
docker build -t jobflow:local .
docker run --rm \
  -p 127.0.0.1:8088:8000 \
  -v jobflow-data:/data \
  -e JOBFLOW_AUTH_USERNAME=replace-with-username \
  -e JOBFLOW_AUTH_PASSWORD=replace-with-password \
  -e JOBFLOW_AUTH_COOKIE_SECURE=false \
  -e FIRECRAWL_API_URL=https://replace-with-firecrawl-url \
  -e FIRECRAWL_API_KEY=replace-with-firecrawl-api-key \
  jobflow:local
```

Open `http://127.0.0.1:8088/`.

Or use Compose:

```bash
cp .env.example .env
docker compose up -d --build
```

`compose.yaml` binds to `127.0.0.1:8088` by default. To expose only on a private Tailscale address, set the bind host in `.env`:

```dotenv
JOBFLOW_BIND=<tailscale-ip>
JOBFLOW_PORT=8088
```

The container serves the built PWA and API from the same FastAPI process. It stores SQLite data in `/data/jobflow.sqlite3`, backed by the `jobflow-data` named volume.

The Compose example runs over plain HTTP, so it sets `JOBFLOW_AUTH_COOKIE_SECURE=false`. Set `JOBFLOW_AUTH_COOKIE_SECURE=true` when JobFlow is served behind HTTPS.

Back up the named volume:

```bash
docker run --rm \
  -v jobflow-data:/data:ro \
  -v "$PWD":/backup \
  busybox \
  sh -c 'cp /data/jobflow.sqlite3 /backup/jobflow.sqlite3.backup'
```

## Authentication

Authentication is optional. If neither `JOBFLOW_AUTH_USERNAME` nor `JOBFLOW_AUTH_PASSWORD` is set, the app and API do not require credentials. If one is set without the other, startup fails with a clear configuration error.

When both are set, the PWA shell and static assets still load, then the app shows a JobFlow login screen. The login posts to `/api/auth/login` and stores a stdlib HMAC-signed, expiring, `HttpOnly`, `SameSite=Strict` session cookie. The default session lifetime is 7 days.

Protected API routes return JSON `401` responses and never emit `WWW-Authenticate`, so browsers do not show a native Basic Auth modal. `GET /health`, `GET /api/auth/status`, `POST /api/auth/login`, and `POST /api/auth/logout` stay open.

Agent clients may still authenticate API requests with HTTP Basic by sending `Authorization: Basic ...`; the server accepts valid Basic credentials without ever challenging for them. The `jobflow` CLI adds this header automatically when both `JOBFLOW_AUTH_USERNAME` and `JOBFLOW_AUTH_PASSWORD` are set in its environment, and fails clearly if only one is set.

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

If API auth is enabled, set both `JOBFLOW_AUTH_USERNAME` and `JOBFLOW_AUTH_PASSWORD` for the CLI process so it can send non-challenging Basic credentials.

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
