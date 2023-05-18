"""A module for converting JIRA issues to JSON lines format."""

__author__ = "Bar Harel"
__version__ = "0.1.0"
__license__ = "MIT License"
# __all__ = []

import logging
from typing import Any
from collections.abc import Iterator, Iterable, MutableMapping
import typing
import requests
from urllib.parse import urljoin, urlencode
import json
from itertools import islice
import csv
import argparse
import os
import dotenv
from collections import Counter

dotenv.load_dotenv()
logger = logging.Logger(__name__)

BATCH_SIZE = 500

# JIRA API URL for CSV
CSV_API = '/sr/jira.issueviews:searchrequest-csv-all-fields/temp/SearchRequest.csv'


def _log_work_converter(log_work: str | list[str] | None) -> list[dict[str, Any]] | None:
    """Convert a log work string to a dictionary.

    Example:
        >>> _log_work_converter("comment;started;author;timeSpentSeconds")
        [{'comment': 'comment', 'started': 'started', 'author': 'author',
            'timeSpentSeconds': 'timeSpentSeconds'}]

    Args:
        log_work: A string or list of strings representing the log work entry.
            The string should be in the format of
            "comment;started;author;timeSpentSeconds". If None, an empty
            string, or an empty list, an empty dictionary is returned.

    Returns:
        A list of dictionaries representing the log work entries.
    """
    # None, empty string, or empty list
    if not log_work:
        return None

    if isinstance(log_work, str):
        log_work = [log_work]
    
    # Jira is stupid and doesn't escape semicolons in the log work
    values = map(lambda x: x.rsplit(";", maxsplit=3), log_work)
    return [dict(zip(("comment", "started", "author", "timeSpentSeconds"),
                     value)) for value in values]

def _comment_converter(comment: str | list[str] | None) -> list[dict[str, Any]] | None:
    """Convert a log work string to a dictionary.

    Example:
        >>> _log_work_converter("comment;started;author;timeSpentSeconds")
        [{'comment': 'comment', 'started': 'started', 'author': 'author',
            'timeSpentSeconds': 'timeSpentSeconds'}]

    Args:
        comment: A string or list of strings representing the log work entry.
            The string should be in the format of
            "comment;started;author;timeSpentSeconds". If None, an empty
            string, or an empty list, an empty dictionary is returned.

    Returns:
        A list of dictionaries representing the log work entries.
    """
    # None, empty string, or empty list
    if not comment:
        return None

    if isinstance(comment, str):
        comment = [comment]
    
    # Jira is stupid and doesn't escape semicolons in the log work
    values = map(lambda x: x.split(";", maxsplit=2), comment)
    return [dict(zip(("datetime", "author", "comment"),
                     value)) for value in values]


converters = {
    "Log Work": _log_work_converter,
}


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


def save_jsons_to_file(jsons: Iterable[dict],
                       fileobj: typing.TextIO) -> None:
    """Save a list of JSONs to a file.

    Args:
        jsons: An iterator of JSONable dictionaries to save.
        fileobj: A file-like object to save the JSONs to.
    """
    for json_ in jsons:
        json.dump(json_, fileobj)
        fileobj.write("\n")

def convert_jsons(jsons: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Apply the converters to the JSONs.
    
    Args:
        jsons: An iterator of JSONable dictionaries to convert.

    Yields:
        The converted JSONs.
    """
    for json_ in jsons:
        for key, converter in converters.items():
            json_[key] = converter(json_.get(key))
        yield json_


def main():
    """Entry point of the program."""
    token = os.getenv("JIRA_TOKEN")
    if not token:
        raise ValueError("JIRA_TOKEN environment variable is not set")

    base_url = os.getenv("JIRA_BASE_URL")
    if not base_url:
        raise ValueError("JIRA_BASE_URL environment variable is not set")

    jsons = iterate_jira_issues(base_url, token, "ORDER BY WORKLOGDATE ASC")
    with open("jira_issues.jsonl", "w") as fileobj:
        save_jsons_to_file(jsons, fileobj)


if __name__ == "__main__":
    """Entry point of the program."""
    parser = argparse.ArgumentParser(
        description='Convert JIRA issues to JSON format.')

    parser.add_argument("--jql", type=str,
                        help="The JQL query to use for the search. By default, "
                        "all issues are returned.")

    def _default_environ(key: str) -> dict[str, Any]:
        """Return a dict with the default value of an environment variable.

        Args:
            key: The name of the environment variable.

        Returns:
            A dict with the default value of the environment variable, or
            {'required': True} if the environment variable is not set.
        """
        return {'default': value} if (value := os.getenv(key)) is not None else {
            "required": True}

    parser.add_argument('-u', '--base_url', type=str, **_default_environ("JIRA_BASE_URL"),
                        help='The base URL of the JIRA server. '
                        'Can also be set using the JIRA_BASE_URL environment '
                        'variable.')

    parser.add_argument("-t", "--token", type=str, **_default_environ("JIRA_TOKEN"),
                        help="The API token to use for authentication. "
                        "Can also be set using the JIRA_TOKEN environment "
                        "variable.")

    parser.add_argument("-o", "--output", type=str, default="jira_issues.jsonl",
                        help="The output file to save the JSONs to. "
                        "By default, the JSONs are saved to "
                        "'jira_issues.jsonl.' "
                        "If the file already exists, it will be overwritten.")

    args = parser.parse_args()

    jsons = iterate_jira_issues(
        args.base_url, args.token, args.jql)
    jsons = convert_jsons(jsons)

    with open(args.output, "w") as fileobj:
        save_jsons_to_file(jsons, fileobj)
