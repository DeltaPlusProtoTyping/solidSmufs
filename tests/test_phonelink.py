"""Photos from a phone over the shop's network (phonelink.py): only a live code's page and upload are served."""

import http.client
import time
import unittest
from unittest import mock

from solidsmufs import phonelink


class PhoneLink(unittest.TestCase):
    def setUp(self):
        self.addr = mock.patch.object(phonelink, "lan_address", return_value="192.168.50.7")
        self.addr.start()
        self.link = phonelink.PhoneLink(bind="127.0.0.1")  # (no firewall question for a test)

    def tearDown(self):
        self.link.close()
        self.addr.stop()

    def ask(self, method, path, body=None, headers=None):
        port = self.link.httpd.server_address[1]
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            c.request(method, path, body=body, headers=headers or {})
            r = c.getresponse()
            return r.status, r.read()
        finally:
            c.close()

    def test_a_code_its_page_and_its_inbox(self):
        got = self.link.start("Balloon 4: Ø.375 ±.005")
        self.assertTrue(got["url"].startswith("http://192.168.50.7:"))
        self.assertTrue(got["url"].endswith(f"/p/{got['code']}"))
        self.assertGreaterEqual(len(got["code"]), 20)
        self.assertTrue(got["qr"].startswith("<svg"))  # (the code to scan)
        status, page = self.ask("GET", f"/p/{got['code']}")
        self.assertEqual(status, 200)
        self.assertIn("Balloon 4: Ø.375 ±.005".encode(), page)
        jpg = b"\xff\xd8\xff\xe0fake jpeg"
        status, _ = self.ask("POST", f"/p/{got['code']}", jpg, {"Content-Type": "image/jpeg", "X-Name": "IMG_0001.jpg"})
        self.assertEqual(status, 200)
        taken = self.link.take(got["code"])
        self.assertEqual((taken["live"], [(p["name"], p["type"], p["data"]) for p in taken["photos"]]), (True, [("IMG_0001.jpg", "image/jpeg", jpg)]))
        self.assertEqual(self.link.take(got["code"])["photos"], [])  # (taken once)

    def test_nothing_else_is_served(self):
        got = self.link.start("x")
        for path in ("/", "/p/", "/p/wrong-code", "/api/hello", f"/p/{got['code']}/../../api/hello", "/index.html"):
            self.assertEqual(self.ask("GET", path)[0], 404, path)
        self.assertEqual(self.ask("POST", "/p/wrong-code", b"x", {"Content-Type": "image/jpeg"})[0], 404)
        self.assertEqual(self.ask("POST", f"/p/{got['code']}", b"<html>", {"Content-Type": "text/html"})[0], 415)

    def test_run_out_and_closed(self):
        got = self.link.start("x")
        self.link.codes[got["code"]]["until"] = time.time() - 1  # (its fifteen minutes are up)
        self.assertEqual(self.ask("GET", f"/p/{got['code']}")[0], 404)
        self.assertEqual(self.ask("POST", f"/p/{got['code']}", b"\xff\xd8", {"Content-Type": "image/jpeg"})[0], 404)
        self.assertFalse(self.link.take(got["code"])["live"])
        # the last code stopped: the network server stops too
        self.link.stop(got["code"])
        self.assertIsNone(self.link.httpd)

    def test_not_on_a_network(self):
        with mock.patch.object(phonelink, "lan_address", return_value=None):
            with self.assertRaises(ValueError):
                self.link.start("x")
        self.assertIsNone(self.link.httpd)


if __name__ == "__main__":
    unittest.main()
