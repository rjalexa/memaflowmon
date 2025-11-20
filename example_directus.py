#!/usr/bin/env python3
"""
Example script demonstrating Directus GraphQL functionality.

This script shows how to use the Directus client to count articles
by date using the GraphQL API.
"""

import datetime as dt
import os
import sys
from dotenv import load_dotenv

# Import the Directus functionality from main.py
from main import count_articles_for_date, count_articles_for_date_range, DirectusClient, load_directus_config


def main():
    """Demonstrate Directus functionality."""
    
    # Load environment variables
    load_dotenv()
    
    print("=== Directus GraphQL Example ===")
    print()
    
    # Example 1: Count articles for a specific date
    print("1. Counting articles for a specific date...")
    target_date = "2025-11-19"  # Using the date that has 40 articles
    
    try:
        article_count = count_articles_for_date(target_date)
        print(f"   Date: {target_date}")
        print(f"   Articles found: {article_count}")
        print()
    except Exception as e:
        print(f"   Error: {e}")
        print()
    
    # Example 2: Count articles for a date range
    print("2. Counting articles for a date range...")
    start_date = "2025-11-18"
    end_date = "2025-11-19"
    
    try:
        date_counts = count_articles_for_date_range(start_date, end_date)
        print(f"   Range: {start_date} to {end_date}")
        print("   Daily counts:")
        for date, count in sorted(date_counts.items()):
            print(f"     {date}: {count} articles")
        print()
    except Exception as e:
        print(f"   Error: {e}")
        print()
    
    # Example 3: Using DirectusClient directly
    print("3. Using DirectusClient directly...")
    try:
        config = load_directus_config()
        client = DirectusClient(config)
        
        # Test connectivity
        test_count = client.count_articles_by_date("2025-11-19")
        print(f"   Direct client test: {test_count} articles found")
        print()
    except Exception as e:
        print(f"   Error: {e}")
        print()
    
    # Example 4: Working with current date
    print("4. Working with current date...")
    today = dt.date.today().isoformat()
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    
    try:
        today_count = count_articles_for_date(today)
        yesterday_count = count_articles_for_date(yesterday)
        
        print(f"   Today ({today}): {today_count} articles")
        print(f"   Yesterday ({yesterday}): {yesterday_count} articles")
        print()
    except Exception as e:
        print(f"   Error: {e}")
        print()


if __name__ == "__main__":
    main()