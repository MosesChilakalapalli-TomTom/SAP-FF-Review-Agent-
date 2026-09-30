import base64
import json
import unittest
from unittest.mock import patch

import function_app
from sap_ai_agent.sap_ai_agents.sap_agents import firefighter_review_agent as firefighter


class FakeRequest:
    def __init__(self, headers=None, body=None):
        self.headers = headers or {}
        self._body = body or {}

    def get_json(self):
        return self._body


def principal(claims):
    encoded = base64.b64encode(
        json.dumps({"claims": claims}).encode("utf-8")
    ).decode("ascii")
    return {"X-MS-CLIENT-PRINCIPAL": encoded}


class DynamicControllerResolutionTests(unittest.TestCase):
    def setUp(self):
        self.identity = {
            "authenticated": True,
            "oid": "object-a",
            "preferred_username": "User@Example.com",
        }

    def sap_result(self, rows):
        return {"status": "success", "data": {"d": {"results": rows}}}

    def test_resolves_case_insensitive_email(self):
        with patch.object(
            firefighter,
            "sap_get",
            return_value=self.sap_result([
                {"Email": "user@example.com", "Controller": "kwasny"}
            ])
        ) as sap_get:
            self.assertEqual(
                firefighter.resolve_sap_controller(self.identity),
                "KWASNY"
            )
            self.assertIn("%27user%40example.com%27", sap_get.call_args.args[0])

    def test_escapes_apostrophe_in_identity(self):
        identity = dict(self.identity, preferred_username="o'brien@example.com")
        with patch.object(
            firefighter,
            "sap_get",
            return_value=self.sap_result([
                {"Email": "O'BRIEN@EXAMPLE.COM", "Controller": "CTRL1"}
            ])
        ) as sap_get:
            self.assertEqual(
                firefighter.resolve_sap_controller(identity),
                "CTRL1"
            )
            self.assertIn("o%27%27brien%40example.com", sap_get.call_args.args[0])

    def test_no_match_is_forbidden(self):
        with patch.object(
            firefighter, "sap_get", return_value=self.sap_result([])
        ):
            with self.assertRaises(firefighter.SapControllerResolutionError) as error:
                firefighter.resolve_sap_controller(self.identity)
            self.assertEqual(error.exception.status_code, 403)

    def test_conflicting_matches_fail_closed(self):
        with patch.object(
            firefighter,
            "sap_get",
            return_value=self.sap_result([
                {"Email": "user@example.com", "Controller": "CTRL1"},
                {"Email": "USER@EXAMPLE.COM", "Controller": "CTRL2"},
            ])
        ):
            with self.assertRaises(firefighter.SapControllerResolutionError) as error:
                firefighter.resolve_sap_controller(self.identity)
            self.assertEqual(error.exception.status_code, 403)

    def test_sap_failure_does_not_fallback(self):
        with patch.object(
            firefighter,
            "sap_get",
            return_value={"status": "error", "message": "unavailable"}
        ):
            with self.assertRaises(firefighter.SapControllerResolutionError) as error:
                firefighter.resolve_sap_controller(self.identity)
            self.assertEqual(error.exception.status_code, 502)

    def test_easy_auth_claim_order_and_normalization(self):
        request = FakeRequest(principal([
            {"typ": "email", "val": "email@example.com"},
            {"typ": "upn", "val": "UPN@example.com"},
            {"typ": "oid", "val": "oid-1"},
        ]))
        identity = function_app.get_authenticated_user(request)
        self.assertEqual(identity["preferred_username"], "upn@example.com")
        self.assertEqual(identity["oid"], "oid-1")

    def test_missing_or_malformed_easy_auth_is_unauthorized(self):
        self.assertFalse(
            function_app.get_authenticated_user(FakeRequest())["authenticated"]
        )
        self.assertFalse(
            function_app.get_authenticated_user(
                FakeRequest({"X-MS-CLIENT-PRINCIPAL": "not-base64"})
            )["authenticated"]
        )

    def test_body_identity_fields_are_not_used(self):
        request = FakeRequest(
            principal([{"typ": "preferred_username", "val": "user@example.com"}]),
            {"email": "attacker@example.com", "controller": "KWASNY"},
        )
        identity = function_app.get_authenticated_user(request)
        self.assertEqual(identity["preferred_username"], "user@example.com")
        self.assertNotIn("controller", identity)


if __name__ == "__main__":
    unittest.main()
