---
name: jobflow
description: Operate JobFlow through its agent-facing CLI. Use for configuring a search, reviewing unanalyzed jobs, persisting AI fit analysis, ingesting job facts, and reading user feedback without direct database access.
---

# JobFlow Agent

## Responsibility boundary

Use the `jobflow` CLI as the control surface. Never read or modify JobFlow's SQLite database directly.

**JobFlow owns deterministic execution:** provider-backed discovery calls, validated ingestion, URL canonicalization and deduplication, persistence, status transitions, retries, tool invocation, notifications, feedback records, and activity.

**The agent owns intelligence:** configure and steer discovery queries, inspect candidate pages and job facts, judge fit, add user-specific context, learn from feedback, select evidence, and—when document commands are available—create and review tailored CV and letter content.

External application submission, recruiter contact, and document upload require explicit approval for the specific opportunity.

## Core loop

1. Verify the service and read the current search configuration:

```bash
jobflow status
jobflow preferences get
```

2. Run deterministic discovery when the user wants fresh candidates:

```bash
jobflow discovery run
jobflow discovery search --query "site:example.com/jobs python vienna" --limit 5
jobflow discovery scrape --url https://example.com/jobs/123
```

Raw search results are candidates, not jobs. The agent reviews returned URLs and scraped markdown, extracts factual job fields, and only then calls `jobflow jobs ingest` for opportunities worth preserving.

3. Inspect work that needs agent judgment:

```bash
jobflow jobs list --filter unanalyzed --limit 10
jobflow jobs show <job_id>
```

4. Analyze the job against the configured preferences and user context. Persist structured JSON:

```bash
jobflow jobs analyze <job_id> --file analysis.json
# or stream JSON
jobflow jobs analyze <job_id> --file -
```

Required fields are `score` (0–100) and `verdict`. Ground evidence in the extracted job text and known profile facts. Clearly represent missing information instead of guessing it.

5. Read reviewed jobs and activity to learn from decisions:

```bash
jobflow jobs list --filter reviewed --limit 20
jobflow activity --limit 20
```

Do not overwrite user feedback through analysis. Feedback can be written only when the user has actually made the decision:

```bash
jobflow feedback set <job_id> --rating good --reason "Strong builder fit" --note "Worth preparing"
```

## Configuration

Read the current preferences before changing them. Apply a complete validated preferences JSON document only when requested or when maintaining the user's established configuration:

```bash
jobflow preferences get
jobflow preferences apply --file preferences.json
```

## Deterministic ingestion

Ingest facts obtained from a source; do not mix agent judgment into this payload:

```bash
jobflow jobs ingest --file job.json
```

Minimum payload:

```json
{
  "source_url": "https://example.com/jobs/123",
  "title": "Software Engineer",
  "company": "Example GmbH"
}
```

Optional fields include `location`, `description`, `raw_description`, `extracted_description`, `source_name`, and `first_seen_at`. JobFlow canonicalizes HTTPS URLs, removes tracking parameters, derives a stable ID, and deduplicates by canonical URL.
