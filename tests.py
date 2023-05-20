from collections import deque
from dataclasses import dataclass
import io
from threading import Thread
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import urllib.parse
import os
from jira2json.__main__ import _main, _parse_args, DEFAULT_FILENAME
from http.server import BaseHTTPRequestHandler, HTTPServer
import weakref

import requests

from jira2json import parse_issues, iterate_jira_issues, save_jsons_to_file
import jira2json


class TestParsers(TestCase):
    def test_worklog_parser(self):
        """Test the worklog parser."""

        result = parse_issues([{
            "Log Work": "comment;started;author;timeSpentSeconds"}])

        self.assertEqual(next(result)["Log Work"], [{
            "comment": "comment", "started": "started", "author": "author",
            "timeSpentSeconds": "timeSpentSeconds"}])

        result = parse_issues([{
            "Log Work": ["comment;started;author;timeSpentSeconds",
                         "comment2;started2;author2;timeSpentSeconds2"]}])

        self.assertEqual(next(result)["Log Work"], [{
            "comment": "comment", "started": "started", "author": "author",
            "timeSpentSeconds": "timeSpentSeconds"},
            {"comment": "comment2", "started": "started2", "author": "author2",
                "timeSpentSeconds": "timeSpentSeconds2"}])

    def test_comment_parser(self):
        """Test the comment parser."""

        # Comments sometimes have trailing semicolons
        result = parse_issues([{
            "Comment": "datetime;author;comment;;;"}])

        self.assertEqual(next(result)["Comment"], [{
            "datetime": "datetime", "author": "author",
            "comment": "comment;;;"}])

        result = parse_issues([{
            "Comment": ["datetime;author;comment",
                        "datetime2;author2;comment2"]}])

        self.assertEqual(next(result)["Comment"], [{
            "datetime": "datetime", "author": "author", "comment": "comment"},
            {"datetime": "datetime2", "author": "author2",
             "comment": "comment2"}])

    def test_override_parsers(self):
        """Test overriding the default parsers."""

        def parser(value):
            return value

        result = parse_issues([{"Log Work": "value"}],
                              parsers={"Log Work": parser})

        self.assertEqual(next(result)["Log Work"], "value")

        with self.assertRaises(StopIteration):
            next(result)


class TestSaveJson(TestCase):
    def test_save_json(self):
        """Test saving JSON to a file."""

        data = [{"key": "value"}]

        fileobj = io.StringIO()
        save_jsons_to_file(data, fileobj)
        fileobj.seek(0)

        self.assertEqual(fileobj.read(), '{"key": "value"}\n')


class FakeHTTPServer:  # pragma: no cover
    @dataclass
    class Request:
        method: str
        path: str
        headers: dict[str, str]
        params: dict[str, list[str]]

    def __init__(self) -> None:
        self.responses: deque[tuple[int, str]] = deque()
        self.requests: deque[self.Request] = deque()  # type: ignore
        get_func = weakref.WeakMethod(self._do_GET)

        class Handler(BaseHTTPRequestHandler):
            # Override GET method
            def do_GET(self):
                func = get_func()
                if func is None:
                    raise RuntimeError("Fake server has been shut down")
                return func(self)

            # Disable logging
            def log_message(self, format, *args):
                pass

        self._server = HTTPServer(("localhost", 0), Handler)
        self.url = f"http://localhost:{self._server.server_port}"
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "FakeHTTPServer":
        self.start()
        return self

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._thread.join(5)
        if self._thread.is_alive():
            raise RuntimeError("Fake server did not shut down")

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.stop()

    def _do_GET(self, handler):
        url = urllib.parse.urlparse(handler.path)
        query = urllib.parse.parse_qs(url.query)
        headers = dict(handler.headers)
        self.requests.append(
            self.Request(handler.command, url.path, headers, query))
        code, data = self.responses.popleft()
        handler.send_response(code)
        handler.send_header("Content-Type", "text/csv")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data.encode("utf-8"))


class TestIterateJiraIssues(TestCase):
    fake_server: FakeHTTPServer

    @classmethod
    def setUpClass(cls) -> None:
        cls.fake_server = FakeHTTPServer()
        cls.fake_server.start()
        cls.addClassCleanup(cls.fake_server.stop)

    def setUp(self) -> None:
        self.fake_server.requests.clear()
        self.fake_server.responses.clear()
        return super().setUp()

    def test_iterate_jira_issues(self):
        """Test iterating over JIRA issues."""
        self.fake_server.responses.append(
            (200, 'Key,Summary\n"hello","world"'))
        iterator = iterate_jira_issues(self.fake_server.url, "hello",
                                       token="mytoken")
        issue = next(iterator)
        self.assertEqual(issue["Key"], "hello")
        self.assertEqual(issue["Summary"], "world")
        request = self.fake_server.requests.popleft()
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.path, jira2json.CSV_API_PATH)
        self.assertEqual(request.headers["Authorization"], "Bearer mytoken")

        self.assertEqual(request.params["jqlQuery"], ["hello"])
        self.assertEqual(request.params["tempMax"],
                         [str(jira2json.BATCH_SIZE)])
        self.assertEqual(request.params["pager/start"], ["0"])

    def test_changing_headers(self):
        """Headers change between the CSVs"""
        self.fake_server.responses.append(
            (200, 'Key,Summary\n' + '"hello","world"\n'*jira2json.BATCH_SIZE))
        self.fake_server.responses.append((200, 'Header1,Header2\n' +
                                           '"more","data"\n'*10))

        iterator = iterate_jira_issues(self.fake_server.url, "hello",
                                       token="mytoken")

        [next(iterator) for _ in range(jira2json.BATCH_SIZE)]

        with self.assertLogs("jira2json", level="WARNING") as logs:
            next(iterator)

        self.assertEqual(len(logs.records), 1)

        # One issue was inside the log message
        self.assertEqual(sum(1 for _ in iterator), 9)

    def test_longer_csv(self):
        """CSV is longer than the batch size"""
        self.fake_server.responses.append(
            (200, 'Key,Summary\n' +
             '"hello","world"\n'*(jira2json.BATCH_SIZE+1)))

        iterator = iterate_jira_issues(self.fake_server.url, "hello",
                                       token="mytoken")

        with self.assertRaises(AssertionError):
            sum(1 for _ in iterator)

    def test_manual_session(self):
        """A session is given instead of a token"""
        self.fake_server.responses.append((200, ""))  # Empty CSV

        session = requests.Session()
        session.headers["Authorization"] = "mystuff"
        iterator = iterate_jira_issues(self.fake_server.url, session=session)

        with self.assertRaises(StopIteration):
            next(iterator)

        self.assertEqual(
            self.fake_server.requests[0].headers["Authorization"], "mystuff")

    def test_no_token_or_session(self):
        """Neither a token nor a session is given"""
        with self.assertRaises(ValueError):
            next(iterate_jira_issues(self.fake_server.url, "hello"))

    def test_both_token_and_session(self):
        """Both a token and a session are given"""
        with self.assertRaises(ValueError):
            next(iterate_jira_issues(self.fake_server.url, "hello",
                                     token="mytoken",
                                     session=requests.Session()))

    def test_bad_response(self):
        """Response is not 200"""
        self.fake_server.responses.append((500, ""))
        with self.assertRaises(requests.HTTPError):
            next(iterate_jira_issues(self.fake_server.url, "hello",
                                     token="mytoken"))

    def test_repeating_header(self):
        """Header is repeated in CSV"""
        self.fake_server.responses.append((200, 'Key,Summary,Summary\n' +
                                           '"hello","world","1"\n' +
                                           '"hello","world","2"\n'))
        iterator = iterate_jira_issues(self.fake_server.url, "hello",
                                       token="mytoken")
        data = next(iterator)
        self.assertEqual(data["Summary"], ["world", "1"])
        data = next(iterator)
        self.assertEqual(data["Summary"], ["world", "2"])


class MainTestCase(TestCase):
    def test_main(self):
        """Test main function"""

        with (patch("jira2json.__main__._parse_args") as parse_args,
              patch("jira2json.__main__.iterate_jira_issues"
                    ) as iterate_jira_issues,
              patch("jira2json.__main__.parse_issues") as parse_issues,
              patch("jira2json.__main__.save_jsons_to_file"
                    ) as save_jsons_to_file):
            output = io.StringIO()
            parse_args.return_value = SimpleNamespace(jql="hello",
                                                      base_url="world",
                                                      token="mytoken",
                                                      output=output)
            iterate_jira_issues.return_value = iter([{"hello": "world"}])
            parse_issues.return_value = iter([{"hello2": "world2"}])

            _main()

            iterate_jira_issues.assert_called_once_with("world", "hello",
                                                        token="mytoken")
            parse_issues.assert_called_once_with(
                iterate_jira_issues.return_value)
            save_jsons_to_file.assert_called_once_with(
                parse_issues.return_value, output)

    def test_args(self):
        """Test argument parsing"""
        with (patch.dict(os.environ, {"JIRA_TOKEN": "tokey_the_token"})):
            args = _parse_args(
                *["--base_url", "https://jira.example.com",
                  "--jql", "project = HELLO",
                  "--token", "mytoken"])
            self.assertEqual(args.base_url, "https://jira.example.com")
            self.assertEqual(args.jql, "project = HELLO")
            self.assertEqual(args.token, "mytoken")
            self.assertEqual(args.output.name,
                             DEFAULT_FILENAME)
            args.output.close()

            args = _parse_args(
                *["--base_url", "https://jira.example.com",
                    "--jql", "project = HELLO"])

            self.assertEqual(args.token, "tokey_the_token")
            args.output.close()


if __name__ == "__main__":  # pragma: no cover
    from unittest import main
    main()
