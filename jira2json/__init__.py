"""A module for converting JIRA issues to JSON lines format."""

__author__ = "Bar Harel"
__version__ = "0.1.1"
__license__ = "MIT License"
__all__ = ["iterate_jira_issues", "save_jsons_to_file", "parse_issues",
           "default_parsers"]

import csv as _csv
import json as _json
import logging as _logging
import typing as _typing
from collections import Counter as _Counter
from collections.abc import Iterable as _Iterable
from collections.abc import Iterator as _Iterator
from itertools import islice as _islice
from typing import Any as _Any
from typing import Callable as _Callable
from urllib.parse import urljoin as _urljoin

import requests as _requests

logger = _logging.getLogger(__name__)

# Must be <= 1000
BATCH_SIZE = 800

# JIRA API URL for CSV
CSV_API_PATH = (
    '/sr/jira.issueviews:searchrequest-csv-all-fields/temp/SearchRequest.csv')


def _log_work_parser(log_work: str | list[str] | None
                     ) -> list[dict[str, _Any]] | None:
    """Parse a log work string to a dictionary.

    Example:
        >>> _log_work_parser("comment;started;author;timeSpentSeconds")
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


def _comment_parser(comment: str | list[str] | None
                    ) -> list[dict[str, _Any]] | None:
    """Parse a log work string to a dictionary.

    Example:
        >>> _log_work_parser("comment;started;author;timeSpentSeconds")
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


default_parsers = {
    "Log Work": _log_work_parser,
    "Comment": _comment_parser,
}
"""A dictionary of default parsers for JIRA fields."""


def iterate_jira_issues(base_url: str, jql: str = "", *,
                        token: str | None = None,
                        session: _requests.Session | None = None
                        ) -> _Iterator[dict]:
    """Iterate over JIRA issues from the JIRA API.

    Args:
        base_url: The base URL of the JIRA server.
        jql: The JQL query to use for the search.
        token: The API token to use for authentication. If None, a session
            must be provided.
        session: A requests session to use for the API calls. If None, a
            session will be created, and the token will be used for
            authentication.

    Yields:
        A dictionary representing a single JIRA issue.
    """
    if not (bool(token) ^ bool(session)):
        raise ValueError("Either token or session must be provided.")

    if session is None:
        session = _requests.Session()
        session.headers["Authorization"] = f"Bearer {token}"

    url = _urljoin(base_url, CSV_API_PATH)
    start_at = 0
    headers = None
    single_headers = None
    response = None
    while True:

        with session.get(
                url,
                params={"jqlQuery": jql,
                        "tempMax": str(BATCH_SIZE),
                        "pager/start": str(start_at), },
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

            reader = _csv.reader(response.iter_lines(
                decode_unicode=True, delimiter="\n"))
            header = next(reader, None)
            if not header:
                break
            header_count = _Counter(header)
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

            count = 0

            for count, row in enumerate(
                    map(iter, filter(None, reader)), start=1):  # type: ignore
                output: dict = {}
                for key, value in header_count.items():
                    if value > 1:
                        output[key] = list(
                            filter(None, _islice(row, value)))  # type: ignore
                    else:
                        output[key] = next(row) or None
                yield output

            if count < BATCH_SIZE:
                break

            assert count == BATCH_SIZE, (
                "Server returned more than BATCH_SIZE issues.")

            start_at += count


def save_jsons_to_file(jsons: _Iterable[dict],
                       fileobj: _typing.TextIO) -> None:
    """Save a list of JSONs to a file.

    Args:
        jsons: An iterator of JSONable dictionaries to save.
        fileobj: A file-like object to save the JSONs to.
    """
    for json_ in jsons:
        _json.dump(json_, fileobj)
        fileobj.write("\n")


def parse_issues(
    issues: _Iterable[dict[str, _Any]], *,
    parsers: dict[str, _Callable[[_Any], _Any]] = default_parsers
) -> _Iterator[dict[str, _Any]]:
    """Applying parsers to the issues.

    Jira's data is badly formatted, and badly escaped. Apply some parsers
    to make it more usable.

    Args:
        issues: An iterator of JSONable dictionaries to parse.
        parsers: A dictionary of parsers to apply to the issues. The keys
            are the names of the fields to parse, and the values are the
            functions to apply to the values of the fields.

    Yields:
        The parsed issues.
    """
    for issue in issues:
        for key, parser in parsers.items():
            issue[key] = parser(issue.get(key))
        yield issue
