#!/usr/bin/env python3
"""
Working implementation for Directus article counting.
Updated to match main.py logic using articleEdition.editionDate.
"""

import os
import requests
from dotenv import load_dotenv
from typing import Dict

# Load environment variables
load_dotenv()

# Get configuration
base_url = os.getenv("DIRECTUS_BASE_URL")
jwt_token = os.getenv("DIRECTUS_JWT")

if not base_url or not jwt_token:
    print("Missing Directus configuration")
    exit(1)

# Headers for authentication
headers = {"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"}


class DirectusClient:
    """Client for interacting with Directus REST API."""

    def __init__(self, base_url: str, jwt_token: str):
        self.base_url = base_url.rstrip("/")
        self.jwt_token = jwt_token
        self.headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json",
        }

    def count_articles_by_date(self, target_date: str) -> int:
        """
        Count articles published on a specific date using REST API.

        Args:
            target_date: Date in YYYY-MM-DD format

        Returns:
            Number of articles found for the date
        """
        # Use the logic from main.py
        date_filter = f"{target_date}"

        # Build the REST API URL with filter using articleEdition.editionDate
        url = f"{self.base_url}/items/articles"
        params = {
            "filter[articleEdition][editionDate][_eq]": date_filter,
            "fields": "id",  # Only get IDs to minimize response size
            "limit": -1,  # Get all matching articles to get accurate count
        }

        response = requests.get(url, headers=self.headers, params=params, timeout=30)

        if response.status_code != 200:
            print(f"Error {response.status_code}: {response.text}")
            return 0

        data = response.json()
        return len(data.get("data", []))

    def count_articles_by_date_range(
        self, start_date: str, end_date: str
    ) -> Dict[str, int]:
        """
        Count articles for each date in a range using REST API.

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            Dictionary mapping dates to article counts
        """
        # Build the REST API URL with date range filter using articleEdition.editionDate
        url = f"{self.base_url}/items/articles"
        params = {
            "filter[articleEdition][editionDate][_gte]": start_date,
            "filter[articleEdition][editionDate][_lte]": end_date,
            "fields": "id,articleEdition.editionDate",  # Get ID and the correct date field
            "limit": -1,  # Get all results
        }

        response = requests.get(url, headers=self.headers, params=params, timeout=30)

        if response.status_code != 200:
            print(f"Error {response.status_code}: {response.text}")
            return {}

        data = response.json()
        articles = data.get("data", [])

        # Count by date
        date_counts = {}
        for article in articles:
            # Extract date from the nested articleEdition object
            article_edition = article.get("articleEdition", {})
            edition_date = article_edition.get("editionDate")
            
            if edition_date:
                # Extract just the date part (YYYY-MM-DD)
                date_only = edition_date[:10]
                date_counts[date_only] = date_counts.get(date_only, 0) + 1

        return date_counts


def main():
    """Test the Directus functionality."""

    if not base_url or not jwt_token:
        print("Missing Directus configuration")
        return

    client = DirectusClient(base_url, jwt_token)

    print("=== Testing Directus REST API (Using articleEdition logic) ===")

    # Test date range
    start_date = "2025-11-01"
    end_date = "2025-11-20"
    print(f"\n2. Testing edition date range: {start_date} to {end_date}")

    try:
        date_counts = client.count_articles_by_date_range(start_date, end_date)
        print("   Daily edition counts:")
        for date, count in sorted(date_counts.items()):
            print(f"     {date}: {count} articles")
    except Exception as e:
        print(f"   Error: {e}")

    print("\n=== Test completed ===")


if __name__ == "__main__":
    main()