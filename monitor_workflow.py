#!/usr/bin/env python3
"""
Directus vs Fuseki Integrity Monitor (Async)
"""

import argparse
import asyncio
import datetime as dt
import logging
import os
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional

import aiohttp
from dotenv import load_dotenv

# Optional Integrations
try:
    from sendmail import send_email

    SENDMAIL_AVAILABLE = True
except ImportError:
    SENDMAIL_AVAILABLE = False

    def send_email(*args, **kwargs) -> bool:
        return False

try:
    from system_info import get_hostname_and_ip

    SYSTEM_INFO_AVAILABLE = True
except ImportError:
    SYSTEM_INFO_AVAILABLE = False

    def get_hostname_and_ip():
        return {"hostname": "unknown", "ip": "unknown"}


# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Monitor")

# ---------------------------------------------------------------------------
# Configuration & Data Models
# ---------------------------------------------------------------------------


@dataclass
class Config:
    directus_base_url: str
    directus_jwt: str
    fuseki_query_url: str
    num_daily_articles_threshold: int
    num_daily_mentions_threshold: int
    concurrency_limit: int = 25


@dataclass
class Article:
    id: str
    headline: str
    slug: str
    published_date: str  # YYYY-MM-DD
    edition_date: str  # YYYY-MM-DD
    uri: str = ""

    # Analysis results
    exists_in_graph: bool = False
    mention_count: int = 0
    checked: bool = False

    @property
    def web_url(self) -> str:
        """Constructs the public web URL."""
        clean_slug = self.slug.strip("/")
        return f"https://ilmanifesto.it/{clean_slug}"


@dataclass
class DayReport:
    date: str
    total_articles: int = 0
    total_mentions: int = 0
    missing_articles: List[Article] = field(default_factory=list)
    low_article_count: bool = False
    low_mention_count: bool = False

    @property
    def has_issues(self) -> bool:
        return (
            bool(self.missing_articles)
            or self.low_article_count
            or self.low_mention_count
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_config() -> Config:
    load_dotenv(override=True)

    # Required
    d_base = os.getenv("DIRECTUS_BASE_URL")
    d_jwt = os.getenv("DIRECTUS_JWT")
    f_service = os.getenv("FUSEKI_SERVICE")
    f_dataset = os.getenv("FUSEKI_DATASET")

    if not all([d_base, d_jwt, f_service, f_dataset]):
        missing = [
            k
            for k, v in locals().items()
            if v is None and k in ["d_base", "d_jwt", "f_service", "f_dataset"]
        ]
        raise RuntimeError(f"Missing env vars: {missing}")

    assert d_base is not None
    assert d_jwt is not None
    assert f_service is not None
    assert f_dataset is not None

    # Construct Fuseki URL
    f_endpoint = os.getenv("FUSEKI_ENDPOINT", "/query").strip("/")
    f_url = f"{f_service.rstrip('/')}/{f_dataset.strip('/')}/{f_endpoint}"

    return Config(
        directus_base_url=d_base.rstrip("/"),
        directus_jwt=d_jwt,
        fuseki_query_url=f_url,
        num_daily_articles_threshold=int(os.getenv("NUM_DAILY_ARTICLES_TRIGGER", "10")),
        num_daily_mentions_threshold=int(os.getenv("NUM_DAILY_MENTIONS_TRIGGER", "0")),
    )


def slugify(value: str) -> str:
    """Generate URI-friendly slug."""
    if not value:
        return ""
    value = str(value)
    value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value)


# ---------------------------------------------------------------------------
# Async Monitor Class
# ---------------------------------------------------------------------------


class Monitor:
    def __init__(self, config: Config):
        self.cfg = config
        self.sem = asyncio.Semaphore(config.concurrency_limit)
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def fetch_directus_articles(
        self, start_date: str, end_date: str
    ) -> List[Article]:
        """Fetch all articles for date range from Directus (Source of Truth)."""
        if not self.session:
            raise RuntimeError("Session not initialized")

        url = f"{self.cfg.directus_base_url}/items/articles"
        headers = {"Authorization": f"Bearer {self.cfg.directus_jwt}"}

        # Sort by editionDate to help debugging
        params = {
            "filter[syncSource][_eq]": "wp",
            "filter[articleEdition][editionDate][_gte]": start_date,
            "filter[articleEdition][editionDate][_lte]": end_date,
            "fields": "id,headline,slug,datePublished,articleEdition.editionDate",
            "limit": -1,
            "sort": "articleEdition.editionDate",
        }

        logger.info(f"Fetching Directus articles: {start_date} -> {end_date}")

        async with self.session.get(url, headers=headers, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error(f"Directus Error {resp.status}: {text}")
                return []

            data = await resp.json()
            items = data.get("data", [])

        articles = []
        for item in items:
            headline = item.get("headline") or "(No Headline)"
            slug_raw = item.get("slug")

            # Date handling
            pub_full = item.get("datePublished")
            pub_date = (
                pub_full[:10] if pub_full and len(pub_full) >= 10 else "0000-00-00"
            )

            edition_obj = item.get("articleEdition") or {}
            edition_date = edition_obj.get("editionDate")

            if not edition_date:
                continue

            # --- KEY CHANGE: URI Construction ---
            # Prioritize the Directus 'slug' field.
            # Only use slugify(headline) if 'slug' is missing.
            if slug_raw and str(slug_raw).strip():
                slug = str(slug_raw).strip()
            else:
                slug = slugify(headline)

            uri = f"http://ilmanifesto.it/kg/article#{pub_date}-{slug}"

            articles.append(
                Article(
                    id=str(item.get("id")),
                    headline=headline,
                    slug=slug,
                    published_date=pub_date,
                    edition_date=edition_date[:10],
                    uri=uri,
                )
            )

        logger.info(f"Directus returned {len(articles)} articles.")
        return articles

    async def check_fuseki_status(self, article: Article):
        """
        Check graph existence and count mentions in a SINGLE query.
        Uses semaphore to limit concurrency.
        """
        query = f"""
        PREFIX mema: <http://ilmanifesto.it/ontology#>
        SELECT (COUNT(?sign) as ?mentions) ?is_article
        WHERE {{
            BIND(<{article.uri}> AS ?s)
            OPTIONAL {{ ?s a mema:Article . BIND(true AS ?is_article) }}
            OPTIONAL {{ ?s mema:yields ?sign . ?sign a mema:Mention . }}
        }} GROUP BY ?is_article
        """

        async with self.sem:
            if not self.session:
                return

            try:
                headers = {"Accept": "application/sparql-results+json"}
                params = {"query": query}

                async with self.session.get(
                    self.cfg.fuseki_query_url,
                    params=params,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"SPARQL Error {resp.status} for {article.id}")
                        return

                    data = await resp.json()
                    bindings = data.get("results", {}).get("bindings", [])

                    if bindings:
                        row = bindings[0]
                        # If ?is_article is bound, the article exists
                        article.exists_in_graph = "is_article" in row
                        # Get mention count
                        if "mentions" in row:
                            article.mention_count = int(row["mentions"]["value"])
                    else:
                        # Should technically not happen due to BIND, but safe fallback
                        article.exists_in_graph = False

                    article.checked = True

            except Exception as e:
                logger.error(f"Failed checking {article.uri}: {e}")

    async def run(self, start_date: str, end_date: str) -> List[DayReport]:
        async with self:
            # 1. Fetch Source Data
            articles = await self.fetch_directus_articles(start_date, end_date)
            # We continue even if articles is empty to report on missing editions

            # 2. Process Fuseki Checks Concurrently (only for found articles)
            if articles:
                tasks = [self.check_fuseki_status(a) for a in articles]
                logger.info(
                    f"Checking {len(articles)} articles in Fuseki (Pool: {self.cfg.concurrency_limit})..."
                )
                await asyncio.gather(*tasks)

            # 3. Aggregate Results by Date
            grouped = defaultdict(list)
            for a in articles:
                grouped[a.edition_date].append(a)

            # 4. Generate Reports
            reports = []

            s = dt.date.fromisoformat(start_date)
            e = dt.date.fromisoformat(end_date)
            delta = (e - s).days

            for i in range(delta + 1):
                day = s + dt.timedelta(days=i)
                day_str = day.isoformat()
                day_articles = grouped.get(day_str, [])

                report = DayReport(
                    date=day_str,
                    total_articles=len(day_articles),
                    total_mentions=sum(a.mention_count for a in day_articles),
                )

                # Identify missing articles (Directus has it, Graph does not)
                report.missing_articles = [
                    a for a in day_articles if not a.exists_in_graph
                ]

                # --- Smart Logic for Requirements ---
                is_monday = day.weekday() == 0

                if report.total_articles == 0:
                    # Case: No articles found in Directus
                    if is_monday:
                        # Requirement B: Monday with 0 articles is normal.
                        # No issue. Skip checks.
                        continue
                    else:
                        # Requirement B: Non-Monday with 0 articles is an anomaly.
                        # We flag low articles, but we DO NOT flag low mentions
                        # (missing edition implies 0 mentions, don't double report).
                        report.low_article_count = True
                else:
                    # Case: Articles exist (Monday special edition OR regular day)
                    # Check thresholds normally
                    if report.total_articles < self.cfg.num_daily_articles_threshold:
                        report.low_article_count = True

                    if report.total_mentions < self.cfg.num_daily_mentions_threshold:
                        report.low_mention_count = True

                if report.has_issues:
                    reports.append(report)

            return reports


# ---------------------------------------------------------------------------
# Reporting & Alerting
# ---------------------------------------------------------------------------


def send_alert_email(reports: List[DayReport], config: Config):
    if not reports:
        return

    hostname = get_hostname_and_ip().get("hostname", "unknown")
    subject = f"[ALERT] Knowledge Graph Integrity Issues - {hostname}"

    # CSS
    style = """
    table {border-collapse: collapse; width: 100%; margin-top: 10px;}
    th, td {border: 1px solid #ddd; padding: 8px; text-align: left;}
    th {background-color: #f2f2f2;}
    .error {color: red; font-weight: bold;}
    .day-header {background-color: #eee; padding: 10px; margin-top: 20px; border-left: 5px solid red;}
    a {text-decoration: none; color: #0066cc;}
    a:hover {text-decoration: underline;}
    """

    html = [f"<html><head><style>{style}</style></head><body>"]
    html.append("<h2>Knowledge Graph Integrity Alert</h2>")
    html.append(
        "<p>Issues detected between <strong>Directus</strong> (Source) and <strong>Fuseki</strong> (Graph).</p>"
    )

    for r in reports:
        html.append(f"<div class='day-header'><strong>Date: {r.date}</strong></div>")
        html.append("<ul>")

        # Requirement C: Directus warning in red, and explicit label
        if r.low_article_count:
            html.append(
                f"<li class='error'>Directus edition article count: {r.total_articles} "
                f"(Threshold: {config.num_daily_articles_threshold})</li>"
            )

        # Requirement: Explicit label, only show if low
        if r.low_mention_count:
            html.append(
                f"<li class='error'>Graph mention count for edition: {r.total_mentions} "
                f"(Threshold: {config.num_daily_mentions_threshold})</li>"
            )

        if r.missing_articles:
            html.append(
                f"<li class='error'>Missing in Graph: {len(r.missing_articles)} articles</li>"
            )
        html.append("</ul>")

        if r.missing_articles:
            html.append("<table>")
            # Requirement A: Web Column
            html.append(
                "<tr><th>ID</th><th>Headline</th><th>Web</th><th>Expected URI</th></tr>"
            )
            for a in r.missing_articles:
                html.append(
                    f"<tr><td>{a.id}</td><td>{a.headline}</td>"
                    f"<td><a href='{a.web_url}'>View</a></td>"
                    f"<td style='font-size:0.8em; color:#666'>{a.uri}</td></tr>"
                )
            html.append("</table>")

    html.append("</body></html>")
    body = "\n".join(html)

    if SENDMAIL_AVAILABLE:
        try:
            send_email(subject_override=subject, body_override=body, html_body=True)
            logger.info("Alert email sent successfully.")
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
    else:
        logger.warning("Email module not available. Dumping report to stdout.")
        print(re.sub(r"<[^>]+>", "", body))  # Simple strip tags for CLI


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Directus vs Fuseki Integrity Monitor")
    parser.add_argument("start", help="Start Date (YYYY-MM-DD)")
    parser.add_argument("end", help="End Date (YYYY-MM-DD)")
    args = parser.parse_args()

    try:
        config = load_config()
    except Exception as e:
        logger.critical(f"Config Error: {e}")
        sys.exit(1)

    monitor = Monitor(config)

    # Run Async Loop
    try:
        reports = asyncio.run(monitor.run(args.start, args.end))
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Runtime Error: {e}")
        sys.exit(1)

    if reports:
        logger.warning(f"Found {len(reports)} days with integrity issues.")
        send_alert_email(reports, config)
    else:
        logger.info("✓ All checks passed. No anomalies found.")


if __name__ == "__main__":
    main()