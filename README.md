# Jira to Json

A Python library to convert Jira issues to Json.

[![GitHub branch checks state](https://img.shields.io/github/checks-status/bharel/jira_to_json/master)](https://github.com/bharel/jira_to_json/actions)
[![PyPI](https://img.shields.io/pypi/v/jira2json)](https://pypi.org/project/jira2json/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/jira2json)](https://pypi.org/project/jira2json/)
[![codecov](https://codecov.io/gh/bharel/jira_to_json/branch/master/graph/badge.svg?token=37IZCOYI9U)](https://codecov.io/gh/bharel/jira_to_json)

The library is based on the [Jira REST API](https://docs.atlassian.com/jira/REST/latest/),
and uses the [Requests](http://docs.python-requests.org/en/latest/) library.

It contacts the Jira server, downloads the issues according to the specified
JQL query, and converts them to Json. An API is provided to access the issues
and their fields and for further processing.

Supports Jira Datacenter.

## Installation

Install the library with pip:

`pip install jira2json[dotenv]`

The `dotenv` extra installs the [python-dotenv](https://pypi.org/project/python-dotenv/)
library, which is used to load the Jira server's url and the authentication token
from a `.env` file.

## Usage

The library can be used as a command line tool or as a Python library.

### Command line tool

The command line tool is called `jira2json` and is installed with the library.

Run `jira2json --help` for usage information.

### Python library

The library exports the following functions:

* `iterate_jira_issues`: iterates over the issues returned by a JQL query.
* `prase_issues`: applies parsers on the issue's data.
* `save_jsons_to_file`: saves the issues to a file.

Typical usage:

```python

from jira2json import iterate_jira_issues, prase_issues, save_jsons_to_file

# Iterate over the issues returned by the JQL query
issues = iterate_jira_issues(
    base_url='https://jira.atlassian.com',
    jql='project=JRA',
    token='mytoken',
)

# Parse the jsons and convert them to a more usable format
issues = prase_issues(issues)

# Save the issues to a file
with open('issues.json', 'w') as f:
    save_jsons_to_file(issues, f)
```

## Development

Install the `dev` extra:

`pip install -e .[dev,dotenv]`