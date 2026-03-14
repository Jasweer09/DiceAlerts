"""
Dice.com Job Scraper Module (Async)
====================================

Production-grade async scraper for Dice.com job listings.

Dice.com is a Next.js app — job data is embedded in the HTML as
``self.__next_f.push()`` RSC payloads.  This scraper fetches the search
results page, extracts JSON from those script chunks, and normalises
each job into the standard pipeline format.

Features:
- Async concurrent scraping with aiohttp + semaphore-based concurrency
- Next.js RSC payload parser for extracting embedded job JSON
- Search strategy permutations (workplace types)
- User-Agent rotation pool (10 realistic browser fingerprints)
- Exponential backoff with jitter on rate limiting
- Circuit breaker pattern with proper reset logic
- Retry logic for transient errors (3 attempts)
- Proxy rotation support
"""

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Dict, Optional, Set
from urllib.parse import quote_plus

import aiohttp

logger = logging.getLogger(__name__)


class CircuitBreakerSkip(Exception):
    """Raised when a query is skipped due to an open circuit breaker."""
    pass


# ── Proxy Rotation Pool ────────────────────────────────────────────────────

class ProxyRotator:
    """Rotates through a list of proxy URLs for each request."""

    def __init__(self):
        self._proxies: List[str] = []
        self._index = 0
        self._failed: Set[str] = set()
        self._load_proxies()

    def _load_proxies(self) -> None:
        single = os.getenv("PROXY_URL", "").strip()
        if single:
            self._proxies.append(single)

        proxy_list = os.getenv("PROXY_LIST", "").strip()
        if proxy_list:
            for p in proxy_list.split(","):
                p = p.strip()
                if p and p not in self._proxies:
                    self._proxies.append(p)

        proxy_file = os.getenv("PROXY_FILE", "").strip()
        if proxy_file and os.path.exists(proxy_file):
            try:
                with open(proxy_file, "r") as f:
                    for line in f:
                        p = line.strip()
                        if p and not p.startswith("#") and p not in self._proxies:
                            self._proxies.append(p)
            except Exception as exc:
                logger.warning(f"Failed to load proxy file: {exc}")

        if self._proxies:
            print(f"  [PROXY] Loaded {len(self._proxies)} proxy(ies)")

    def get_proxy(self) -> Optional[str]:
        if not self._proxies:
            return None
        available = [p for p in self._proxies if p not in self._failed]
        if not available:
            self._failed.clear()
            available = self._proxies
        proxy = available[self._index % len(available)]
        self._index += 1
        return proxy

    def mark_failed(self, proxy: str) -> None:
        self._failed.add(proxy)
        remaining = len(self._proxies) - len(self._failed)
        print(f"  [PROXY] Marked proxy as failed ({remaining} remaining)")

    def mark_success(self, proxy: str) -> None:
        self._failed.discard(proxy)

    @property
    def enabled(self) -> bool:
        return len(self._proxies) > 0


# ── User-Agent Rotation Pool ────────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:134.0) Gecko/20100101 Firefox/134.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


# ── Abstract Base ──────────────────────────────────────────────────────────

class AbstractJobScraper(ABC):
    """Abstract base class for all job scrapers."""

    @abstractmethod
    async def scrape(self, keyword: str, location: str, **kwargs) -> List[Dict]:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...


# ── Rate Limiter with Circuit Breaker ──────────────────────────────────────

class RateLimiter:
    """Exponential backoff with jitter and circuit breaker."""

    def __init__(
        self,
        base_delay: float = 3.0,
        max_delay: float = 60.0,
        jitter_range: float = 1.5,
        max_failures: int = 5,
        cooldown_seconds: float = 120.0,
    ):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter_range = jitter_range
        self.max_failures = max_failures
        self.cooldown_seconds = cooldown_seconds
        self._consecutive_failures = 0
        self._circuit_open_until: float = 0.0

    def get_delay(self) -> float:
        delay = self.base_delay * (2 ** min(self._consecutive_failures, 6))
        delay = min(delay, self.max_delay)
        jitter = random.uniform(-self.jitter_range, self.jitter_range)
        return max(0.5, delay + jitter)

    def record_success(self) -> None:
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.max_failures:
            self._circuit_open_until = time.time() + self.cooldown_seconds
            print(f"  [RATE-LIMITER] Circuit breaker OPEN for {self.cooldown_seconds}s")

    def check_circuit(self) -> bool:
        now = time.time()
        if self._circuit_open_until > 0:
            if now < self._circuit_open_until:
                return True
            self._circuit_open_until = 0.0
            self._consecutive_failures = 0
            print("  [RATE-LIMITER] Circuit breaker RESET — resuming requests")
        return False


# ── Dice Search Strategy Generator ─────────────────────────────────────────

class DiceSearchStrategy:
    """Generates search query permutations for Dice.com.

    Dice supports fewer filter axes than LinkedIn:
    - Workplace type (Remote, On-Site, Hybrid)
    - Employment type (FULLTIME, CONTRACTS, PARTTIME, THIRD_PARTY)
    - Posted date (ONE, THREE, SEVEN, ANY)

    No experience level or dual-sort needed.
    """

    @staticmethod
    def generate(
        keywords: List[str],
        location: str,
        posted_date: str = "ONE",
        page_size: int = 20,
        workplace_types: Optional[List[str]] = None,
        employment_types: Optional[List[str]] = None,
        high_priority_keywords: Optional[List[str]] = None,
        high_priority_pages: int = 3,
        normal_pages: int = 2,
    ) -> List[Dict]:
        """Return a list of query dicts ready for the scraper."""
        queries: List[Dict] = []
        hp_set = set(high_priority_keywords or [])

        for keyword in keywords:
            max_pages = high_priority_pages if keyword in hp_set else normal_pages
            priority = "HIGH" if keyword in hp_set else "NORMAL"

            # Base query (no workplace filter)
            queries.append({
                "keyword": keyword,
                "location": location,
                "posted_date": posted_date,
                "page_size": page_size,
                "max_pages": max_pages,
                "extra_params": {},
                "label": f"{keyword} [BASE/{priority}]",
            })

            # Workplace type permutations
            for wt in (workplace_types or []):
                queries.append({
                    "keyword": keyword,
                    "location": location,
                    "posted_date": posted_date,
                    "page_size": page_size,
                    "max_pages": max_pages,
                    "extra_params": {"filters.workplaceTypes": wt},
                    "label": f"{keyword} [{wt.upper()}/{priority}]",
                })

            # Employment type permutations
            for et in (employment_types or []):
                queries.append({
                    "keyword": keyword,
                    "location": location,
                    "posted_date": posted_date,
                    "page_size": page_size,
                    "max_pages": max_pages,
                    "extra_params": {"filters.employmentType": et},
                    "label": f"{keyword} [{et.upper()}/{priority}]",
                })

        return queries


# ── Next.js RSC Payload Parser ─────────────────────────────────────────────

def _parse_nextjs_jobs(html: str) -> List[Dict]:
    """Extract job objects from Dice.com Next.js RSC payloads.

    Dice embeds job data inside ``self.__next_f.push([1, "..."])`` script
    calls.  The second element is a long string with escaped quotes (``\\"``)
    containing the RSC tree, which includes a ``"jobList":{"data":[...]}``
    JSON array of job objects.

    Strategy:
    1. Find every ``self.__next_f.push([1,"..."])`` payload.
    2. Unescape the inner string (``\\"`` → ``"``).
    3. Locate ``"jobList":{"data":[`` and extract the JSON array.
    4. Parse each job object from the array.
    """
    jobs: List[Dict] = []

    # Match push payloads that contain job data
    push_pattern = re.compile(
        r'self\.__next_f\.push\(\s*\[1,"(.*?)"\]\s*\)', re.DOTALL
    )

    for match in push_pattern.finditer(html):
        raw_str = match.group(1)

        # Only process payloads that actually contain job data
        if 'companyName' not in raw_str:
            continue

        # Unescape the JS string: \" → "
        unescaped = raw_str.replace('\\"', '"')

        # Find the jobList.data array
        marker = '"jobList":{"data":['
        jl_idx = unescaped.find(marker)
        if jl_idx < 0:
            continue

        arr_start = jl_idx + len(marker) - 1  # position of '['

        # Find the matching closing ']' using bracket depth tracking
        depth = 0
        arr_end = arr_start
        for ci in range(arr_start, len(unescaped)):
            ch = unescaped[ci]
            if ch == '[':
                depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    arr_end = ci + 1
                    break

        arr_str = unescaped[arr_start:arr_end]

        try:
            parsed_jobs = json.loads(arr_str)
            if isinstance(parsed_jobs, list):
                jobs.extend(parsed_jobs)
        except json.JSONDecodeError:
            # If full array parse fails, try extracting individual objects
            _extract_individual_jobs(arr_str, jobs)

    return jobs


def _extract_individual_jobs(text: str, jobs: List[Dict]) -> None:
    """Fallback: extract individual job objects from a malformed array string."""
    seen_ids: Set[str] = {j.get("id", "") for j in jobs}
    # Find individual JSON objects that look like job listings
    obj_pattern = re.compile(r'\{[^{}]*"guid"\s*:\s*"[^"]+?"[^{}]*\}')
    for m in obj_pattern.finditer(text):
        try:
            obj = json.loads(m.group(0))
            jid = obj.get("id", obj.get("guid", ""))
            if jid and jid not in seen_ids and obj.get("companyName"):
                jobs.append(obj)
                seen_ids.add(jid)
        except json.JSONDecodeError:
            continue


# ── Dice Scraper ───────────────────────────────────────────────────────────

class DiceScraper(AbstractJobScraper):
    """Async Dice.com scraper with full resilience stack.

    Fetches Dice search results pages and extracts job data from the
    embedded Next.js RSC payloads.
    """

    BASE_URL = "https://www.dice.com/jobs"

    def __init__(
        self,
        max_concurrent: int = 5,
        base_delay: float = 3.0,
        max_retries: int = 3,
    ):
        self.max_retries = max_retries
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.rate_limiter = RateLimiter(base_delay=base_delay)
        self.proxy_rotator = ProxyRotator()
        self._session: Optional[aiohttp.ClientSession] = None
        self._global_seen_ids: Set[str] = set()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            connector = aiohttp.TCPConnector(limit_per_host=10, ssl=False)
            self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)
            # Warm-up request (mimics real browser visiting Dice.com)
            try:
                headers = self._random_headers()
                async with self._session.get(
                    "https://www.dice.com", headers=headers, timeout=aiohttp.ClientTimeout(total=10)
                ):
                    pass
                await asyncio.sleep(random.uniform(1.0, 2.5))
            except Exception:
                pass
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            try:
                if not self._session.closed:
                    await self._session.close()
            except Exception as exc:
                logger.warning(f"Session close error (non-fatal): {exc}")
            finally:
                self._session = None

    def reset_seen_ids(self) -> None:
        self._global_seen_ids.clear()

    @staticmethod
    def _random_headers() -> Dict:
        ua = random.choice(USER_AGENTS)
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.dice.com/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Cache-Control": "max-age=0",
        }
        if "Chrome/" in ua and "Firefox" not in ua:
            chrome_ver = ua.split("Chrome/")[1].split(".")[0]
            headers["Sec-CH-UA"] = f'"Chromium";v="{chrome_ver}", "Google Chrome";v="{chrome_ver}", "Not?A_Brand";v="99"'
            headers["Sec-CH-UA-Mobile"] = "?0"
            headers["Sec-CH-UA-Platform"] = random.choice(['"Windows"', '"macOS"', '"Linux"'])
        return headers

    # -- public API ----------------------------------------------------------

    async def scrape(self, keyword: str, location: str, posted_date: str = "ONE",
                     page_size: int = 20, max_pages: int = 2,
                     extra_params: Optional[Dict] = None, **kwargs) -> List[Dict]:
        """Scrape a single query with concurrency control and circuit breaker."""
        async with self.semaphore:
            if self.rate_limiter.check_circuit():
                print(f"  [SCRAPER] Circuit breaker OPEN -- skipping '{keyword}'")
                raise CircuitBreakerSkip(keyword)

            all_jobs: List[Dict] = []
            local_seen: Set[str] = set()

            for page in range(max_pages):
                if page > 0:
                    delay = self.rate_limiter.get_delay()
                    await asyncio.sleep(delay)

                jobs = await self._fetch_page(
                    keyword, location, posted_date, page_size, page, extra_params, local_seen,
                )

                if jobs is None:
                    break

                all_jobs.extend(jobs)

                if len(jobs) == 0:
                    break

            return all_jobs

    async def scrape_query(self, query: Dict) -> List[Dict]:
        """Convenience: scrape a DiceSearchStrategy query dict."""
        return await self.scrape(
            keyword=query["keyword"],
            location=query["location"],
            posted_date=query.get("posted_date", "ONE"),
            page_size=query.get("page_size", 20),
            max_pages=query["max_pages"],
            extra_params=query.get("extra_params"),
        )

    # -- internals -----------------------------------------------------------

    async def _fetch_page(
        self,
        keyword: str,
        location: str,
        posted_date: str,
        page_size: int,
        page: int,
        extra_params: Optional[Dict],
        local_seen: Set[str],
    ) -> Optional[List[Dict]]:
        """Fetch one page with retry + backoff."""
        params: Dict = {
            "q": keyword,
            "location": location,
            "page": str(page + 1),  # Dice uses 1-indexed pages
            "pageSize": str(page_size),
            "filters.postedDate": posted_date,
            "language": "en",
        }
        if extra_params:
            params.update(extra_params)

        for attempt in range(self.max_retries):
            proxy = self.proxy_rotator.get_proxy()
            try:
                session = await self._ensure_session()
                headers = self._random_headers()

                async with session.get(
                    self.BASE_URL, params=params, headers=headers, proxy=proxy
                ) as resp:
                    if resp.status == 429:
                        self.rate_limiter.record_failure()
                        if proxy:
                            self.proxy_rotator.mark_failed(proxy)
                        wait = self.rate_limiter.get_delay() * (attempt + 1)
                        print(f"  [SCRAPER] Rate limited (HTTP 429) -- waiting {wait:.1f}s")
                        await asyncio.sleep(wait)
                        continue

                    if resp.status >= 500:
                        print(f"  [SCRAPER] Server error {resp.status} for '{keyword}' -- retrying")
                        await asyncio.sleep(self.rate_limiter.get_delay())
                        continue

                    if resp.status == 403:
                        print(f"  [SCRAPER] Forbidden {resp.status} for '{keyword}' -- retrying (attempt {attempt + 1})")
                        await asyncio.sleep(self.rate_limiter.get_delay() * (attempt + 1))
                        continue

                    if resp.status != 200:
                        print(f"  [SCRAPER] HTTP {resp.status} for '{keyword}' page {page + 1}")
                        return None

                    html = await resp.text()
                    self.rate_limiter.record_success()
                    if proxy:
                        self.proxy_rotator.mark_success(proxy)
                    return self._parse_jobs(html, local_seen)

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if proxy:
                    self.proxy_rotator.mark_failed(proxy)
                if attempt < self.max_retries - 1:
                    wait = self.rate_limiter.get_delay()
                    await asyncio.sleep(wait)
                else:
                    print(f"  [SCRAPER] Failed after {self.max_retries} retries: {exc}")
                    return None

        return None

    def _parse_jobs(self, html: str, local_seen: Set[str]) -> List[Dict]:
        """Parse Dice job data from HTML page."""
        raw_jobs = _parse_nextjs_jobs(html)
        jobs: List[Dict] = []

        for raw in raw_jobs:
            try:
                parsed = self._normalise_job(raw)
                if not parsed:
                    continue

                job_id = parsed["id"]
                if job_id in local_seen or job_id in self._global_seen_ids:
                    continue

                local_seen.add(job_id)
                self._global_seen_ids.add(job_id)
                jobs.append(parsed)
            except Exception as exc:
                logger.debug(f"Failed to parse job: {exc}")
                continue

        return jobs

    @staticmethod
    def _normalise_job(raw: Dict) -> Optional[Dict]:
        """Normalise a raw Dice job dict to the standard pipeline format."""
        title = raw.get("title", "").strip()
        if not title:
            return None

        guid = raw.get("guid", raw.get("id", ""))
        job_id = guid if guid else hashlib.sha1(title.encode()).hexdigest()[:12]

        company = raw.get("companyName", raw.get("company", "N/A"))

        # Location
        loc_obj = raw.get("jobLocation", {})
        if isinstance(loc_obj, dict):
            location = loc_obj.get("displayName", "")
            if not location:
                city = loc_obj.get("city", "")
                state = loc_obj.get("state", "")
                location = f"{city}, {state}".strip(", ") if city or state else "N/A"
        elif isinstance(loc_obj, str):
            location = loc_obj
        else:
            location = "N/A"

        # Posted date — Dice gives ISO datetime
        posted_raw = raw.get("postedDate", "")
        posted_text = "N/A"
        if posted_raw:
            try:
                posted_dt = datetime.fromisoformat(posted_raw.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                delta = now - posted_dt
                total_mins = int(delta.total_seconds() / 60)
                if total_mins < 60:
                    posted_text = f"{total_mins} minutes ago"
                elif total_mins < 1440:
                    posted_text = f"{total_mins // 60} hours ago"
                else:
                    posted_text = f"{total_mins // 1440} days ago"
            except (ValueError, TypeError):
                posted_text = str(posted_raw)

        # URL — always use canonical job-detail URL via guid when available,
        # because some detailsPageUrl values are apply-redirect links
        url = ""
        if guid:
            url = f"https://www.dice.com/job-detail/{guid}"
        if not url:
            url = raw.get("detailsPageUrl", "")

        # Salary — Dice often includes this
        salary = raw.get("salary", "")

        return {
            "id": job_id,
            "title": title,
            "company": company if company else "N/A",
            "location": location if location else "N/A",
            "posted": posted_raw if posted_raw else "N/A",
            "posted_text": posted_text,
            "url": url if url else "N/A",
            "salary": salary if salary else "",
            "scraped_at": datetime.now().isoformat(),
        }


# ── Backward-compatible sync wrapper ─────────────────────────────────────────

def scrape_dice_jobs(
    keyword: str,
    location: str,
    posted_date: str = "ONE",
    page_size: int = 20,
    max_pages: int = 1,
    delay_seconds: float = 3.0,
) -> List[Dict]:
    """Synchronous fallback for legacy callers (health_monitor, alerting)."""

    async def _run() -> List[Dict]:
        scraper = DiceScraper(max_concurrent=1, base_delay=delay_seconds)
        try:
            return await scraper.scrape(keyword, location, posted_date, page_size, max_pages=max_pages)
        finally:
            await scraper.close()

    return asyncio.run(_run())
