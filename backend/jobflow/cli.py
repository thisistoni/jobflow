from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
BASE_URL_ENV = "JOBFLOW_URL"
JOB_FILTERS = ["inbox", "strong", "maybe", "low", "reviewed", "unanalyzed", "all"]


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    client = Client(args.base_url)
    try:
        result = dispatch(args, client)
    except CliError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, ensure_ascii=False)
    print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agent-facing HTTP CLI for JobFlow.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get(BASE_URL_ENV, DEFAULT_BASE_URL),
        help=f"API base URL; defaults to ${BASE_URL_ENV} or {DEFAULT_BASE_URL}.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Read backend health.")

    jobs = commands.add_parser("jobs", help="Inspect, ingest, and analyze jobs.")
    job_commands = jobs.add_subparsers(dest="jobs_command", required=True)

    list_jobs = job_commands.add_parser("list", help="List jobs.")
    list_jobs.add_argument("--filter", default="inbox", choices=JOB_FILTERS)
    list_jobs.add_argument("--limit", type=int, default=50)

    show_job = job_commands.add_parser("show", help="Read one job.")
    show_job.add_argument("job_id")

    ingest_job = job_commands.add_parser("ingest", help="Ingest one deterministic job record from JSON.")
    ingest_job.add_argument("--file", required=True, help="JSON file path, or - for stdin.")

    analyze_job = job_commands.add_parser("analyze", help="Persist agent analysis for one job from JSON.")
    analyze_job.add_argument("job_id")
    analyze_job.add_argument("--file", required=True, help="JSON file path, or - for stdin.")

    preferences = commands.add_parser("preferences", help="Read or replace search preferences.")
    preference_commands = preferences.add_subparsers(dest="preferences_command", required=True)
    preference_commands.add_parser("get", help="Read search preferences.")
    apply_preferences = preference_commands.add_parser("apply", help="Replace search preferences from JSON.")
    apply_preferences.add_argument("--file", required=True, help="JSON file path, or - for stdin.")

    feedback = commands.add_parser("feedback", help="Write explicit user feedback.")
    feedback_commands = feedback.add_subparsers(dest="feedback_command", required=True)
    set_feedback = feedback_commands.add_parser("set", help="Mark a job good, maybe, or bad.")
    set_feedback.add_argument("job_id")
    set_feedback.add_argument("--rating", required=True, choices=["good", "maybe", "bad"])
    set_feedback.add_argument("--reason", action="append", default=[])
    set_feedback.add_argument("--note", default="")

    activity = commands.add_parser("activity", help="Read recent deterministic activity.")
    activity.add_argument("--limit", type=int, default=50)
    return parser


def dispatch(args: argparse.Namespace, client: "Client") -> Any:
    if args.command == "status":
        return client.request("GET", "/health")
    if args.command == "jobs":
        if args.jobs_command == "list":
            query = urlencode({"filter": args.filter, "limit": args.limit})
            return client.request("GET", f"/api/jobs?{query}")
        if args.jobs_command == "show":
            return client.request("GET", f"/api/jobs/{args.job_id}")
        if args.jobs_command == "ingest":
            return client.request("POST", "/api/jobs", read_json(args.file))
        if args.jobs_command == "analyze":
            return client.request("PUT", f"/api/jobs/{args.job_id}/analysis", read_json(args.file))
    if args.command == "preferences":
        if args.preferences_command == "get":
            return client.request("GET", "/api/preferences")
        if args.preferences_command == "apply":
            return client.request("PUT", "/api/preferences", read_json(args.file))
    if args.command == "feedback" and args.feedback_command == "set":
        return client.request(
            "POST",
            f"/api/jobs/{args.job_id}/feedback",
            {"rating": args.rating, "reasons": args.reason, "note": args.note},
        )
    if args.command == "activity":
        query = urlencode({"limit": args.limit})
        return client.request("GET", f"/api/activity?{query}")
    raise CliError("Unsupported command")


class Client:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, payload: Any | None = None) -> Any:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8")
            raise CliError(f"HTTP {exc.code}: {format_error_body(detail)}") from exc
        except URLError as exc:
            raise CliError(f"Request failed: {exc.reason}") from exc
        if not body:
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise CliError(f"Response was not valid JSON: {body}") from exc


def read_json(path: str) -> Any:
    try:
        raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        return json.loads(raw)
    except OSError as exc:
        raise CliError(f"Could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CliError(f"Invalid JSON in {path}: {exc}") from exc


def format_error_body(body: str) -> str:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body
    return json.dumps(parsed, ensure_ascii=False)


class CliError(Exception):
    pass


if __name__ == "__main__":
    raise SystemExit(main())
