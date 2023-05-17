"""A module for converting JIRA issues to JSON format."""

__author__ = "Bar Harel"
__version__ = "0.1.0"
__license__ = "MIT License"
__all__ = [""]

import logging
from typing import Iterator
import requests
from urllib.parse import urljoin, urlencode
import json
from itertools import islice
import csv
import os
import dotenv
from collections import Counter

dotenv.load_dotenv()
logger = logging.Logger(__name__)

BATCH_SIZE = 20

# JIRA API URL for CSV
CSV_API = '/sr/jira.issueviews:searchrequest-csv-all-fields/temp/SearchRequest.csv'


def iterate_jira_issues(base_url: str, token: str, jql: str) -> Iterator[dict]:
    """Iterate over JIRA issues from the JIRA API.

    Args:
        base_url: The base URL of the JIRA server.
        token: The API token to use for authentication.
        jql: The JQL query to use for the search.

    Yields:
        A dictionary representing a single JIRA issue.
    """
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    url = urljoin(base_url, CSV_API)
    start_at = 0
    headers = None
    single_headers = None
    response = None
    while True:

        with session.get(
                url,
                params={"jqlQuery": jql,
                        "tempMax": BATCH_SIZE,
                        "pager/start": start_at, },
                stream=True) as response:
            if not response.ok:
                logger.error(
                    "Failed to get issues from JIRA. "
                    "Status code: %s."
                    + (" Perhaps the JQL query is invalid?" if
                       response.status_code == 400 else "") +
                       " Response: %s.",
                    response.status_code, response.text)
                response.raise_for_status()

            reader = csv.reader(response.iter_lines(
                decode_unicode=True, delimiter="\n"))
            header = next(reader, None)
            if not header:
                break
            header_count = Counter(header)
            new_headers = set(header_count)
            new_single_headers = set(
                (key for key, value in header_count.items() if value == 1))

            if headers is not None and (new_headers != headers or
                                        new_single_headers != single_headers):
                assert single_headers is not None
                removed = headers-new_headers
                new = new_headers-headers
                changed = new | removed
                single_changed = single_headers ^ new_single_headers
                single_changed -= changed
                logger.warning("Jira fields changed between batches. Diff - "
                               "Removed fields: %s ;  New fields: %s ; "
                               "Changed from single to list or opposite: %s",
                               tuple(headers-new_headers),
                               tuple(new_headers-headers),
                               tuple(single_changed))

            single_headers = new_single_headers
            headers = new_headers

            for row in map(iter, filter(None, reader)):  # type: ignore
                output: dict = {}
                for key, value in header_count.items():
                    if value > 1:
                        output[key] = list(
                            filter(None, islice(row, value)))  # type: ignore
                    else:
                        output[key] = next(row) or None
                yield output

            start_at += BATCH_SIZE


def main():
    """Entry point of the program."""
    token = os.getenv("JIRA_TOKEN")
    if not token:
        raise ValueError("JIRA_TOKEN environment variable is not set")

    base_url = os.getenv("JIRA_BASE_URL")
    if not base_url:
        raise ValueError("JIRA_BASE_URL environment variable is not set")
    import pprint
    for i in iterate_jira_issues(base_url, token, "ORDER BY WORKLOGDATE ASC"):
        pprint.pprint(i)
        break


if __name__ == "__main__":
    main()
