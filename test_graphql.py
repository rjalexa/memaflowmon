#!/usr/bin/env python3
import os
import sys
import json
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get configuration
base_url = os.getenv("DIRECTUS_BASE_URL")
jwt_token = os.getenv("DIRECTUS_JWT")

if not base_url or not jwt_token:
    print("Missing Directus configuration")
    sys.exit(1)

graphql_url = f"{base_url.rstrip('/')}/graphql"
headers = {
    "Authorization": f"Bearer {jwt_token}",
    "Content-Type": "application/json"
}

print("=== Testing Directus GraphQL ===")
print(f"URL: {graphql_url}")

# Test 1: Simple query
print("\n1. Testing simple query...")
simple_query = {
    "query": """
    query {
      articles(limit: 3) {
        id
        headline
        datePublished
      }
    }
    """
}

try:
    response = requests.post(graphql_url, headers=headers, json=simple_query, timeout=10)
    print(f"Status: {response.status_code}")
    print("Response:", json.dumps(response.json(), indent=2))
except Exception as e:
    print(f"Error: {e}")

# Test 2: Aggregated query
print("\n2. Testing aggregated query...")
aggregated_query = {
    "query": """
    query {
      articles_aggregated {
        countAll
      }
    }
    """
}

try:
    response = requests.post(graphql_url, headers=headers, json=aggregated_query, timeout=10)
    print("Status:", response.status_code)
    print("Response:", json.dumps(response.json(), indent=2))
except Exception as e:
    print("Error:", e)

# Test 3: Filtered aggregated query
print("\n3. Testing filtered aggregated query...")
filtered_query = {
    "query": """
    query FilteredCount($date: String!) {
      articles_aggregated(
        filter: {
          datePublished: {
            _eq: $date
          }
        }
      ) {
        countAll
      }
    }
    """,
    "variables": {
        "date": "2002-12-03"
    }
}

try:
    response = requests.post(graphql_url, headers=headers, json=filtered_query, timeout=10)
    print("Status:", response.status_code)
    print("Response:", json.dumps(response.json(), indent=2))
except Exception as e:
    print("Error:", e)

# Test 4: Simple filtered query (no aggregation)
print("\n4. Testing simple filtered query...")
simple_filtered_query = {
    "query": """
    query FilteredArticles($date: String!) {
      articles(
        filter: {
        datePublished: {
          _eq: $date
        }
      }
      limit: 10
    ) {
      id
      headline
      datePublished
    }
  }
  """,
    "variables": {
        "date": "2002-12-03"
    }
}

try:
    response = requests.post(graphql_url, headers=headers, json=simple_filtered_query, timeout=10)
    print("Status:", response.status_code)
    result = response.json()
    print("Response:", json.dumps(result, indent=2))
    if 'data' in result and 'articles' in result['data']:
        articles = result['data']['articles']
        print(f"Found {len(articles)} articles for {articles[0]['datePublished'] if articles else 'no articles'}")
except Exception as e:
    print("Error:", e)

print("\n=== Test completed ===")