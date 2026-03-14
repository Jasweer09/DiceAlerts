"""
Job Filtering Module
====================

Handles job filtering, deduplication, and relevance validation.
Ensures only new, relevant jobs are sent as notifications.

Key Features:
- Deduplication with persistent JSON storage + corruption recovery
- Relevance filtering using 250+ Data Analyst/Engineer/CRM/Automation term dictionary
- Configurable title, company, and location filters
- Job relevance scoring (0.0-1.0)
- Automatic cleanup of stale entries
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


# ── Deduplication ────────────────────────────────────────────────────────────

def load_seen_jobs(filepath: str) -> Dict:
    """Load previously seen job IDs from disk.

    On corruption or parse errors, backs up the corrupted file and starts fresh
    instead of silently losing all history.
    """
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")
        return data
    except json.JSONDecodeError as exc:
        # Back up corrupted file so we don't lose data permanently
        backup = filepath + f".corrupt.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        logger.error(f"Corrupted seen_jobs file: {exc}. Backing up to {backup}")
        print(f"  [WARNING] seen_jobs.json corrupted: {exc}. Backed up to {backup}")
        try:
            os.rename(filepath, backup)
        except OSError:
            pass
        return {}
    except Exception as exc:
        logger.error(f"Failed to load seen_jobs: {exc}")
        print(f"  [WARNING] Could not load seen_jobs: {exc}")
        return {}


def save_seen_jobs(filepath: str, seen: Dict) -> None:
    """Persist seen job IDs to disk (atomic write via temp file + rename)."""
    tmp = filepath + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(seen, f, indent=2, ensure_ascii=False)
        os.replace(tmp, filepath)
    except Exception as exc:
        logger.error(f"Failed to save seen_jobs: {exc}")
        # Clean up temp file
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def filter_new_jobs(jobs: List[Dict], seen_jobs: Dict) -> Tuple[List[Dict], Dict]:
    """Return only jobs not seen before, and update seen dict."""
    new_jobs = []
    for job in jobs:
        job_id = job["id"]
        if job_id not in seen_jobs:
            new_jobs.append(job)
            seen_jobs[job_id] = {
                "title": job["title"],
                "company": job["company"],
                "first_seen": datetime.now().isoformat(),
            }
    return new_jobs, seen_jobs


def cleanup_seen_jobs(seen_jobs: Dict, retention_days: int = 30) -> Tuple[Dict, int]:
    """Remove seen jobs older than retention_days."""
    cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()
    cleaned = {}
    for job_id, data in seen_jobs.items():
        if isinstance(data, dict) and data.get("first_seen", "") >= cutoff:
            cleaned[job_id] = data
        elif not isinstance(data, dict):
            # Legacy format or malformed — keep it
            cleaned[job_id] = data
    return cleaned, len(seen_jobs) - len(cleaned)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _term_matches(term: str, text: str) -> bool:
    """Word-boundary match for short terms to avoid false substring hits.

    Short alphabetic terms (<=4 chars like 'sql', 'bi', 'ssis', 'ssrs') use
    regex word boundaries. Longer terms use substring match which is
    faster and sufficient (e.g., 'data analyst' won't false-match).
    """
    if len(term) <= 4 and term.isalpha():
        return bool(re.search(r"\b" + re.escape(term) + r"\b", text))
    return term in text


# ── Relevance Filtering ─────────────────────────────────────────────────────

# Expanded Data Analyst / Data Engineer / CRM / Automation term dictionary (250+ terms)
DATA_ANALYST_CORE_TERMS = [
    # ── Data Analyst Roles (~50 terms) ───────────────────────────────────
    "data analyst", "data analysis", "data analytics",
    "junior data analyst", "senior data analyst", "lead data analyst",
    "staff data analyst", "principal data analyst",
    "business analyst", "business intelligence analyst",
    "bi analyst", "bi developer", "bi engineer",
    "reporting analyst", "report analyst", "report developer",
    "insights analyst", "insight analyst",
    "product analyst", "product analytics",
    "marketing analyst", "marketing analytics", "marketing data analyst",
    "operations analyst", "operational analyst", "ops analyst",
    "financial analyst", "financial data analyst", "finance analyst",
    "revenue analyst", "pricing analyst",
    "risk analyst", "risk data analyst",
    "supply chain analyst", "logistics analyst",
    "healthcare analyst", "clinical data analyst",
    "hr analyst", "people analyst", "workforce analyst",
    "fraud analyst", "compliance analyst",
    "web analyst", "digital analyst", "digital analytics",
    "ecommerce analyst", "e-commerce analyst",
    "customer analyst", "customer insights analyst",
    "research analyst", "quantitative analyst",
    "sql analyst", "excel analyst",
    "analytics manager", "data analytics manager",
    "analytics lead", "analytics director",

    # ── Data Engineer Roles (~35 terms) ──────────────────────────────────
    "data engineer", "data engineering",
    "junior data engineer", "senior data engineer", "lead data engineer",
    "staff data engineer", "principal data engineer",
    "etl developer", "etl engineer", "etl analyst",
    "analytics engineer", "analytics engineering",
    "data architect", "data architecture",
    "data pipeline", "data pipeline engineer",
    "data warehouse", "data warehouse engineer", "data warehouse developer",
    "data warehouse analyst", "dwh developer", "dwh engineer",
    "data modeler", "data modeling",
    "data platform", "data platform engineer",
    "data infrastructure", "data infrastructure engineer",
    "database developer", "database engineer", "database analyst",
    "database administrator", "dba",
    "big data engineer", "big data developer", "big data analyst",
    "cloud data engineer",

    # ── CRM Analyst Roles (~35 terms) ────────────────────────────────────
    "crm analyst", "crm manager", "crm specialist",
    "crm developer", "crm administrator", "crm admin",
    "crm consultant", "crm coordinator", "crm engineer",
    "salesforce analyst", "salesforce administrator", "salesforce admin",
    "salesforce developer", "salesforce consultant",
    "salesforce engineer", "salesforce specialist",
    "salesforce architect", "salesforce manager",
    "hubspot analyst", "hubspot specialist", "hubspot administrator",
    "hubspot manager", "hubspot developer", "hubspot consultant",
    "dynamics 365", "dynamics crm", "dynamics analyst",
    "dynamics administrator", "dynamics developer", "dynamics consultant",
    "marketo specialist", "marketo analyst", "marketo developer",
    "pardot specialist", "pardot analyst",
    "marketing automation specialist", "marketing operations analyst",
    "lifecycle analyst", "retention analyst", "engagement analyst",

    # ── Automation Analyst Roles (~25 terms) ─────────────────────────────
    "automation analyst", "automation engineer", "automation specialist",
    "automation developer", "automation consultant",
    "rpa developer", "rpa analyst", "rpa engineer",
    "rpa consultant", "rpa specialist",
    "process automation", "process automation analyst",
    "process automation engineer", "process automation specialist",
    "workflow automation", "workflow analyst", "workflow engineer",
    "business process analyst", "business process automation",
    "intelligent automation", "digital automation",
    "robotic process automation",
    "automation architect", "automation manager",
    "hyperautomation",

    # ── Tech Stack Signals (~50 terms) ───────────────────────────────────
    "sql", "mysql", "postgresql", "postgres", "sql server", "t-sql", "pl/sql",
    "python analyst", "python data", "r programmer",
    "tableau", "tableau developer", "tableau analyst",
    "power bi", "power bi developer", "power bi analyst", "powerbi",
    "looker", "looker developer", "looker analyst",
    "qlik", "qlikview", "qlik sense",
    "dbt", "dbt developer", "dbt engineer",
    "airflow", "apache airflow",
    "snowflake", "snowflake developer", "snowflake engineer",
    "databricks", "databricks engineer",
    "bigquery", "big query", "google bigquery",
    "redshift", "amazon redshift",
    "spark", "apache spark", "pyspark",
    "kafka", "apache kafka",
    "fivetran", "stitch", "matillion", "talend", "informatica",
    "ssis", "ssrs", "ssas",
    "excel", "advanced excel", "vba",
    "google analytics", "adobe analytics",
    "data studio", "looker studio",
    "metabase", "superset", "apache superset",

    # ── Automation Tools (~15 terms) ─────────────────────────────────────
    "uipath", "ui path",
    "power automate", "microsoft power automate",
    "automation anywhere",
    "blue prism", "blueprism",
    "zapier", "workato", "make.com", "integromat",
    "celonis", "appian",
    "n8n", "tray.io",

    # ── CRM Platforms (~15 terms) ────────────────────────────────────────
    "salesforce", "hubspot", "marketo",
    "dynamics 365", "microsoft dynamics",
    "pardot", "eloqua",
    "zoho crm", "zoho",
    "sugar crm", "sugarcrm",
    "pipedrive", "freshsales",
    "klaviyo", "braze", "iterable",

    # ── Data Governance (~20 terms) ──────────────────────────────────────
    "data governance", "data governance analyst",
    "data quality", "data quality analyst", "data quality engineer",
    "data steward", "data stewardship",
    "data catalog", "data cataloging",
    "data mesh", "data fabric",
    "data lake", "data lakehouse",
    "data lineage", "data compliance",
    "master data management", "data management", "mdm",

    # ── Standalone Short Terms (word-boundary matched) ─────────────────
    "crm", "rpa", "etl", "d365",

    # ── Visualization & Dashboards (~10 terms) ──────────────────────────
    "data visualization", "data visualisation",
    "dashboard developer", "dashboard analyst", "dashboard designer",
    "visualization engineer", "visualisation engineer",
    "reporting engineer", "reporting developer",
    "kpi analyst",
]


def filter_relevant_jobs(jobs: List[Dict], search_keywords: List[str]) -> List[Dict]:
    """Validate scraped jobs contain Data/Analytics-related terms OR user search keywords in title.

    Dice's broad matching returns irrelevant results (e.g., searching
    "Data Analyst" returns unrelated roles). This filter catches them.

    Jobs whose title matches any user-configured SEARCH_KEYWORDS auto-pass,
    so custom keywords are never silently dropped by the relevance filter.
    """
    relevant = []
    filtered_count = 0

    # Normalize user keywords for matching (lowercase, multi-word safe)
    user_kw_lower = [kw.strip().lower() for kw in search_keywords if kw.strip()]

    for job in jobs:
        title_lower = job["title"].lower()

        # Pass if title matches any Data/Analytics core term
        if any(_term_matches(term, title_lower) for term in DATA_ANALYST_CORE_TERMS):
            relevant.append(job)
        # Pass if title contains any user-configured search keyword
        elif user_kw_lower and any(kw in title_lower for kw in user_kw_lower):
            relevant.append(job)
        else:
            filtered_count += 1
            print(f"  Filtered irrelevant: '{job['title']}' at {job['company']}")

    if filtered_count > 0:
        print(f"  Relevance filter removed {filtered_count} irrelevant job(s)")

    return relevant


def calculate_job_relevance_score(job_title: str, search_keyword: str) -> float:
    """Score job relevance 0.0-1.0 for ranking."""
    title_lower = job_title.lower()
    keyword_lower = search_keyword.lower()

    if title_lower == keyword_lower:
        return 1.0

    score = 0.0

    if keyword_lower in title_lower:
        score = 0.9

    keyword_words = set(keyword_lower.split())
    title_words = set(title_lower.split())
    if keyword_words:
        overlap = len(keyword_words & title_words) / len(keyword_words)
        score = max(score, overlap * 0.8)

    high_value = [
        "data analyst", "data engineer", "bi analyst",
        "crm analyst", "automation analyst", "analytics engineer",
    ]
    boost = sum(0.1 for t in high_value if t in title_lower)
    return min(score + boost, 1.0)


# ── User Filters ─────────────────────────────────────────────────────────────

def apply_filters(
    jobs: List[Dict],
    title_must_contain: List[str],
    title_exclude: List[str],
    company_filter: List[str],
    company_exclude: List[str],
    location_filter: List[str],
) -> List[Dict]:
    """Apply user-defined keyword, company, and location filters.

    All checks are case-insensitive. Uses word-boundary matching for
    title filters to avoid partial hits (e.g., "intern" won't match "internal").
    """
    filtered = []
    for job in jobs:
        title = job["title"].lower()
        company = job["company"].lower()
        location = job["location"].lower()

        if title_must_contain:
            if not any(
                re.search(r"\b" + re.escape(w.lower()) + r"\b", title)
                for w in title_must_contain
            ):
                continue

        if title_exclude:
            if any(
                re.search(r"\b" + re.escape(w.lower()) + r"\b", title)
                for w in title_exclude
            ):
                continue

        if company_filter:
            if not any(c.lower() in company for c in company_filter):
                continue

        if company_exclude:
            if any(c.lower() in company for c in company_exclude):
                continue

        if location_filter:
            if not any(loc.lower() in location for loc in location_filter):
                continue

        filtered.append(job)

    return filtered
