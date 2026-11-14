"""Lead and admin passwords for Ballooning mode (kernel/roles.py), in a folder of their own."""

import datetime
import json
import os
import tempfile
import unittest
from unittest import mock

from solidsmufs.kernel import roles


class Roles(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"APPDATA": self.dir.name, "SOLIDSMUFS_APP": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.dir.cleanup()

    def lead_op(self):
        roles.need_for("balloon_status", {"status": "released"})

    def test_no_password_no_roles(self):
        self.assertFalse(roles.status()["on"])
        self.lead_op()  # (allowed)
        roles.need_for("balloon_issue_act", {"act": "purge"})

    def test_lead_unlocks_for_four_hours(self):
        roles.set_password("lead", "1234")
        st = roles.status()
        self.assertEqual((st["on"], st["lead"], st["admin"], st["level"]), (True, True, False, None))
        with self.assertRaises(ValueError):
            self.lead_op()
        with self.assertRaises(ValueError):
            roles.need_for("balloon_issue_act", {"act": "resolve", "route": "machinist"})
        roles.need_for("balloon_issue_act", {"act": "fixed"})  # (anyone's)
        roles.need_for("balloon_edit", {})
        with self.assertRaises(ValueError):
            roles.unlock("nope")
        self.assertEqual(roles.unlock("1234"), "lead")
        self.lead_op()
        until = datetime.datetime.fromisoformat(roles.status()["until"])
        self.assertAlmostEqual((until - datetime.datetime.now().astimezone()).total_seconds(), 4 * 3600, delta=60)
        # four hours on: locked again
        path = os.path.join(self.dir.name, "SolidSmufs", "unlock.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"level": "lead", "until": (datetime.datetime.now().astimezone() - datetime.timedelta(minutes=1)).isoformat()}, f)
        self.assertIsNone(roles.level())
        with self.assertRaises(ValueError):
            self.lead_op()
        roles.unlock("1234")
        roles.lock()
        self.assertIsNone(roles.level())
        # the password isn't kept as typed
        self.assertNotIn("1234", open(os.path.join(self.dir.name, "SolidSmufs", "roles.json"), encoding="utf-8").read())

    def test_changing_passwords(self):
        roles.set_password("lead", "1234")
        with self.assertRaises(ValueError):
            roles.set_password("lead", "5678")  # (not without the old one)
        roles.set_password("lead", "5678", current="1234")
        self.assertEqual(roles.unlock("5678"), "lead")
        roles.set_password("admin", "adminpw")
        roles.lock()
        with self.assertRaises(ValueError):
            roles.set_password("lead", "9999", current="wrong")
        self.assertEqual(roles.unlock("adminpw"), "admin")
        roles.set_password("lead", "9999")  # (an admin may)
        self.lead_op()
        with self.assertRaises(ValueError):
            roles.set_password("lead", "12")  # (too short)
        roles.set_password("lead", "")
        roles.set_password("admin", "")
        self.assertFalse(roles.status()["on"])

    def test_outside_the_app_no_roles(self):
        roles.set_password("lead", "1234")
        with mock.patch.dict(os.environ, {"SOLIDSMUFS_APP": ""}):
            self.lead_op()
            self.assertFalse(roles.status()["on"])


if __name__ == "__main__":
    unittest.main()
