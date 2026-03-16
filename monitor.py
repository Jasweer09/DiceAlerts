#!/usr/bin/env python3
"""
Dice Data Analyst Job Monitor -- Async Main Runner
====================================================

Orchestrates the complete job monitoring pipeline using asyncio:
1. Generate search strategy permutations
2. Scrape Dice.com concurrently with rate limiting
3. Deduplicate, filter for relevance, apply user filters
4. Remove seen jobs, send Discord notifications
5. Record metrics for health monitoring

Usage:
    python monitor.py              # Run continuously
    python monitor.py --once       # Run once and exit (GitHub Actions)
"""

import asyncio
import time
import argparse
from datetime import datetime, timezone
from typing import List, Dict

import config
from scraper import DiceScraper, DiceSearchStrategy, CircuitBreakerSkip
from filters import (
    load_seen_jobs, save_seen_jobs, filter_new_jobs, apply_filters,
    filter_relevant_jobs, cleanup_seen_jobs,
)
from metrics import MetricsStore
from notifier import notify


def log(msg: str) -> None:
    """Print timestamped log message."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def parse_posted_time(job: Dict) -> int:
    """Convert ISO posted date to minutes-ago for sorting (newest = smallest).

    Dice provides exact ISO timestamps, so we compute the delta directly.
    Falls back to a large value if parsing fails.
    """
    posted = job.get("posted", "")
    if not posted or posted == "N/A":
        return 999999
    try:
        posted_dt = datetime.fromisoformat(posted.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - posted_dt
        return max(0, int(delta.total_seconds() / 60))
    except (ValueError, TypeError):
        return 999999


async def run_once() -> None:
    """Execute one complete async job monitoring cycle."""
    start_time = time.time()
    metrics_store = MetricsStore(config.METRICS_FILE)
    stats = {"scraped": 0, "new": 0, "notified": 0, "error": None, "rate_limited": False, "queries_skipped": 0}

    scraper = DiceScraper(
        max_concurrent=config.MAX_CONCURRENT_REQUESTS,
        base_delay=config.REQUEST_DELAY_SECONDS,
        max_retries=config.MAX_RETRIES,
    )

    try:
        log("=" * 60)
        log(f"Checking Dice.com in '{config.SEARCH_LOCATION}'")
        log(f"Keywords: {len(config.SEARCH_KEYWORDS)} search terms")

        # ── 0. Detect downtime gap and expand lookback if needed ─────
        effective_posted_date = config.SEARCH_POSTED_DATE
        summary = metrics_store.get_summary()
        last_success_ts = summary.get("last_successful_run")
        if last_success_ts:
            try:
                parsed = datetime.fromisoformat(last_success_ts)
                last_run_time = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
                now_utc = datetime.now(timezone.utc)
                gap_hours = (now_utc - last_run_time).total_seconds() / 3600
                if gap_hours > 24 and effective_posted_date == "ONE":
                    effective_posted_date = "THREE"
                    log(f"  Gap detected: last successful run {gap_hours:.1f}h ago -- expanding to 3-day lookback")
                elif gap_hours > 72 and effective_posted_date in ("ONE", "THREE"):
                    effective_posted_date = "SEVEN"
                    log(f"  Gap detected: last successful run {gap_hours:.1f}h ago -- expanding to 7-day lookback")
            except (ValueError, TypeError):
                pass

        # ── 1. Generate search strategy ──────────────────────────────
        queries = DiceSearchStrategy.generate(
            keywords=config.SEARCH_KEYWORDS,
            location=config.SEARCH_LOCATION,
            posted_date=effective_posted_date,
            page_size=config.SEARCH_PAGE_SIZE,
            workplace_types=config.SEARCH_WORKPLACE_TYPES,
            employment_types=config.SEARCH_EMPLOYMENT_TYPES,
            high_priority_keywords=config.HIGH_PRIORITY_KEYWORDS if config.ENABLE_ADAPTIVE_PAGINATION else None,
            high_priority_pages=config.HIGH_PRIORITY_PAGES,
            normal_pages=config.NORMAL_PAGES,
        )

        strategy_parts = []
        if config.SEARCH_WORKPLACE_TYPES:
            strategy_parts.append(f"workplace={config.SEARCH_WORKPLACE_TYPES}")
        if config.SEARCH_EMPLOYMENT_TYPES:
            strategy_parts.append(f"employment={config.SEARCH_EMPLOYMENT_TYPES}")

        log(f"Strategy: {len(queries)} queries ({', '.join(strategy_parts)})")
        log("=" * 60)

        # ── 2. Scrape all queries concurrently ───────────────────────
        scraper.reset_seen_ids()

        tasks = [scraper.scrape_query(q) for q in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_jobs: List[Dict] = []
        query_errors = 0
        skipped_queries: List[Dict] = []
        for i, result in enumerate(results):
            if isinstance(result, CircuitBreakerSkip):
                skipped_queries.append(queries[i])
            elif isinstance(result, Exception):
                query_errors += 1
                log(f"  Query failed: {queries[i]['label']} -- {result}")
            elif isinstance(result, list):
                all_jobs.extend(result)

        if query_errors > 0:
            log(f"  {query_errors}/{len(queries)} queries encountered errors")

        # ── 2b. Retry circuit-breaker-skipped queries after cooldown ──
        if skipped_queries:
            cooldown = scraper.rate_limiter.cooldown_seconds
            log(f"  {len(skipped_queries)} queries skipped (circuit breaker) -- retrying after {cooldown:.0f}s cooldown")
            await asyncio.sleep(cooldown)

            retry_tasks = [scraper.scrape_query(q) for q in skipped_queries]
            retry_results = await asyncio.gather(*retry_tasks, return_exceptions=True)

            retry_recovered = 0
            for i, result in enumerate(retry_results):
                if isinstance(result, list) and result:
                    all_jobs.extend(result)
                    retry_recovered += len(result)
                elif isinstance(result, Exception) and not isinstance(result, CircuitBreakerSkip):
                    query_errors += 1

            log(f"  Retry pass: recovered {retry_recovered} jobs from {len(skipped_queries)} skipped queries")

        stats["queries_skipped"] = len(skipped_queries)

        # Sort by posted time (newest first by minutes-ago value)
        all_jobs.sort(key=parse_posted_time)
        stats["scraped"] = len(all_jobs)
        log(f"Scraped {len(all_jobs)} unique jobs from {len(queries)} queries")

        if not all_jobs:
            stats["rate_limited"] = True
            log("WARNING: No jobs returned -- Dice may be rate-limiting.")
            return

        # ── 3. Relevance filter ──────────────────────────────────────
        log("Applying relevance filter...")
        relevant_jobs = filter_relevant_jobs(all_jobs, config.SEARCH_KEYWORDS)
        log(f"Relevance: {len(relevant_jobs)}/{len(all_jobs)} jobs are Data/Analytics-related")

        if not relevant_jobs:
            log("WARNING: No relevant Data/Analytics jobs found.")
            return

        # ── 4. User-defined filters ──────────────────────────────────
        filtered = apply_filters(
            relevant_jobs,
            title_must_contain=config.TITLE_MUST_CONTAIN,
            title_exclude=config.TITLE_EXCLUDE,
            company_filter=config.COMPANY_FILTER,
            company_exclude=config.COMPANY_EXCLUDE,
            location_filter=config.LOCATION_FILTER,
        )
        log(f"After user filters: {len(filtered)} jobs match criteria")

        # ── 5. Deduplication (seen jobs) ─────────────────────────────
        seen = load_seen_jobs(config.SEEN_JOBS_FILE)
        cleaned, removed_count = cleanup_seen_jobs(seen, config.SEEN_JOBS_RETENTION_DAYS)
        if removed_count > 0:
            log(f"Cleaned up {removed_count} seen jobs older than {config.SEEN_JOBS_RETENTION_DAYS} days")
        new_jobs, cleaned = filter_new_jobs(filtered, cleaned)
        stats["new"] = len(new_jobs)
        log(f"New jobs (not seen before): {len(new_jobs)}")

        # ── 6. Display and notify ────────────────────────────────────
        if new_jobs:
            new_jobs.sort(key=parse_posted_time, reverse=True)
            log("-" * 60)
            for i, job in enumerate(new_jobs, 1):
                salary_info = f" | {job['salary']}" if job.get('salary') else ""
                log(f"  #{i} [{job['posted_text']}] {job['title']}")
                log(f"      {job['company']} -- {job['location']}{salary_info}")
                log(f"      {job['url']}")
            log("-" * 60)

            if config.DISCORD_ENABLED:
                log("Sending notifications...")
                sent, failed_jobs = await notify(new_jobs, config)
                stats["notified"] = sent

                # Remove failed jobs from seen so they retry next cycle
                if failed_jobs:
                    for job in failed_jobs:
                        cleaned.pop(job["id"], None)
                    log(f"  {len(failed_jobs)} job(s) will retry next cycle (notification failed)")
            else:
                log("Notifications disabled -- enable Discord in .env")
        else:
            log("No new jobs this cycle")

        # Save seen_jobs AFTER notifications so failed ones retry
        save_seen_jobs(config.SEEN_JOBS_FILE, cleaned)

        log(f"Done. Next check in {config.RUN_EVERY_MINUTES} minutes.\n")

    except Exception as exc:
        stats["error"] = str(exc)
        log(f"ERROR: {exc}")
    finally:
        try:
            await scraper.close()
        except Exception:
            pass
        elapsed = time.time() - start_time
        metrics_store.record_run(
            jobs_scraped=stats["scraped"],
            new_jobs=stats["new"],
            notifications_sent=stats["notified"],
            execution_time=elapsed,
            success=stats["error"] is None,
            error=stats["error"],
            rate_limited=stats["rate_limited"],
        )


def get_current_interval() -> int:
    """Determine check interval based on business hours."""
    if not config.ENABLE_TIME_BASED_INTERVALS:
        return config.RUN_EVERY_MINUTES

    current_hour = datetime.now().hour
    if config.BUSINESS_HOURS_START <= current_hour < config.BUSINESS_HOURS_END:
        return config.BUSINESS_HOURS_INTERVAL
    return config.OFF_HOURS_INTERVAL


async def run_continuous() -> None:
    """Run the monitor continuously with adaptive intervals."""
    while True:
        await run_once()
        interval = get_current_interval()
        log(f"Sleeping {interval} minutes until next check...")
        await asyncio.sleep(interval * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dice Data Analyst Job Monitor")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    wt = config.SEARCH_WORKPLACE_TYPES
    et = config.SEARCH_EMPLOYMENT_TYPES

    # Calculate total queries for display
    base = len(config.SEARCH_KEYWORDS)
    variants = 1 + len(wt) + len(et)
    hp_count = len(config.HIGH_PRIORITY_KEYWORDS) if config.ENABLE_ADAPTIVE_PAGINATION else 0
    total_queries = base * variants

    print("\n" + "=" * 60)
    print("  Dice Data Analyst Monitor v1.0 (Async)")
    print("=" * 60)
    print(f"  Keywords    : {base} search terms")
    print(f"  Queries     : {total_queries} total ({base} kw x {variants} variants)")
    print(f"  Location    : {config.SEARCH_LOCATION}")
    print(f"  Workplace   : {', '.join(wt) if wt else 'all'}")
    if et:
        print(f"  Employment  : {', '.join(et)}")
    print(f"  Posted Date : {config.SEARCH_POSTED_DATE}")
    print(f"  Page Size   : {config.SEARCH_PAGE_SIZE}")
    print(f"  Concurrency : {config.MAX_CONCURRENT_REQUESTS} parallel requests")

    if config.ENABLE_TIME_BASED_INTERVALS:
        print(f"  Interval    : Adaptive ({config.BUSINESS_HOURS_INTERVAL}m biz / {config.OFF_HOURS_INTERVAL}m off)")
    else:
        print(f"  Interval    : Every {config.RUN_EVERY_MINUTES} minutes")

    print(f"  Discord     : {'ENABLED' if config.DISCORD_ENABLED else 'DISABLED'}")
    print("=" * 60 + "\n")

    if args.once:
        log("Running once (--once mode)...")
        asyncio.run(run_once())
        return

    log("Starting continuous monitoring... Press Ctrl+C to stop.\n")
    try:
        asyncio.run(run_continuous())
    except KeyboardInterrupt:
        log("Monitor stopped by user.")


if __name__ == "__main__":
    main()
