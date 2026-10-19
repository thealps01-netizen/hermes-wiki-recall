"""Unit tests for wiki-recall. Run: PYTHONUTF8=1 python -m unittest discover -s tests (from the plugin folder)."""
import importlib.util
import json
import os
import re
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import recall  # noqa: E402

QUERY = "private-query-7f3a"
TOKEN = "tok-secret-91c2"


def _load_plugin():
    """Import the plugin package (__init__.py) with its `from . import recall` bound to `recall`."""
    name = "wiki_recall_under_test"
    sys.modules[name + ".recall"] = recall
    spec = importlib.util.spec_from_file_location(name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _FakeCtx:
    def __init__(self, skip_pattern):
        self.skip_pattern = skip_pattern
        self.hooks = {}

    def get_config(self, key, default=None):
        return self.skip_pattern if key == "skip_pattern" else default

    def register_hook(self, name, callback):
        self.hooks[name] = callback


class _Handler(BaseHTTPRequestHandler):
    reply: dict = {}
    raw = None  # bytes sent instead of the JSON-encoded reply
    delay = 0.0
    status = 200
    seen: list = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        type(self).seen.append((body, self.headers.get("Authorization")))
        time.sleep(type(self).delay)
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(type(self).raw if type(self).raw is not None else json.dumps(type(self).reply).encode())
        except ConnectionError:
            pass  # the client gave up (timeout test)

    def log_message(self, *_):
        pass


class RecallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        _Handler.reply = {"results": [
            {"path": "wiki/a.md", "title": "A", "vectorScore": 1.0},
            {"path": "wiki/b.md", "title": "B", "vectorScore": 0.79},
            {"path": "wiki/c.md", "title": "C", "vectorScore": 0.85},
            {"path": "wiki/d.md", "title": "D", "vectorScore": 0.9},
            {"path": "wiki/e.md", "title": "E", "vectorScore": 0.95},
        ]}
        _Handler.raw, _Handler.delay, _Handler.status, _Handler.seen = None, 0.0, 200, []

    def assertOneSafeWarning(self, cm, reason):
        self.assertEqual(len(cm.records), 1, cm.output)
        message = cm.records[0].getMessage()
        self.assertTrue(message.startswith("wiki-recall: "), message)
        self.assertIn(reason, message)
        self.assertNotIn(QUERY, message)
        self.assertNotIn(TOKEN, message)

    def test_keeps_at_most_three_hits_above_threshold(self):
        hits = recall.search("gateway decision", base_url=self.base, token=None)
        self.assertEqual([h["title"] for h in hits], ["A", "C", "D"])

    def test_body_is_utf8_and_token_sent_as_bearer(self):
        recall.search("şğüı", base_url=self.base, token="t0k")
        body, auth = _Handler.seen[0]
        self.assertIn("şğüı".encode("utf-8"), body)
        self.assertEqual(auth, "Bearer t0k")

    def test_no_token_sends_no_auth_header(self):
        recall.search("x", base_url=self.base, token=None)
        self.assertIsNone(_Handler.seen[0][1])

    def test_timeout_returns_nothing(self):
        _Handler.delay = 0.5
        self.assertEqual(recall.search("x", base_url=self.base, token=None, timeout=0.1), [])

    def test_server_error_returns_nothing(self):
        _Handler.status = 500
        self.assertEqual(recall.search("x", base_url=self.base, token=None), [])

    def test_unreachable_returns_nothing(self):
        self.assertEqual(recall.search("x", base_url="http://127.0.0.1:9", token=None), [])

    def test_empty_or_non_text_message_is_not_searched(self):
        self.assertEqual(recall.search("  ", base_url=self.base, token=None), [])
        self.assertEqual(_Handler.seen, [])

    def test_message_text_from_multimodal_list(self):
        msg = [{"type": "text", "text": "gateway"}, {"type": "image_url", "image_url": {"url": "x"}}]
        self.assertEqual(recall.message_text(msg), "gateway")

    def test_long_message_is_truncated(self):
        recall.search("a" * 5000, base_url=self.base, token=None)
        self.assertLessEqual(len(json.loads(_Handler.seen[0][0])["query"]), recall.MAX_QUERY_CHARS)

    def test_context_lists_titles_and_paths_only(self):
        text = recall.format_context([{"title": "A", "path": "wiki/a.md"}])
        self.assertIn("A (wiki/a.md)", text)
        self.assertEqual(recall.format_context([]), "")

    # Failure logging: one safe WARNING line per swallowed failure.

    def test_unreachable_logs_one_safe_warning(self):
        with self.assertLogs(recall.logger, "WARNING") as cm:
            self.assertEqual(recall.search(QUERY, base_url="http://127.0.0.1:9", token=TOKEN, timeout=10), [])
        self.assertOneSafeWarning(cm, "app unreachable")

    def test_timeout_logs_one_safe_warning(self):
        _Handler.delay = 0.5
        with self.assertLogs(recall.logger, "WARNING") as cm:
            self.assertEqual(recall.search(QUERY, base_url=self.base, token=TOKEN, timeout=0.1), [])
        self.assertOneSafeWarning(cm, "timed out")

    def test_http_error_logs_one_safe_warning(self):
        _Handler.status = 500
        _Handler.raw = (QUERY + TOKEN).encode()
        with self.assertLogs(recall.logger, "WARNING") as cm:
            self.assertEqual(recall.search(QUERY, base_url=self.base, token=TOKEN), [])
        self.assertOneSafeWarning(cm, "HTTP 500")

    def test_invalid_json_logs_one_safe_warning(self):
        _Handler.raw = ("not json " + QUERY).encode()
        with self.assertLogs(recall.logger, "WARNING") as cm:
            self.assertEqual(recall.search(QUERY, base_url=self.base, token=TOKEN), [])
        self.assertOneSafeWarning(cm, "bad reply")

    def test_json_list_reply_logs_one_safe_warning(self):
        _Handler.reply = [QUERY]
        with self.assertLogs(recall.logger, "WARNING") as cm:
            self.assertEqual(recall.search(QUERY, base_url=self.base, token=TOKEN), [])
        self.assertOneSafeWarning(cm, "bad reply")

    def test_results_not_a_list_logs_one_safe_warning(self):
        _Handler.reply = {"results": {"path": QUERY}}
        with self.assertLogs(recall.logger, "WARNING") as cm:
            self.assertEqual(recall.search(QUERY, base_url=self.base, token=TOKEN), [])
        self.assertOneSafeWarning(cm, "bad reply")

    def test_unexpected_error_logs_class_name_only(self):
        with mock.patch.object(recall.urllib.request, "urlopen", side_effect=RuntimeError(QUERY + TOKEN)):
            with self.assertLogs(recall.logger, "WARNING") as cm:
                self.assertEqual(recall.search(QUERY, base_url=self.base, token=TOKEN), [])
        self.assertOneSafeWarning(cm, "unexpected error")
        self.assertIn("RuntimeError", cm.records[0].getMessage())

    def test_token_lookup_failure_logs_one_safe_warning(self):
        def lookup(name):
            raise KeyError(TOKEN)
        with self.assertLogs(recall.logger, "WARNING") as cm:
            self.assertIsNone(recall.read_token(lookup))
        self.assertOneSafeWarning(cm, "token lookup failed")

    def test_invalid_skip_pattern_logs_one_safe_warning(self):
        ctx = _FakeCtx("(")
        with self.assertLogs(recall.logger, "WARNING") as cm:
            _load_plugin().register(ctx)
        self.assertOneSafeWarning(cm, "invalid skip_pattern")
        self.assertIn("pre_llm_call", ctx.hooks)

    def test_success_and_empty_query_log_nothing(self):
        with self.assertNoLogs(recall.logger):
            self.assertEqual(len(recall.search(QUERY, base_url=self.base, token=TOKEN)), 3)
            self.assertEqual(recall.search("  ", base_url=self.base, token=TOKEN), [])
            _Handler.reply = {"results": [{"path": "wiki/b.md", "vectorScore": 0.5}]}
            self.assertEqual(recall.search(QUERY, base_url=self.base, token=TOKEN), [])

    # Token comes only from the Hermes lookup.

    def test_read_token_strips_lookup_value(self):
        seen = []
        self.assertEqual(recall.read_token(lambda name: seen.append(name) or "  tok \n"), "tok")
        self.assertEqual(seen, ["LLM_WIKI_API_TOKEN"])

    def test_read_token_empty_or_missing_is_none(self):
        self.assertIsNone(recall.read_token(lambda name: ""))
        self.assertIsNone(recall.read_token(lambda name: None))

    # Skip pattern: empty by default, configurable.

    def test_default_has_no_skip(self):
        recall.search("How do I open the Atlas app?", base_url=self.base, token=None, skip=None)
        self.assertEqual(len(_Handler.seen), 1)

    def test_skip_pattern_blocks_matching_message_only(self):
        skip = re.compile(r"\bopen\b.*\bapp\b", re.I)
        with self.assertNoLogs(recall.logger):
            self.assertEqual(recall.search("How do I OPEN the Atlas app?", base_url=self.base, token=None, skip=skip), [])
        self.assertEqual(_Handler.seen, [])
        recall.search("What did we decide about the gateway?", base_url=self.base, token=None, skip=skip)
        self.assertEqual(len(_Handler.seen), 1)

    def test_register_wires_skip_pattern_into_hook(self):
        ctx = _FakeCtx(r"\bopen\b.*\bapp\b")
        _load_plugin().register(ctx)
        hook = ctx.hooks["pre_llm_call"]
        with mock.patch.object(recall, "read_token", lambda lookup: None), \
                mock.patch.dict(os.environ, {"LLM_WIKI_API_BASE_URL": self.base}):
            self.assertIsNone(hook(user_message="How do I open the Atlas app?"))
            self.assertEqual(_Handler.seen, [])
            result = hook(user_message="What did we decide about the gateway?")
        self.assertEqual(len(_Handler.seen), 1)
        self.assertIn("A (wiki/a.md)", result["context"])

    def test_register_with_empty_pattern_searches_everything(self):
        ctx = _FakeCtx("")
        _load_plugin().register(ctx)
        with mock.patch.object(recall, "read_token", lambda lookup: None), \
                mock.patch.dict(os.environ, {"LLM_WIKI_API_BASE_URL": self.base}):
            ctx.hooks["pre_llm_call"](user_message="How do I open the Atlas app?")
        self.assertEqual(len(_Handler.seen), 1)


if __name__ == "__main__":
    unittest.main()
