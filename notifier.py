"""
Job Notification Module (Async)
================================

Sends job notifications to Discord via webhooks using async HTTP.
Follows Single Responsibility -- only handles notification delivery.

Features:
- Async Discord webhook delivery via aiohttp
- Batch sending: up to 10 embeds per webhook call (Discord max)
- Rate-limit awareness with Retry-After header support
- Up to 3 retries per batch with exponential backoff
- Retries on transient 5xx errors (not just 429)
- Returns failed jobs so they can retry next cycle
- Rich embedded messages with job details
- Salary field display (Dice includes salary data)
"""

import asyncio
import logging
from typing import List, Dict, Tuple

import aiohttp

logger = logging.getLogger(__name__)

BATCH_SIZE = 10  # Discord allows max 10 embeds per webhook call


# ── Discord Notifications ────────────────────────────────────────────────────

async def send_discord(jobs: List[Dict], config) -> Tuple[int, List[Dict]]:
    """Send job alerts to Discord via webhook with rich embeds.

    Sends up to 10 embeds per webhook call to minimize API calls.
    Returns (sent_count, list_of_failed_jobs) so caller can retry failures.
    """
    if not config.DISCORD_ENABLED or not config.DISCORD_WEBHOOK_URL:
        return 0, []

    sent = 0
    failed_jobs: List[Dict] = []
    timeout = aiohttp.ClientTimeout(total=15)

    # Build all embeds first
    job_embeds = []
    for job in jobs:
        fields = [
            {"name": "\U0001f3e2 Company", "value": job["company"], "inline": True},
            {"name": "\U0001f4cd Location", "value": job["location"], "inline": True},
            {"name": "\U0001f550 Posted", "value": job["posted_text"], "inline": True},
        ]

        # Add salary field if available (Dice provides salary data)
        salary = job.get("salary", "")
        if salary:
            fields.append({"name": "\U0001f4b0 Salary", "value": salary, "inline": True})

        embed = {
            "title": f"\U0001f514 {job['title']}",
            "url": job["url"],
            "color": 0xCC0000,  # Dice red
            "fields": fields,
            "footer": {"text": "Dice Job Monitor"},
        }
        job_embeds.append((job, embed))

    # Send in batches of BATCH_SIZE
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for batch_start in range(0, len(job_embeds), BATCH_SIZE):
            batch = job_embeds[batch_start:batch_start + BATCH_SIZE]
            embeds = [embed for _, embed in batch]
            batch_jobs = [job for job, _ in batch]
            payload = {"embeds": embeds}

            success = False
            for attempt in range(3):
                try:
                    async with session.post(config.DISCORD_WEBHOOK_URL, json=payload) as resp:
                        if resp.status in (200, 204):
                            for job in batch_jobs:
                                print(f"  [DISCORD] Sent: {job['title']} @ {job['company']}")
                            success = True
                            break
                        elif resp.status == 429:
                            retry_after = float(resp.headers.get("Retry-After", "2"))
                            print(f"  [DISCORD] Rate limited -- waiting {retry_after}s (attempt {attempt + 1})")
                            await asyncio.sleep(retry_after)
                            continue
                        elif resp.status >= 500:
                            print(f"  [DISCORD] Server error {resp.status} (attempt {attempt + 1})")
                            if attempt < 2:
                                await asyncio.sleep(2.0 * (attempt + 1))
                            continue
                        else:
                            body = await resp.text()
                            print(f"  [DISCORD] HTTP {resp.status}: {body[:100]}")
                            break  # 4xx client error, non-retryable
                except Exception as exc:
                    print(f"  [DISCORD] Error (attempt {attempt + 1}): {exc}")
                    if attempt < 2:
                        await asyncio.sleep(1.0 * (attempt + 1))

            if success:
                sent += len(batch_jobs)
            else:
                failed_jobs.extend(batch_jobs)

            # Small delay between batches to respect Discord rate limits
            await asyncio.sleep(0.5)

    if failed_jobs:
        print(f"  [DISCORD] {len(failed_jobs)} notification(s) failed -- will retry next cycle")

    return sent, failed_jobs


# ── Notification Dispatcher ──────────────────────────────────────────────────

async def notify(jobs: List[Dict], config) -> Tuple[int, List[Dict]]:
    """Main dispatcher -- sends jobs to all configured channels.

    Returns (total_sent, list_of_failed_jobs).
    """
    if not jobs:
        return 0, []
    return await send_discord(jobs, config)
