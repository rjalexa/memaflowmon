# MeMaFlow Monitor

**Directus vs Fuseki Integrity Monitor**

`memaflowmon` is an asynchronous integrity monitoring tool designed to verify consistency between **Directus** (the CMS/Source of Truth) and **Apache Jena Fuseki** (the Knowledge Graph). It ensures that articles published in Directus are correctly ingested, indexed, and present in the Knowledge Graph.

## Features

- **Integrity Verification**: Fetches published articles from Directus and verifies their existence in Fuseki.
- **Mention Counting**: Checks if articles have associated mentions in the graph.
- **Threshold Monitoring**: Alerts if the daily article count or mention count falls below configured thresholds.
- **Asynchronous Execution**: Uses `aiohttp` and `asyncio` for high-performance concurrent checks.
- **Reporting**:
  - Generates CSV reports for missing articles.
  - Sends HTML email alerts with detailed summaries.
- **Connectivity Checks**: Verifies access to Directus and Fuseki before running logic.

## Prerequisites

- **Python 3.13+**
- **uv** (recommended) or `pip` for dependency management.
- Access to a **Directus** instance (API URL & Token).
- Access to a **Fuseki** SPARQL endpoint.
- An SMTP server for sending email alerts.

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd directusmon
   ```

2. **Install dependencies:**
   Using `uv` (recommended):
   ```bash
   uv sync
   ```
   Or using `pip`:
   ```bash
   pip install .
   ```

## Configuration

1. Copy the template configuration file:
   ```bash
   cp .env.template .env
   ```

2. Edit `.env` with your specific settings:

   **Fuseki Settings:**
   - `FUSEKI_SERVICE`: Base URL of the Fuseki server (e.g., `http://localhost:3030`).
   - `FUSEKI_DATASET`: Name of the dataset (e.g., `memav7`).
   - `FUSEKI_ENDPOINT`: Query endpoint (default: `/query/`).

   **Directus Settings:**
   - `DIRECTUS_BASE_URL`: URL of your Directus instance.
   - `DIRECTUS_JWT`: API Token for authentication.

   **Thresholds:**
   - `NUM_DAILY_ARTICLES_TRIGGER`: Minimum expected articles per day (default: 30).
   - `NUM_DAILY_MENTIONS_TRIGGER`: Minimum expected mentions per day (default: 300).

   **Email / SMTP:**
   - `MAILSMTP`: SMTP server address (e.g., `smtp.example.com:587`).
   - `MAILUSER`: SMTP username.
   - `MAILPASS`: SMTP password.
   - `MAILTO1`: Recipient email address (add `MAILTO2`, `MAILTO3`, etc. for more).

## Usage

Run the monitor using the command line. You can specify a date range to check.

### Basic Usage (Check Today)
```bash
python src/memaflowmon.py
```

### Check a Specific Date
```bash
python src/memaflowmon.py 2023-10-25
```

### Check a Date Range
```bash
python src/memaflowmon.py 2023-10-01 2023-10-31
```

## Workflow

1. **Connectivity Check**: The script first pings Directus and Fuseki. If either is unreachable, it sends a "Connectivity Alert" email and aborts.
2. **Data Fetching**: It retrieves all *published* articles from Directus for the specified date range.
3. **Graph Verification**: For every article, it queries Fuseki (concurrently) to:
   - Confirm the article URI exists.
   - Count the number of mentions linked to the article.
4. **Analysis**:
   - Compares counts against `NUM_DAILY_ARTICLES_TRIGGER` and `NUM_DAILY_MENTIONS_TRIGGER`.
   - Identifies specific articles missing from the graph.
   - **Note**: Mondays are treated as exceptions for low article counts (standard editorial schedule).
5. **Reporting**:
   - If issues are found:
     - A CSV file listing missing articles is saved to the `output/` directory.
     - An email alert is sent to configured recipients with a summary and list of errors.
   - If no issues are found, it logs a success message and exits.

## Output

- **Console Logs**: Real-time progress and error logging.
- **CSV Reports**: Located in `output/YYYYMMDD_missing_from_graph.csv`.
- **Email Alerts**: HTML formatted emails containing:
  - Summary of issues.
  - List of missing articles with links.
  - System hostname/IP for identification.

## Project Structure

- `src/memaflowmon.py`: Main application logic and entry point.
- `src/sendmail.py`: Utility for sending SMTP emails.
- `src/system_info.py`: Utility for retrieving host system information.
- `.env.template`: Template for environment variables.
- `pyproject.toml`: Project metadata and dependencies.