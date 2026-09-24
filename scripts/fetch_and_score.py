#!/usr/bin/env python3
"""Fetch jobs from JSearch, score them against the profile, and store them."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "profile.yaml"
PROFILE = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))

RAPIDAPI_KEY = os.environ["RAPIDAPI_KEY"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
DB_PATH = Path(os.environ.get("DB_PATH", str(ROOT / "jobs.db")))


def fetch_jobs() -> list[dict]:
    """Call JSearch for recent PM roles matching the candidate profile."""
    response = requests.get(
        "https://jsearch.p.rapidapi.com/search",
        headers={
            "X-RapidAPI-Key": RAPIDAPI_KEY,
            "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
        },
        params={
            "query": "Principal Product Manager OR Senior Product Manager",
            "location": "India",
            "date_posted": "week",
            "num_pages": "3",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("data", [])


def apply_hard_filters(job: dict) -> bool:
    """Return whether a job passes the profile's non-LLM filters."""
    title = job.get("job_title", "").lower()
    excluded_titles = (
        title.lower()
        for title in PROFILE["hard_filters"]["title_exclude"]
    )
    if any(excluded_title in title for excluded_title in excluded_titles):
        return False

    posted = job.get("job_posted_at_datetime_utc")
    if posted:
        posted_at = datetime.fromisoformat(posted.replace("Z", "+00:00"))
        cutoff = datetime.now(posted_at.tzinfo) - timedelta(
            days=PROFILE["hard_filters"]["posted_within_days"],
        )
        if posted_at < cutoff:
            return False

    return True


def score_job_with_llm(job: dict) -> dict:
    """Score one job with OpenAI's JSON response mode."""
    prompt = f"""You are scoring a job for Satya Tejh Rallapalli, Principal PM.

CANDIDATE PROFILE:
{json.dumps(PROFILE, indent=2)}

JOB DESCRIPTION:
Title: {job.get("job_title")}
Company: {job.get("employer_name")}
Description: {job.get("job_description", "")[:4000]}

Return JSON only:
{{
  "weighted_score": 0-100,
  "best_archetype": "A|B|C|D",
  "fit_reasons": ["reason1", "reason2", "reason3"],
  "gaps": ["gap1", "gap2"],
  "lead_story": "which anchor story to lead with",
  "recommendation": "apply|maybe|skip"
}}"""
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    response.raise_for_status()
    return json.loads(response.json()["choices"][0]["message"]["content"])


def init_db() -> sqlite3.Connection:
    """Create the standalone fetched-jobs table when needed."""
    connection = sqlite3.connect(DB_PATH)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            title TEXT,
            company TEXT,
            location TEXT,
            url TEXT,
            posted_at TEXT,
            archetype_score REAL,
            best_archetype TEXT,
            fit_reasons TEXT,
            gaps TEXT,
            lead_story TEXT,
            recommendation TEXT,
            status TEXT DEFAULT 'Inbox',
            fetched_at TEXT
        )
        """,
    )
    connection.commit()
    return connection


def store_job(connection: sqlite3.Connection, job: dict, score: dict) -> None:
    """Insert or replace one scored job."""
    location = ", ".join(
        part for part in (job.get("job_city"), job.get("job_country")) if part
    )
    connection.execute(
        """
        INSERT OR REPLACE INTO jobs
        (job_id, title, company, location, url, posted_at,
         archetype_score, best_archetype, fit_reasons, gaps,
         lead_story, recommendation, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job.get("job_id"),
            job.get("job_title"),
            job.get("employer_name"),
            location,
            job.get("job_apply_link"),
            job.get("job_posted_at_datetime_utc"),
            score.get("weighted_score"),
            score.get("best_archetype"),
            json.dumps(score.get("fit_reasons", [])),
            json.dumps(score.get("gaps", [])),
            score.get("lead_story"),
            score.get("recommendation"),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    connection.commit()


def main() -> None:
    """Fetch, filter, score, and persist jobs."""
    print(f"[{datetime.now(timezone.utc).isoformat()}] Starting job fetch...")
    connection = init_db()
    try:
        jobs = fetch_jobs()
        print(f"Fetched {len(jobs)} raw jobs")
        scored_count = 0
        for job in jobs:
            if not apply_hard_filters(job):
                continue
            try:
                score = score_job_with_llm(job)
                store_job(connection, job, score)
                scored_count += 1
                print(
                    f"  Scored: {job.get('job_title')} @ "
                    f"{job.get('employer_name')} -> {score.get('weighted_score')}",
                )
            except (KeyError, json.JSONDecodeError, requests.RequestException) as error:
                print(f"  Error scoring {job.get('job_id')}: {error}")
        print(f"Done. Stored {scored_count} scored jobs.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
