# Directus GraphQL Integration

This project includes a clean, well-structured function/class for querying the Directus backend using GraphQL to count articles by date.

## Features

- **DirectusConfig**: Configuration class for Directus GraphQL API
- **DirectusClient**: Client class for executing GraphQL queries
- **Convenience functions**: Simple wrappers for common use cases
- **Flexible date handling**: Support for both single dates and date ranges
- **Error handling**: Robust error handling with logging
- **Environment configuration**: Uses `.env` for secure credential management

## Files

- `main.py` - Contains the Directus GraphQL functionality integrated with existing SPARQL functionality
- `example_directus.py` - Example script demonstrating how to use the Directus features
- `.env.template` - Template for environment variables
- `README.md` - This documentation

## Quick Start

1. **Set up environment variables:**
   ```bash
   cp .env.template .env
   ```
   
   Edit `.env` and add your Directus configuration:
   ```env
   DIRECTUS_BASE_URL=https://directus.ilmanifesto.it
   DIRECTUS_JWT=your_jwt_token_here
   ```

2. **Run the example:**
   ```bash
   python example_directus.py
   ```

## Usage Examples

### Basic Usage

```python
from main import count_articles_for_date, count_articles_for_date_range

# Count articles for a specific date
article_count = count_articles_for_date("2025-11-20")
print(f"Found {article_count} articles")

# Count articles for a date range
date_counts = count_articles_for_date_range("2025-11-18", "2025-11-20")
for date, count in date_counts.items():
    print(f"{date}: {count} articles")
```

### Advanced Usage

```python
from main import DirectusClient, load_directus_config

# Load configuration
config = load_directus_config()

# Create client
client = DirectusClient(config)

# Execute queries
count = client.count_articles_by_date("2025-11-20")
range_counts = client.count_articles_by_date_range("2025-11-18", "2025-11-20")
```

## Configuration

The system uses environment variables for configuration:

### Required Variables

- `DIRECTUS_BASE_URL`: The base URL of your Directus instance (e.g., `https://directus.ilmanifesto.it`)
- `DIRECTUS_JWT`: JWT token for authentication (from your Directus backend)

### Optional Variables

The system also supports Fuseki configuration for the existing SPARQL functionality:
- `FUSEKI_SERVICE`
- `FUSEKI_ENDPOINT`
- `FUSEKI_DATASET`
- `NUM_DAILY_ARTICLES_TRIGGER`

## GraphQL Queries

The implementation uses optimized GraphQL queries:

### Single Date Query
```graphql
query CountArticles($date: String!) {
    articles_aggregated(
        filter: {
            datePublished: {
                _eq: $date
            }
        }
    ) {
        count {
            count
        }
    }
}
```

### Date Range Query
```graphql
query CountArticlesByRange($startDate: String!, $endDate: String!) {
    articles_aggregated(
        filter: {
            datePublished: {
                _between: [$startDate, $endDate]
            }
        }
    ) {
        groupBy {
            datePublished
            count {
                count
            }
        }
    }
}
```

## API Reference

### DirectusConfig

Configuration class for Directus GraphQL API.

**Properties:**
- `base_url`: Base URL of Directus instance
- `jwt_token`: JWT token for authentication
- `graphql_url`: Computed GraphQL endpoint URL

### DirectusClient

Client for interacting with Directus GraphQL API.

**Methods:**
- `count_articles_by_date(target_date: str) -> int`: Count articles for a specific date
- `count_articles_by_date_range(start_date: str, end_date: str) -> Dict[str, int]`: Count articles for a date range

### Convenience Functions

- `count_articles_for_date(date_str: str, config: Optional[DirectusConfig] = None) -> int`
- `count_articles_for_date_range(start_date: str, end_date: str, config: Optional[DirectusConfig] = None) -> Dict[str, int]`

## Error Handling

The implementation includes comprehensive error handling:

- **HTTP Errors**: Logged and handled gracefully
- **GraphQL Errors**: Checked and reported
- **Network Issues**: Timeout handling and connection error management
- **Response Parsing**: Safe extraction of data with fallback values

All errors are logged using Python's logging module with appropriate log levels.

## Integration with Existing Code

The Directus functionality is seamlessly integrated with the existing SPARQL functionality in `main.py`. Both systems can be used independently or together, sharing the same configuration and logging infrastructure.

## Security Notes

- **JWT Token**: Never commit the `.env` file with real tokens to version control
- **Environment Variables**: Use environment variables for sensitive configuration
- **HTTPS**: Always use HTTPS URLs for production deployments
- **Token Expiry**: JWT tokens may expire and need to be refreshed periodically

## Development

### Requirements

- Python 3.7+
- requests
- python-dotenv

### Testing

Run the example script to verify functionality:
```bash
python example_directus.py
```

### Logging

Enable debug logging to see GraphQL queries and responses:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Schema Adaptation

The GraphQL queries may need adjustment based on your actual Directus schema. The implementation includes comments indicating where schema-specific changes may be needed.

**Areas that may need customization:**
- Field names in GraphQL queries
- Response parsing structure
- Aggregation methods

## License

This code is provided as-is for educational and development purposes.