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

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


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
        """
        Build the full SPARQL endpoint URL from parts.
        Example: http://localhost:3030/memav7/query
        """
        base = self.service.rstrip("/")
        dataset = self.dataset.strip("/")
        endpoint = self.endpoint
        
        # Remove trailing slash from endpoint if present
        endpoint = endpoint.rstrip("/")
        
        # ensure endpoint starts with a single leading slash
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
            
        return f"{base}/{dataset}{endpoint}"


def load_config() -> FusekiConfig:
    """
    Load configuration from .env and return a FusekiConfig instance.
    Required:
      - FUSEKI_SERVICE (e.g. http://localhost:3030)
      - FUSEKI_ENDPOINT (e.g. /query/)
      - FUSEKI_DATASET (e.g. memav7)
      - NUM_DAILY_ARTICLES_TRIGGER (integer threshold)
    """
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

    # Type narrowing: after the None check, these are guaranteed to be str
    assert service is not None
    assert endpoint is not None
    assert dataset is not None
    assert num_daily_articles is not None

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
# SPARQL query building & execution
# ---------------------------------------------------------------------------


def build_sparql_query(days: int) -> str:
    """
    Build a SPARQL query that groups articles by mema:published_day
    for the last `days` days (inclusive of today).

    We let Fuseki compute 'today' using NOW() and subtract an xsd:dayTimeDuration.
    """
    # SPARQL duration literal, e.g. "P30D"^^xsd:dayTimeDuration
    duration_literal = f'"P{days}D"^^xsd:dayTimeDuration'

    return f"""
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX mema:  <http://ilmanifesto.it/ontology#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>

SELECT
  ?published_day
  (COUNT(?article) AS ?count)
WHERE {{
  # compute today and {days} days ago
  BIND(NOW() AS ?nowDt)
  BIND(xsd:date(?nowDt) AS ?today)
  BIND(?nowDt - {duration_literal} AS ?startDt)
  BIND(xsd:date(?startDt) AS ?startDate)

  # match articles in the last {days} days
  ?article rdf:type mema:Article ;
           mema:published_day ?published_day .
  FILTER(
    xsd:date(?published_day) >= ?startDate &&
    xsd:date(?published_day) <= ?today
  )
}}
GROUP BY
  ?published_day
ORDER BY
  DESC(xsd:date(?published_day))
"""
    # (no LIMIT: we just filter by date window)


def execute_sparql_query(config: FusekiConfig, query: str) -> List[Dict[str, Any]]:
    """
    Execute a SPARQL SELECT query against Fuseki and return the 'bindings' list.
    """
    url = config.query_url
    headers = {
        "Accept": "application/sparql-results+json",
    }
    params = {
        "query": query,
    }

    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()

    data = resp.json()
    return data.get("results", {}).get("bindings", [])


# ---------------------------------------------------------------------------
# Business logic
# ---------------------------------------------------------------------------


@dataclass
class DaySummary:
    date: dt.date
    weekday: str
    count: int


def parse_results_to_day_summaries(bindings: List[Dict[str, Any]]) -> List[DaySummary]:
    """
    Convert SPARQL JSON bindings into a list of DaySummary objects.
    Each binding should have 'published_day' and 'count' variables.
    """
    summaries: List[DaySummary] = []

    for b in bindings:
        published_val = b["published_day"]["value"]
        count_val = b["count"]["value"]

        # Parse date like "2025-11-14"
        d = dt.date.fromisoformat(published_val)
        count = int(count_val)
        weekday_name = d.strftime("%A")

        summaries.append(DaySummary(date=d, weekday=weekday_name, count=count))

    # sort ascending by date to make output natural
    summaries.sort(key=lambda s: s.date)
    return summaries


def find_suspicious_days(
    summaries: List[DaySummary],
    threshold: int,
) -> List[DaySummary]:
    """
    From list of day summaries, return those that:
      - are NOT Monday
      - have article count < threshold
    """
    suspicious = []
    for s in summaries:
        # Monday is 0 in weekday(), but we already have the name
        if s.weekday != "Monday" and s.count < threshold:
            suspicious.append(s)
    return suspicious


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check, for the last N days, which days (excluding Mondays) "
            "have fewer articles than NUM_DAILY_ARTICLES_TRIGGER."
        )
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

    try:
        config = load_config()
    except RuntimeError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1

    # Test endpoint connectivity
    logger.debug(f"Testing endpoint pattern 1: {config.query_url}")
    try:
        test_response = requests.get(config.query_url, timeout=10)
        logger.debug(f"Pattern 1 - Status: {test_response.status_code}")
        if test_response.status_code == 200:
            logger.debug(f"SUCCESS: Found working endpoint at: {config.query_url}")
        else:
            logger.warning(f"Endpoint returned status {test_response.status_code}")
    except requests.RequestException as e:
        logger.error(f"Failed to reach endpoint {config.query_url}: {e}")
        return 1

    # Log current date/time for debugging
    now = dt.datetime.now()
    logger.debug(f"Current execution time: {now.isoformat()}")
    logger.debug(f"User timezone: {os.getenv('TZ', 'Not set')}")

    query = build_sparql_query(days=args.days)

    try:
        bindings = execute_sparql_query(config, query)
    except requests.RequestException as e:
        print(f"HTTP error querying Fuseki: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error parsing Fuseki response: {e}", file=sys.stderr)
        return 1

    summaries = parse_results_to_day_summaries(bindings)
    
    # Log all summaries for debugging
    logger.debug(f"Total days found in query: {len(summaries)}")
    for summary in summaries:
        logger.debug(f"Day: {summary.date} ({summary.weekday}), Count: {summary.count}")
    
    suspicious_days = find_suspicious_days(
        summaries,
        threshold=config.num_daily_articles_threshold,
    )
    
    # Log suspicious days filtering
    logger.debug(f"Suspicious days found: {len(suspicious_days)}")
    for day in suspicious_days:
        logger.debug(f"Suspicious: {day.date} ({day.weekday}), Count: {day.count} < {config.num_daily_articles_threshold}")

    print(
        f"Checking last {args.days} days (excluding Mondays) "
        f"against threshold NUM_DAILY_ARTICLES_TRIGGER={config.num_daily_articles_threshold}"
    )
    print()

    if not suspicious_days:
        print("No non-Monday days found with article counts below threshold.")
        return 0

    # Simple table-like output
    print(f"{'Date':<12} {'Weekday':<10} {'Count':>5}")
    print("-" * 30)
    for s in suspicious_days:
        print(f"{s.date.isoformat():<12} {s.weekday:<10} {s.count:>5}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
