#!/usr/bin/env python3
import os
import sys
import argparse
import requests
import re
import unicodedata
from dotenv import load_dotenv

# --- CHANGE START ---
# Calculate path to .env one directory up
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
env_path = os.path.join(parent_dir, ".env")

# Load environment variables from the specific path
load_dotenv(dotenv_path=env_path, override=True)
# --- CHANGE END ---

BASE_URL = os.getenv("DIRECTUS_BASE_URL")
JWT_TOKEN = os.getenv("DIRECTUS_JWT")

FUSEKI_SERVICE = os.getenv("FUSEKI_SERVICE")
FUSEKI_DATASET = os.getenv("FUSEKI_DATASET")
FUSEKI_ENDPOINT_PATH = os.getenv("FUSEKI_ENDPOINT", "/query")

SPARQL_ENDPOINT = None
if FUSEKI_SERVICE and FUSEKI_DATASET:
    base = FUSEKI_SERVICE.rstrip("/")
    dataset = FUSEKI_DATASET.strip("/")
    endpoint = FUSEKI_ENDPOINT_PATH.strip("/")
    SPARQL_ENDPOINT = f"{base}/{dataset}/{endpoint}"

if not BASE_URL or not JWT_TOKEN:
    print(
        "Error: Missing DIRECTUS_BASE_URL or DIRECTUS_JWT in .env file", file=sys.stderr
    )
    print(f"Looked for .env at: {env_path}", file=sys.stderr)
    sys.exit(1)

if not SPARQL_ENDPOINT:
    print(
        "Error: Missing FUSEKI_SERVICE or FUSEKI_DATASET in .env file", file=sys.stderr
    )
    sys.exit(1)


def check_article_exists(uri):
    if SPARQL_ENDPOINT is None:
        return "ERROR"

    query = f"""
    PREFIX mema: <http://ilmanifesto.it/ontology#>
    ASK {{
        <{uri}> a mema:Article .
    }}
    """

    try:
        response = requests.get(
            SPARQL_ENDPOINT,
            params={"query": query},
            headers={"Accept": "application/sparql-results+json"},
            timeout=10,
        )
        if response.status_code == 200:
            return response.json().get("boolean", False)
        return "ERROR"
    except Exception:
        return "ERROR"


def slugify(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens.
    """
    value = str(value)
    value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    value = re.sub(r"[-\s]+", "-", value)
    return value


def fetch_articles(start_date: str, end_date: str):
    """
    Fetch articles between two dates including ID, Title, and Edition Date.
    """
    # Ensure start_date is before end_date
    if start_date > end_date:
        print(f"Swapping dates: {start_date} > {end_date}", file=sys.stderr)
        start_date, end_date = end_date, start_date

    if BASE_URL is None:
        print("Error: BASE_URL is not set.", file=sys.stderr)
        return

    base = BASE_URL.rstrip("/")
    url = f"{base}/items/articles"

    headers = {
        "Authorization": f"Bearer {JWT_TOKEN}",
        "Content-Type": "application/json",
    }

    # Retrieve ID, Headline, Published Date, and Edition details
    fields = "id,headline,datePublished,articleEdition.editionDate"

    params = {
        "filter[syncSource][_eq]": "wp",
        "filter[articleEdition][editionDate][_gte]": start_date,
        "filter[articleEdition][editionDate][_lte]": end_date,
        "fields": fields,
        "limit": -1,  # No limit
        "sort": "articleEdition.editionDate",
    }

    # print(f"Querying Directus: {start_date} to {end_date}...")

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)

        if response.status_code != 200:
            print(f"Error {response.status_code}: {response.text}", file=sys.stderr)
            return

        data = response.json()
        articles = data.get("data", [])

        # print(f"Found {len(articles)} articles.\n")

        for article in articles:
            headline = article.get("headline", "(No Headline)")
            art_pub_date = article.get("datePublished", "N/A")

            if art_pub_date and len(art_pub_date) >= 10:
                art_pub_date = art_pub_date[:10]

            slug = slugify(headline)
            url = f"http://ilmanifesto.it/kg/article#{art_pub_date}-{slug}"

            exists = check_article_exists(url)

            # ANSI escape codes for colors
            GREEN = "\033[92m"
            RED = "\033[91m"
            RESET = "\033[0m"

            edition_date = "N/A"
            if article.get("articleEdition") and article["articleEdition"].get(
                "editionDate"
            ):
                edition_date = article["articleEdition"]["editionDate"]

            if exists is True:
                print(f"{edition_date} {GREEN}{url}{RESET}")
            elif exists is False:
                print(f"{edition_date} {RED}{url} MISSING{RESET}")
            else:
                print(f"{edition_date} {RED}{url} SPARQL_ERROR{RESET}")

    except requests.RequestException as e:
        print(f"Connection error: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch article list from Directus by Date Range"
    )
    parser.add_argument("start", help="Start Date (YYYY-MM-DD)")
    parser.add_argument("end", help="End Date (YYYY-MM-DD)")

    args = parser.parse_args()

    fetch_articles(args.start, args.end)


if __name__ == "__main__":
    main()
