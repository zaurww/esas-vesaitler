"""Requests from foreign pages are refused (CLAUDE.md §3, layer 3).

Run against a real loopback server: the gates live in HTTP headers, and the
point is what an actual request with those headers gets back.
"""

from __future__ import annotations

import http.client
import json
import threading
import unittest

from web.app import LocalServer, Handler


class ForeignRequests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = LocalServer(("127.0.0.1", 0), Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, method, path, headers=None, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    # The action itself is unknown on purpose: if a gate let the request
    # through it would answer 400 "naməlum əməliyyat", never touching data.
    ACTION = json.dumps({"client": "x", "action": "no.such", "payload": {}})

    def test_own_page_passes_the_gates(self):
        status, _ = self.req("POST", "/api/action", {
            "Content-Type": "application/json",
            "Origin": f"http://127.0.0.1:{self.port}"}, self.ACTION)
        self.assertEqual(status, 400)          # reached the action table

    def test_localhost_name_is_ours_too(self):
        status, _ = self.req("POST", "/api/action", {
            "Host": f"localhost:{self.port}",
            "Content-Type": "application/json"}, self.ACTION)
        self.assertEqual(status, 400)

    def test_simple_content_type_is_refused(self):
        # What a no-cors fetch from a foreign page can send without preflight.
        status, _ = self.req("POST", "/api/action",
                             {"Content-Type": "text/plain"}, self.ACTION)
        self.assertEqual(status, 403)

    def test_foreign_origin_is_refused(self):
        status, _ = self.req("POST", "/api/action", {
            "Content-Type": "application/json",
            "Origin": "https://evil.example"}, self.ACTION)
        self.assertEqual(status, 403)

    def test_other_port_origin_is_refused(self):
        status, _ = self.req("POST", "/api/action", {
            "Content-Type": "application/json",
            "Origin": f"http://127.0.0.1:{self.port + 1}"}, self.ACTION)
        self.assertEqual(status, 403)

    def test_rebound_host_is_refused_for_reads(self):
        # DNS rebinding: a foreign name resolved to 127.0.0.1.
        status, _ = self.req("GET", "/api/context",
                             {"Host": f"evil.example:{self.port}"})
        self.assertEqual(status, 403)

    def test_update_endpoints_are_gated_too(self):
        status, _ = self.req("POST", "/api/update-apply",
                             {"Content-Type": "text/plain"}, "{}")
        self.assertEqual(status, 403)

    def test_page_itself_still_loads(self):
        status, _ = self.req("GET", "/")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
