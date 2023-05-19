from collections import deque
from dataclasses import dataclass
import io
from threading import Thread
from types import SimpleNamespace
from typing import cast
from unittest import TestCase
from unittest.mock import Mock
import urllib.parse
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
            "datetime": "datetime", "author": "author", "comment": "comment;;;"}])
        
        result = parse_issues([{
            "Comment": ["datetime;author;comment",
                        "datetime2;author2;comment2"]}])
        
        self.assertEqual(next(result)["Comment"], [{
            "datetime": "datetime", "author": "author", "comment": "comment"},
            {"datetime": "datetime2", "author": "author2", "comment": "comment2"}])
        
    def test_override_parsers(self):
        """Test overriding the default parsers."""

        def parser(value):
            return value
        
        result = parse_issues([{"Log Work": "value"}],
                              parsers={"Log Work": parser})
        
        self.assertEqual(next(result)["Log Work"], "value")

class TestSaveJson(TestCase):
    def test_save_json(self):
        """Test saving JSON to a file."""
                
        data = [{"key": "value"}]

        fileobj = io.StringIO()
        save_jsons_to_file(data, fileobj)
        fileobj.seek(0)
        
        self.assertEqual(fileobj.read(), '{"key": "value"}\n')

class FakeHTTPServer:
    @dataclass
    class Request:
        method: str
        path: str
        headers: dict[str, str]
        params: dict[str, list[str]]

    def __init__(self) -> None:
        self.responses: deque[tuple[int, str]] = deque()
        self.requests: deque[self.Request] = deque()
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
        self.fake_server.responses.append((200, 'Key,Summary\n"hello","world"'))
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
        self.fake_server.responses.append((200, 'Key,Summary\n' +
                                           '"hello","world"\n'*jira2json.BATCH_SIZE))
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
        

if __name__ == "__main__":
    from unittest import main
    main()