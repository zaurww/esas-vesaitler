"""Single-instance handoff (CLAUDE.md §9 launcher note, added after Zaur

flagged that a second double-click on Başlat.bat silently started a second
writer on the same clients/ folder -- see web/app.py's note above
_APP_MARKER for why that is a lost-write bug, not a port nuisance).

Three things are checked, in order of how far the bug could hide:

* _install_id/_same_installation are pure functions -- easy to get subtly
  wrong (case-sensitivity on Windows paths, a probe answer missing a key)
  without ever showing up in manual testing on one machine;
* _bind_or_handoff actually binds a real loopback socket, because the
  behaviour that matters -- OSError on a taken port, LocalServer's
  allow_reuse_address=False making that error reliable -- only exists at
  the socket layer, not in a mock;
* serve() itself is not exercised here: it calls serve_forever(), which
  does not return, and needs a real browser to matter. _bind_or_handoff is
  the seam that carries all of serve()'s new decision logic.
"""

from __future__ import annotations

import socket
import unittest
from pathlib import Path

from web.app import (
    ENGINE_VERSION,
    ROOT,
    _APP_MARKER,
    _bind_or_handoff,
    _install_id,
    _same_installation,
    instance_marker,
)


def _free_port() -> int:
    """Ask the OS for a port nobody holds, the same way tempfile picks names."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class InstallId(unittest.TestCase):
    def test_stable_for_the_same_path(self):
        self.assertEqual(_install_id(Path("D:/clients-a")),
                          _install_id(Path("D:/clients-a")))

    def test_different_for_different_folders(self):
        # Two accountants, two folders -- must never collide, or a second,
        # unrelated installation would be waved through as "us".
        self.assertNotEqual(_install_id(Path("D:/clients-a")),
                             _install_id(Path("D:/clients-b")))

    def test_case_insensitive_on_windows_paths(self):
        # "D:\..." and "d:\..." name the same folder on Windows and must
        # hash to the same id, or a case difference alone would look like a
        # second installation and defeat the whole handoff.
        self.assertEqual(_install_id(Path("D:/Clients")),
                          _install_id(Path("d:/clients")))


class SameInstallation(unittest.TestCase):
    def test_our_own_marker_matches(self):
        self.assertTrue(_same_installation(instance_marker()))

    def test_a_different_installations_marker_does_not_match(self):
        other = instance_marker()
        other["install"] = "0" * 16
        self.assertFalse(_same_installation(other))

    def test_an_unrelated_local_service_does_not_match(self):
        # Something else entirely answered on that port with valid JSON that
        # is not ours at all -- must read as "not us", not crash.
        self.assertFalse(_same_installation({"hello": "world"}))
        self.assertFalse(_same_installation(None))

    def test_the_app_tag_alone_is_not_enough(self):
        # A future unrelated tool could reuse a similar shape by accident;
        # both the app tag AND the folder id must match.
        self.assertFalse(_same_installation({"app": _APP_MARKER}))


class BindOrHandoff(unittest.TestCase):
    def test_binds_normally_when_the_port_is_free(self):
        port = _free_port()
        httpd, got = _bind_or_handoff(port, tries=3)
        try:
            self.assertIsNotNone(httpd)
            self.assertEqual(got, port)
        finally:
            if httpd is not None:
                httpd.server_close()

    def test_hands_off_when_the_port_is_held_by_ourselves(self):
        port = _free_port()
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.bind(("127.0.0.1", port))
        holder.listen(1)
        try:
            httpd, got = _bind_or_handoff(
                port, tries=3, probe=lambda p, timeout=1.0: instance_marker())
            self.assertIsNone(httpd)
            self.assertEqual(got, port)
        finally:
            holder.close()

    def test_steps_past_a_port_held_by_something_else(self):
        port = _free_port()
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.bind(("127.0.0.1", port))
        holder.listen(1)
        try:
            httpd, got = _bind_or_handoff(
                port, tries=5, probe=lambda p, timeout=1.0: None)
            try:
                self.assertIsNotNone(httpd)
                self.assertNotEqual(got, port)
            finally:
                if httpd is not None:
                    httpd.server_close()
        finally:
            holder.close()

    def test_a_taken_port_that_never_frees_up_raises_not_hangs(self):
        # Every candidate in range must be occupied by someone else for the
        # exhaustion path to trigger -- one taken port alone just steps past
        # it, which is the case above.
        port = _free_port()
        holders = []
        try:
            for p in (port, port + 1):
                h = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                h.bind(("127.0.0.1", p))
                h.listen(1)
                holders.append(h)
            with self.assertRaises(SystemExit):
                _bind_or_handoff(port, tries=2, probe=lambda p, timeout=1.0: None)
        finally:
            for h in holders:
                h.close()


class InstanceMarker(unittest.TestCase):
    def test_carries_the_running_engine_version(self):
        self.assertEqual(instance_marker()["version"], ENGINE_VERSION)

    def test_carries_this_installations_id(self):
        self.assertEqual(instance_marker()["install"], _install_id(ROOT))


if __name__ == "__main__":
    unittest.main()
