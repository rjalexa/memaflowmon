#!/usr/bin/env python3
import argparse
import datetime as dt
import os
import sys
import logging
from dataclasses import dataclass
from typing import List, Dict, Any

import requests
from dotenv import load_dotenv

# Try to import helper modules
try:
    from sendmail import send_email

    SENDMAIL_AVAILABLE = True
except ImportError:
    SENDMAIL_AVAILABLE = False

try:
    from system_info import get_hostname_and_ip

    SYSTEM_INFO_AVAILABLE = True
except ImportError:
    SYSTEM_INFO_AVAILABLE = False

    def get_hostname_and_ip():
        return {"hostname": "unknown", "ip": "unknown"}


# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Enable debug logging for Directus client
directus_logger = logging.getLogger("DirectusClient")
directus_logger.setLevel(logging.DEBUG)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class FusekiConfig:
    service: str
    endpoint: str
    dataset: str
    num_daily_articles_threshold: int

    @property
    def query_url(self) -> str:
        base = self.service.rstrip("/")
        dataset = self.dataset.strip("/")
        endpoint = self.endpoint.rstrip("/")
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        return f"{base}/{dataset}{endpoint}"


def load_config() -> FusekiConfig:
    load_dotenv(override=True)

    service = os.getenv("FUSEKI_SERVICE")
    endpoint = os.getenv("FUSEKI_ENDPOINT")
    dataset = os.getenv("FUSEKI_DATASET")
    num_daily_articles = os.getenv("NUM_DAILY_ARTICLES_TRIGGER")

    missing = [
        name
        for name, value in [
            ("FUSEKI_SERVICE", service),
            ("FUSEKI_ENDPOINT", endpoint),
            ("FUSEKI_DATASET", dataset),
            ("NUM_DAILY_ARTICLES_TRIGGER", num_daily_articles),
        ]
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required .env variables: {', '.join(missing)}")

    try:
        threshold = int(num_daily_articles)
    except ValueError:
        raise RuntimeError("NUM_DAILY_ARTICLES_TRIGGER must be an integer")

    return FusekiConfig(
        service=service,
        endpoint=endpoint,
        dataset=dataset,
        num_daily_articles_threshold=threshold,
    )


# ---------------------------------------------------------------------------
# SPARQL (Fuseki) Logic
# ---------------------------------------------------------------------------


def build_articles_query(days: int) -> str:
    """
    Counts articles per day.
    Uses simple string literal comparison matching the working example.
    """
    today = dt.date.today()
    start_date = today - dt.timedelta(days=days - 1)

    # Use simple string format YYYY-MM-DD
    today_str = today.isoformat()
    start_str = start_date.isoformat()

    return f"""
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX mema:  <http://ilmanifesto.it/ontology#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>

SELECT
  ?published_day
  (COUNT(?article) AS ?count)
WHERE {{
  ?article rdf:type mema:Article ;
           mema:published_day ?published_day .
  FILTER(
    ?published_day >= '{start_str}' &&
    ?published_day <= '{today_str}'
  )
}}
GROUP BY
  ?published_day
ORDER BY
  DESC(?published_day)
"""


def build_mentions_query(days: int) -> str:
    """
    Counts total mentions per day.
    Uses simple string literal comparison matching the working example.
    """
    today = dt.date.today()
    start_date = today - dt.timedelta(days=days - 1)

    today_str = today.isoformat()
    start_str = start_date.isoformat()

    return f"""
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX mema:  <http://ilmanifesto.it/ontology#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>

SELECT
  ?published_day
  (COUNT(?sign) AS ?total_mentions)
WHERE {{
  ?article rdf:type           mema:Article ;
           mema:published_day  ?published_day ;
           mema:yields ?sign .
  ?sign a mema:Mention .
  
  FILTER(
    ?published_day >= '{start_str}' &&
    ?published_day <= '{today_str}'
  )
}}
GROUP BY
  ?published_day
ORDER BY
  DESC(?published_day)
"""


def execute_sparql_query(
    config: FusekiConfig, query: str, timeout: int = 30
) -> List[Dict[str, Any]]:
    url = config.query_url
    headers = {"Accept": "application/sparql-results+json"}
    params = {"query": query}

    logger.debug(f"Executing SPARQL query against: {url}")
    resp = requests.get(url, headers=headers, params=params, timeout=timeout)
    resp.raise_for_status()

    data = resp.json()
    return data.get("results", {}).get("bindings", [])


# ---------------------------------------------------------------------------
# Directus Logic
# ---------------------------------------------------------------------------


@dataclass
class DirectusConfig:
    base_url: str
    jwt_token: str


def load_directus_config() -> DirectusConfig:
    load_dotenv(override=True)
    base_url = os.getenv("DIRECTUS_BASE_URL")
    jwt_token = os.getenv("DIRECTUS_JWT")

    if not base_url or not jwt_token:
        raise RuntimeError("Missing required Directus .env variables")

    return DirectusConfig(base_url=base_url, jwt_token=jwt_token)


class DirectusClient:
    def __init__(self, config: DirectusConfig):
        self.base_url = config.base_url.rstrip("/")
        self.jwt_token = config.jwt_token
        self.headers = {
            "Authorization": f"Bearer {config.jwt_token}",
            "Content-Type": "application/json",
        }

    def count_articles_by_date_range(
        self, start_date: str, end_date: str
    ) -> Dict[str, int]:
        url = f"{self.base_url}/items/articles"
        params = {
            "filter[articleEdition][editionDate][_gte]": start_date,
            "filter[articleEdition][editionDate][_lte]": end_date,
            "fields": "id,articleEdition.editionDate",
            "limit": -1,
        }

        try:
            logger.debug(f"Directus range query URL: {url}")
            response = requests.get(
                url, headers=self.headers, params=params, timeout=30
            )

            if response.status_code != 200:
                logger.error(
                    f"Directus REST API error {response.status_code}: {response.text}"
                )
                return {}

            data = response.json()
            articles = data.get("data", [])

            # Count by date
            date_counts = {}
            for article in articles:
                article_edition = article.get("articleEdition", {})
                edition_date = article_edition.get("editionDate")
                if edition_date:
                    date_only = edition_date[:10]
                    date_counts[date_only] = date_counts.get(date_only, 0) + 1

            return date_counts

        except requests.RequestException as e:
            logger.error(f"Directus REST API request failed: {e}")
            return {}


# ---------------------------------------------------------------------------
# Business Logic & Aggregation
# ---------------------------------------------------------------------------


@dataclass
class DaySummary:
    date: dt.date
    weekday: str
    fuseki_count: int = 0
    directus_count: int = 0
    total_mentions: int = 0
    avg_mentions_per_article: float = 0.0

    # Error tracking
    is_anomalous: bool = False
    error_reasons: List[str] = None

    def __post_init__(self):
        if self.error_reasons is None:
            self.error_reasons = []


def check_for_anomalies(
    summaries: List[DaySummary], threshold: int
) -> List[DaySummary]:
    """
    Apply the rules:
    1. Directus Count < Threshold (excluding Mondays) -> Low Volume
    2. Fuseki Count != Directus Count -> Mismatch
    """
    anomalous_days = []

    for s in summaries:
        issues = []

        # Rule 1: Directus Threshold Check
        # If it's not Monday, we expect a minimum number of articles in the CMS
        if s.weekday != "Monday":
            if s.directus_count < threshold:
                issues.append(f"Low Directus Volume ({s.directus_count} < {threshold})")

        # Rule 2: Consistency Check
        # Fuseki must match Directus (ingestion verification)
        if s.fuseki_count != s.directus_count:
            diff = s.directus_count - s.fuseki_count
            if diff > 0:
                issues.append(f"Missing in Fuseki (-{diff})")
            else:
                issues.append(f"Extra in Fuseki (+{abs(diff)})")

        if issues:
            s.is_anomalous = True
            s.error_reasons = issues
            anomalous_days.append(s)

    return anomalous_days


def generate_full_day_summaries(days_back: int) -> List[DaySummary]:
    """
    Generate a DaySummary for EVERY day in the last `days_back`
    initialized with 0s.
    """
    summaries: List[DaySummary] = []
    today = dt.date.today()

    for i in range(days_back):
        target_date = today - dt.timedelta(days=i)
        weekday_name = target_date.strftime("%A")
        summaries.append(DaySummary(date=target_date, weekday=weekday_name))

    # Sort ascending
    summaries.sort(key=lambda s: s.date)
    return summaries


# ---------------------------------------------------------------------------
# Email Alert Logic
# ---------------------------------------------------------------------------


def send_alert_notification(anomalies: List[DaySummary], threshold: int) -> bool:
    """
    Send an email alert listing the anomalous days.
    """
    if not SENDMAIL_AVAILABLE:
        logger.warning("Cannot send alert email: sendmail module not found.")
        return False

    system_info = get_hostname_and_ip()
    hostname = system_info.get("hostname", "unknown")
    ip = system_info.get("ip", "unknown")
    current_time_utc = dt.datetime.now(dt.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    subject = f"[ALERT] Article Count/Integrity Issues on {hostname}"

    # Build rows for the HTML table
    rows_html = ""
    for s in anomalies:
        reasons_html = "<br>".join(s.error_reasons)

        # Color coding
        d_style = ""
        f_style = ""

        if s.directus_count < threshold and s.weekday != "Monday":
            d_style = "color: red; font-weight: bold;"

        if s.fuseki_count != s.directus_count:
            f_style = "color: orange; font-weight: bold;"

        rows_html += f"""
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd;">{s.date.isoformat()}</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{s.weekday}</td>
            <td style="padding: 8px; border: 1px solid #ddd; {d_style}">{s.directus_count}</td>
            <td style="padding: 8px; border: 1px solid #ddd; {f_style}">{s.fuseki_count}</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{s.total_mentions}</td>
            <td style="padding: 8px; border: 1px solid #ddd; font-size: 0.9em;">{reasons_html}</td>
        </tr>
        """

    body = f"""<html>
<body>
<h2 style="color: red;">⚠ DATA INTEGRITY ALERT</h2>
<hr>

<p>The following days have triggered alerts based on the configured threshold ({threshold}) or data consistency checks.</p>

<h3>HOST INFORMATION:</h3>
<table style="border-collapse: collapse;">
<tr><td style="padding: 8px; border: 1px solid #ddd;"><strong>Hostname:</strong></td><td style="padding: 8px; border: 1px solid #ddd;">{hostname} (IP: {ip})</td></tr>
<tr><td style="padding: 8px; border: 1px solid #ddd;"><strong>Timestamp:</strong></td><td style="padding: 8px; border: 1px solid #ddd;">{current_time_utc}</td></tr>
</table>

<h3>ANOMALOUS DAYS:</h3>
<table style="border-collapse: collapse; width: 100%;">
<tr style="background-color: #f2f2f2;">
    <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Date</th>
    <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Weekday</th>
    <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Directus</th>
    <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">SPARQL</th>
    <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Mentions</th>
    <th style="padding: 8px; border: 1px solid #ddd; text-align: left;">Issue(s)</th>
</tr>
{rows_html}
</table>

<h3>LEGEND:</h3>
<ul>
    <li><strong>Low Directus Volume:</strong> The CMS has fewer than {threshold} articles for this day. (Likely editorial/upstream issue).</li>
    <li><strong>Missing in Fuseki:</strong> Articles exist in Directus but are not in the Knowledge Graph. (Ingestion pipeline failure).</li>
    <li><strong>Extra in Fuseki:</strong> Knowledge Graph has more articles than Directus. (Deletions in CMS not propagated, or duplicates).</li>
</ul>

<hr>
<p><em>Automated alert from main.py</em></p>
</body>
</html>
"""
    try:
        load_dotenv(override=True)
        return send_email(subject_override=subject, body_override=body, html_body=True)
    except Exception as e:
        logger.error(f"Failed to send email alert: {e}")
        return False


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor article counts in Directus vs Fuseki."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days back from today to check (default: 30)",
    )
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)

    # 1. Load Config
    try:
        config = load_config()
    except RuntimeError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1

    # 2. Initialize Day Summaries (The Dates)
    summaries = generate_full_day_summaries(args.days)
    start_date = summaries[0].date.isoformat()
    end_date = summaries[-1].date.isoformat()

    # 3. Fetch Directus Data (Source of Truth)
    directus_config = None
    try:
        directus_config = load_directus_config()
        logger.info(f"Fetching Directus counts ({start_date} to {end_date})...")
        d_client = DirectusClient(directus_config)
        d_counts = d_client.count_articles_by_date_range(start_date, end_date)

        for s in summaries:
            s.directus_count = d_counts.get(s.date.isoformat(), 0)

    except Exception as e:
        logger.error(f"Failed to fetch Directus data: {e}")

    # 4. Fetch Fuseki Data (Target)
    try:
        logger.info(f"Fetching Fuseki counts ({start_date} to {end_date})...")

        # Articles Query
        a_query = build_articles_query(args.days)
        a_bindings = execute_sparql_query(config, a_query)

        # Mentions Query
        m_query = build_mentions_query(args.days)
        m_bindings = execute_sparql_query(config, m_query, timeout=120)

        # Map SPARQL Article Counts
        f_counts = {}
        for b in a_bindings:
            try:
                # Assuming format "YYYY-MM-DD" in the binding value
                raw_date = b["published_day"]["value"]
                d = dt.date.fromisoformat(raw_date)
                f_counts[d] = int(b["count"]["value"])
            except Exception as e:
                logger.debug(f"Skipping bad date binding: {e}")

        # Map SPARQL Mention Counts
        m_counts = {}
        for b in m_bindings:
            try:
                raw_date = b["published_day"]["value"]
                d = dt.date.fromisoformat(raw_date)
                m_counts[d] = int(b["total_mentions"]["value"])
            except Exception as e:
                logger.debug(f"Skipping bad date binding: {e}")

        # Populate summaries
        for s in summaries:
            s.fuseki_count = f_counts.get(s.date, 0)
            s.total_mentions = m_counts.get(s.date, 0)
            if s.fuseki_count > 0:
                s.avg_mentions_per_article = s.total_mentions / s.fuseki_count

    except Exception as e:
        logger.error(f"Failed to fetch Fuseki data: {e}")

    # 5. Check for Anomalies
    anomalies = check_for_anomalies(summaries, config.num_daily_articles_threshold)

    # 6. Console Output
    print(
        f"Checking last {args.days} days (excluding Mondays from low-volume check)\n"
        f"Threshold: {config.num_daily_articles_threshold} articles/day"
    )
    print()

    print("SUMMARY OF ALL DAYS:")
    print(
        f"{'Date':<12} {'Weekday':<10} {'Directus':>8} {'SPARQL':>8} {'Mentions':>8} {'Avg':>6} {'Status':<20}"
    )
    print("-" * 80)
    for s in summaries:
        status = "OK"
        if s.is_anomalous:
            status = "FAIL: " + ", ".join(s.error_reasons)
            if len(status) > 30:
                status = status[:27] + "..."

        print(
            f"{s.date.isoformat():<12} {s.weekday:<10} {s.directus_count:>8} {s.fuseki_count:>8} "
            f"{s.total_mentions:>8} {s.avg_mentions_per_article:>6.1f} {status:<20}"
        )
    print()

    if not anomalies:
        print("✓ No anomalies detected.")
        return 0

    print("⚠ ANOMALIES DETECTED:")
    for s in anomalies:
        print(f"  {s.date.isoformat()} ({s.weekday}): {', '.join(s.error_reasons)}")
        print(f"    Directus: {s.directus_count} | Fuseki: {s.fuseki_count}")

    # 7. Email Alert
    if SENDMAIL_AVAILABLE:
        print("\nSending email alert...")
        if send_alert_notification(anomalies, config.num_daily_articles_threshold):
            print("Email alert sent successfully.")
        else:
            print("Failed to send email alert.")
    else:
        print("\nSkipping email alert (sendmail module not found).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
