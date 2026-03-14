"""
Configuration Module for Dice Job Monitor
==========================================

Loads all settings from the .env file with sensible defaults.
Type-safe parsing with validation on startup.

Environment Variables:
    See .env file for the complete list and descriptions.
"""

import os
from dotenv import load_dotenv

load_dotenv()


# ── Helpers ──────────────────────────────────────────────────────────────────

def parse_list(value, default=None):
    """Parse comma-separated string into a list."""
    if not value or value.strip() == "":
        return default or []
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_bool(value, default=False):
    """Parse string boolean value."""
    if isinstance(value, bool):
        return value
    if not value:
        return default
    return value.lower() in ("true", "yes", "1", "on")


# ── Job Search Settings ─────────────────────────────────────────────────────

SEARCH_KEYWORDS = parse_list(os.getenv("SEARCH_KEYWORDS", ""), [
    "Data Analyst",
    "Data Engineer",
    "Business Intelligence Analyst",
    "BI Analyst",
    "BI Developer",
    "Reporting Analyst",
    "Analytics Engineer",
    "CRM Analyst",
    "Salesforce Analyst",
    "Salesforce Administrator",
    "CRM Administrator",
    "Automation Analyst",
    "RPA Developer",
    "ETL Developer",
    "Data Warehouse Engineer",
    "Power BI Developer",
    "Tableau Developer",
    "Marketing Analyst",
    "Operations Analyst",
    "Product Analyst",
    "Financial Data Analyst",
    "SQL Analyst",
    "Process Automation Analyst",
    "HubSpot Analyst",
])
SEARCH_KEYWORD = SEARCH_KEYWORDS[0] if SEARCH_KEYWORDS else "Data Analyst"
SEARCH_LOCATION = os.getenv("SEARCH_LOCATION", "United States")

# ── Dice-Specific Search Parameters ────────────────────────────────────────

# Posted date filter: ONE (today), THREE (3 days), SEVEN (7 days), ANY
SEARCH_POSTED_DATE = os.getenv("SEARCH_POSTED_DATE", "ONE")

# Page size: up to 100 (Dice default is 20)
SEARCH_PAGE_SIZE = int(os.getenv("SEARCH_PAGE_SIZE", "20"))

# ── Adaptive Pagination ─────────────────────────────────────────────────────

ENABLE_ADAPTIVE_PAGINATION = parse_bool(os.getenv("ENABLE_ADAPTIVE_PAGINATION", "false"))
HIGH_PRIORITY_KEYWORDS = parse_list(os.getenv("HIGH_PRIORITY_KEYWORDS", ""))
HIGH_PRIORITY_PAGES = int(os.getenv("HIGH_PRIORITY_PAGES", "3"))
NORMAL_PAGES = int(os.getenv("NORMAL_PAGES", "3"))
REQUEST_DELAY_SECONDS = float(os.getenv("REQUEST_DELAY_SECONDS", "3.0"))

# ── Search Strategy Permutations ────────────────────────────────────────────

# Workplace types: Remote, On-Site, Hybrid (Dice capitalisation)
SEARCH_WORKPLACE_TYPES = parse_list(
    os.getenv("SEARCH_WORKPLACE_TYPES", "Remote,On-Site,Hybrid"), ["Remote", "On-Site", "Hybrid"]
)

# Employment types: FULLTIME, CONTRACTS, PARTTIME, THIRD_PARTY
SEARCH_EMPLOYMENT_TYPES = parse_list(os.getenv("SEARCH_EMPLOYMENT_TYPES", ""), [])

# ── Async / Concurrency ─────────────────────────────────────────────────────

MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "3"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# ── Time-Based Intervals ────────────────────────────────────────────────────

ENABLE_TIME_BASED_INTERVALS = parse_bool(os.getenv("ENABLE_TIME_BASED_INTERVALS", "false"))
BUSINESS_HOURS_START = int(os.getenv("BUSINESS_HOURS_START", "8"))
BUSINESS_HOURS_END = int(os.getenv("BUSINESS_HOURS_END", "18"))
BUSINESS_HOURS_INTERVAL = int(os.getenv("BUSINESS_HOURS_INTERVAL", "5"))
OFF_HOURS_INTERVAL = int(os.getenv("OFF_HOURS_INTERVAL", "10"))

# ── Job Filters ─────────────────────────────────────────────────────────────

TITLE_MUST_CONTAIN = parse_list(os.getenv("TITLE_MUST_CONTAIN", ""))
TITLE_EXCLUDE = parse_list(os.getenv("TITLE_EXCLUDE", ""), ["intern", "internship"])
COMPANY_FILTER = parse_list(os.getenv("COMPANY_FILTER", ""))
COMPANY_EXCLUDE = parse_list(os.getenv("COMPANY_EXCLUDE", ""))
LOCATION_FILTER = parse_list(os.getenv("LOCATION_FILTER", ""))

# ── Schedule ─────────────────────────────────────────────────────────────────

RUN_EVERY_MINUTES = int(os.getenv("RUN_EVERY_MINUTES", "5"))

# ── Notifications ────────────────────────────────────────────────────────────

DISCORD_ENABLED = parse_bool(os.getenv("DISCORD_ENABLED", "false"))
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# ── Storage ──────────────────────────────────────────────────────────────────

SEEN_JOBS_FILE = os.getenv("SEEN_JOBS_FILE", "seen_jobs.json")
METRICS_FILE = os.getenv("METRICS_FILE", "metrics.json")
SEEN_JOBS_RETENTION_DAYS = int(os.getenv("SEEN_JOBS_RETENTION_DAYS", "30"))
