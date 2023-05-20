import argparse
import logging
import os
from typing import Any
from jira2json import iterate_jira_issues, parse_issues, save_jsons_to_file

DEFAULT_FILENAME = "jira_issues.jsonl"


def _main():
    """Entry point of the program."""

    try:
        import dotenv
        dotenv.load_dotenv()
    except ImportError:  # pragma: no cover
        pass

    logging.basicConfig(level=logging.WARNING)

    args = _parse_args()

    jsons = iterate_jira_issues(
        args.base_url, args.jql, token=args.token)
    jsons = parse_issues(jsons)

    with args.output as fileobj:
        save_jsons_to_file(jsons, fileobj)


def _parse_args(*args: str) -> argparse.Namespace:
    """Parse the command line arguments.

    Args:
        args: The command line arguments to parse. If not provided, the
            arguments are read from sys.argv.

    Returns:
        The parsed command line arguments.
    """
    parser = argparse.ArgumentParser(
        description='Convert JIRA issues to JSON format.')

    parser.add_argument(
        "--jql", type=str,
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
        return ({'default': value} if (value := os.getenv(key)) is not None
                else {"required": True})

    parser.add_argument('-u', '--base_url', type=str,
                        **_default_environ("JIRA_BASE_URL"),
                        help='The base URL of the JIRA server. '
                        'Can also be set using the JIRA_BASE_URL environment '
                        'variable.')

    parser.add_argument("-t", "--token", type=str,
                        **_default_environ("JIRA_TOKEN"),
                        help="The API token to use for authentication. "
                        "Can also be set using the JIRA_TOKEN environment "
                        "variable.")

    parser.add_argument("-o", "--output", type=argparse.FileType("w"),
                        default=DEFAULT_FILENAME,
                        help="The output file to save the JSONs to. "
                        "By default, the JSONs are saved to "
                        "'jira_issues.jsonl.' "
                        "If the file already exists, it will be overwritten.")

    result = parser.parse_args(args or None)
    return result


if __name__ == "__main__":  # pragma: no cover
    """Entry point of the program."""
    _main()
