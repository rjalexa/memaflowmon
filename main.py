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
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
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


def build_articles_query(days: int) -> str:
    """
    Build a SPARQL query that groups articles by mema:published_day
    for the last `days` days (inclusive of today).
    
    We calculate the date range in Python to ensure consistent timezone handling.
    """
    # Calculate today and start date in Python to avoid timezone issues
    today = dt.date.today()
    start_date = today - dt.timedelta(days=days - 1)  # -1 because we include today
    
    # Format dates as SPARQL date literals
    today_literal = f'"{today.isoformat()}"^^xsd:date'
    start_date_literal = f'"{start_date.isoformat()}"^^xsd:date'

    return f"""
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX mema:  <http://ilmanifesto.it/ontology#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>

SELECT
  ?published_day
  (COUNT(?article) AS ?count)
WHERE {{
  # match articles in the date range {start_date} to {today}
  ?article rdf:type mema:Article ;
           mema:published_day ?published_day .
  FILTER(
    xsd:date(?published_day) >= {start_date_literal} &&
    xsd:date(?published_day) <= {today_literal}
  )
}}
GROUP BY
  ?published_day
ORDER BY
  DESC(xsd:date(?published_day))
"""


def build_mentions_query(days: int) -> str:
    """
    Build a SPARQL query that counts total mentions per day for the last `days` days.
    
    This query directly counts all mentions per day without nested subqueries,
    providing the total number of mentions found in the graph for every article of a given day.
    """
    # Calculate today and start date in Python to ensure consistent timezone handling
    today = dt.date.today()
    start_date = today - dt.timedelta(days=days - 1)  # -1 because we include today
    
    # Format dates as SPARQL date literals
    today_literal = f'"{today.isoformat()}"^^xsd:date'
    start_date_literal = f'"{start_date.isoformat()}"^^xsd:date'

    return f"""
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX mema:  <http://ilmanifesto.it/ontology#>
PREFIX xsd:   <http://www.w3.org/2001/XMLSchema#>

SELECT
  ?published_day
  (COUNT(?sign) AS ?total_mentions)
WHERE {{
  # match articles and their mentions in the date range {start_date} to {today}
  ?article rdf:type           mema:Article ;
           mema:published_day  ?published_day ;
           mema:yields ?sign .
  ?sign a mema:Mention .
  
  FILTER(
    xsd:date(?published_day) >= {start_date_literal} &&
    xsd:date(?published_day) <= {today_literal}
  )
}}
GROUP BY
  ?published_day
ORDER BY
  DESC(xsd:date(?published_day))
"""


def execute_sparql_query(config: FusekiConfig, query: str, timeout: int = 30) -> List[Dict[str, Any]]:
    """
    Execute a SPARQL SELECT query against Fuseki and return the 'bindings' list.
    
    Args:
        config: Fuseki configuration
        query: SPARQL query string
        timeout: Request timeout in seconds (default: 30)
    """
    url = config.query_url
    headers = {
        "Accept": "application/sparql-results+json",
    }
    params = {
        "query": query,
    }

    logger.debug(f"Executing SPARQL query against: {url}")
    logger.debug(f"Query: {query}")

    resp = requests.get(url, headers=headers, params=params, timeout=timeout)
    
    if resp.status_code != 200:
        logger.error(f"HTTP Error {resp.status_code}: {resp.text}")
        resp.raise_for_status()

    data = resp.json()
    bindings = data.get("results", {}).get("bindings", [])
    logger.debug(f"Query returned {len(bindings)} bindings")
    
    return bindings


# ---------------------------------------------------------------------------
# Business logic
# ---------------------------------------------------------------------------


@dataclass
class DaySummary:
    date: dt.date
    weekday: str
    count: int
    total_mentions: int = 0
    avg_mentions_per_article: float = 0.0


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
    try:
        # Test with a simple SPARQL query instead of just GET
        test_query = "SELECT ?s WHERE { ?s ?p ?o } LIMIT 1"
        test_params = {"query": test_query}
        test_response = requests.get(config.query_url, params=test_params, timeout=10)
        if test_response.status_code != 200:
            logger.warning(f"Endpoint returned status {test_response.status_code}")
    except requests.RequestException as e:
        logger.error(f"Failed to reach endpoint {config.query_url}: {e}")
        return 1

    # Build and execute articles query
    articles_query = build_articles_query(days=args.days)

    try:
        article_bindings = execute_sparql_query(config, articles_query)
    except requests.RequestException as e:
        print(f"HTTP error querying Fuseki for articles: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error parsing Fuseki article response: {e}", file=sys.stderr)
        return 1

    # Build and execute mentions query
    mentions_query = build_mentions_query(days=args.days)

    try:
        # Use longer timeout for mentions query as it processes more data
        mention_bindings = execute_sparql_query(config, mentions_query, timeout=120)
    except requests.RequestException as e:
        logger.warning(f"HTTP error querying Fuseki for mentions: {e}")
        logger.info("Skipping mentions data due to timeout or connection issues")
        mention_bindings = []
    except ValueError as e:
        logger.warning(f"Error parsing Fuseki mention response: {e}")
        logger.info("Skipping mentions data due to parsing issues")
        mention_bindings = []

    # Parse article results
    summaries = parse_results_to_day_summaries(article_bindings)
    
    # Parse mention results into a dictionary for efficient lookup
    mentions_by_day = {}
    for binding in mention_bindings:
        published_val = binding["published_day"]["value"]
        total_mentions_val = binding["total_mentions"]["value"]
        
        d = dt.date.fromisoformat(published_val)
        total_mentions = int(total_mentions_val)
        mentions_by_day[d] = total_mentions
    
    # Combine article counts with mention counts and calculate averages
    for summary in summaries:
        summary.total_mentions = mentions_by_day.get(summary.date, 0)
        # Calculate average mentions per article (avoid division by zero)
        if summary.count > 0:
            summary.avg_mentions_per_article = summary.total_mentions / summary.count
        else:
            summary.avg_mentions_per_article = 0.0
    
    suspicious_days = find_suspicious_days(
        summaries,
        threshold=config.num_daily_articles_threshold,
    )

    print(
        f"Checking last {args.days} days (excluding Mondays) "
        f"against threshold NUM_DAILY_ARTICLES_TRIGGER={config.num_daily_articles_threshold}"
    )
    print()

    # Always show summary of all days first
    print("SUMMARY OF ALL DAYS:")
    print(f"{'Date':<12} {'Weekday':<10} {'Articles':>8} {'Mentions':>8} {'Avg Mentions':>12}")
    print("-" * 54)
    for s in summaries:
        print(f"{s.date.isoformat():<12} {s.weekday:<10} {s.count:>8} {s.total_mentions:>8} {s.avg_mentions_per_article:>12.1f}")
    print()

    # Then show suspicious days if any
    if not suspicious_days:
        print("No non-Monday days found with article counts below threshold.")
        return 0

    print("SUSPICIOUS DAYS (below threshold):")
    print(f"{'Date':<12} {'Weekday':<10} {'Count':>5}")
    print("-" * 30)
    for s in suspicious_days:
        print(f"{s.date.isoformat():<12} {s.weekday:<10} {s.count:>5}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
