import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_bridge.nexus_bridge import validate_request


class TestNexusBridgeAuthorization(unittest.TestCase):
    def validate(self, action, user_id="", authorized_users=""):
        env = {
            "NEXUS_BRIDGE_TOKEN": "test-token",
            "NEXUS_BRIDGE_DISABLED": "false",
            "NEXUS_AUTHORIZED_ALEXA_USERS": authorized_users,
        }
        payload = {
            "task": "solicitacao de teste",
            "action_hint": action,
            "user_id": user_id,
        }
        with patch.dict(os.environ, env, clear=False):
            return validate_request(payload)

    def test_group_a_allowed_without_allowlist(self):
        valid, _, _ = self.validate("STATUS")
        self.assertTrue(valid)

    def test_group_b_denied_when_allowlist_empty(self):
        valid, _, message = self.validate("CRIAR", "user-1")
        self.assertFalse(valid)
        self.assertIn("autorizado", message.lower())

    def test_group_c_denied_when_allowlist_empty(self):
        valid, _, _ = self.validate("EXECUTAR", "user-1")
        self.assertFalse(valid)

    def test_restricted_action_denied_without_user_id(self):
        valid, _, _ = self.validate("CRIAR", "", "user-1,user-2")
        self.assertFalse(valid)

    def test_restricted_action_denied_for_unknown_user(self):
        valid, _, _ = self.validate("CRIAR", "intruso", "user-1,user-2")
        self.assertFalse(valid)

    def test_restricted_action_allowed_for_authorized_user(self):
        valid, user_id, message = self.validate("CRIAR", "user-1", "user-1,user-2")
        self.assertTrue(valid, message)
        self.assertEqual(user_id, "user-1")


if __name__ == "__main__":
    unittest.main()
