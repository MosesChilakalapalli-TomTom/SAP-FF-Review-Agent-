import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sap_ai_agent.sap_ai_agents.sap_agents import firefighter_review_agent


class FirefighterReviewCompletenessTests(unittest.TestCase):
    def build_sessions(self):
        sessions = []

        for index in range(16):
            timestamp = f"20240101{index:02d}0000"
            sessions.append({
                "FirefighterUser": f"USER{index + 1}",
                "FirefighterId": "FF_TEST",
                "SessionId": f"SESSION-{index + 1:02d}",
                "Reason": "",
                "Owner": "OWNER",
                "Controller": "CONTROLLER",
                "Connector": "TEST",
                "LoginTime": timestamp,
                "LogoutTime": f"20240101{index:02d}5959"
            })

        return sessions

    def build_activities(self):
        return [
            {
                "FFUser": f"USER{index + 1}",
                "Connector": "TEST",
                "Action": f"TX{index + 1}",
                "Program": f"PROGRAM{index + 1}",
                "ExecDate": f"20240101{index:02d}3000"
            }
            for index in range(5)
        ]

    def model_response(self, batch):
        reviews = []

        for index, session in enumerate(batch, start=1):
            activities = session.get("Activities", [])
            activity_text = (
                "\n".join(
                    (
                        f"- Transaction Code: {activity['Action']}\n"
                        f"- Program: {activity['Program']}\n"
                        f"- Execution Time: {activity['ExecDate']}"
                    )
                    for activity in activities
                )
                if activities
                else "No recorded activities."
            )
            reviews.append(
                f"### Session {index}\n"
                f"- Session ID: {session['SessionId']}\n"
                f"### Activities\n{activity_text}\n"
                "### Analysis\nAvailable data reviewed.\n"
                "### Recommendation\nREQUEST JUSTIFICATION\n"
                "### Decision\nREQUEST JUSTIFICATION"
            )

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="\n\n".join(reviews)
                    ),
                    finish_reason="stop"
                )
            ]
        )

    def test_all_sixteen_sessions_are_reviewed_exactly_once(self):
        sessions = self.build_sessions()
        activities = self.build_activities()
        firefighter_review_agent.attach_activities_to_sessions(
            sessions,
            activities
        )
        batches = [
            sessions[index:index + 4]
            for index in range(0, 16, 4)
        ]
        responses = [
            self.model_response(batch)
            for batch in batches
        ]

        with patch.object(
            firefighter_review_agent.azure_client.chat.completions,
            "create",
            side_effect=responses
        ) as create:
            review = firefighter_review_agent.analyze_firefighter_data(
                sessions,
                activities
            )

        self.assertEqual(create.call_count, 4)
        self.assertIn("Sessions Reviewed: 16", review)
        self.assertIn("Sessions with Activities: 5", review)
        self.assertIn("Sessions without Activities: 11", review)
        self.assertEqual(review.count("No recorded activities."), 11)

        reviewed_ids = re.findall(
            r"(?im)^\s*-\s*Session ID:\s*(\S+)",
            review
        )
        self.assertEqual(
            reviewed_ids,
            [session["SessionId"] for session in sessions]
        )
        self.assertEqual(
            len(reviewed_ids),
            len(set(reviewed_ids))
        )
        self.assertNotRegex(
            review,
            r"(?m)^\s*#{1,6}\s"
        )
        self.assertNotIn("**", review)
        self.assertNotRegex(
            review,
            r"(?m)^\s*---\s*$"
        )
        self.assertIn("🔥 FIREFIGHTER REVIEW", review)
        self.assertIn("📊 OVERVIEW", review)
        self.assertIn("🔹 SESSION 1", review)
        self.assertIn("🧾 ACTIVITIES", review)
        self.assertIn("🔍 ASSESSMENT", review)
        self.assertIn(
            "🟠 REQUEST JUSTIFICATION",
            review
        )

    def test_truncated_batch_is_rejected(self):
        sessions = self.build_sessions()[:2]
        incomplete = self.model_response(sessions[:1])
        incomplete.choices[0].finish_reason = "length"

        with patch.object(
            firefighter_review_agent.azure_client.chat.completions,
            "create",
            return_value=incomplete
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "finish reason 'length'"
            ):
                firefighter_review_agent.analyze_firefighter_data(
                    sessions,
                    []
                )

    def test_backend_activities_replace_incomplete_model_output(self):
        sessions = self.build_sessions()[:1]
        activities = self.build_activities()[:1]
        firefighter_review_agent.attach_activities_to_sessions(
            sessions,
            activities
        )
        incomplete = self.model_response(sessions)
        incomplete.choices[0].message.content = (
            incomplete.choices[0].message.content
            .replace(
                "- Execution Time: 20240101003000",
                "- Transaction Code: INVENTED"
            )
        )

        with patch.object(
            firefighter_review_agent.azure_client.chat.completions,
            "create",
            return_value=incomplete
        ):
            review = firefighter_review_agent.analyze_firefighter_data(
                sessions,
                activities
            )

        self.assertIn(
            "🔷 T-Code: TX1",
            review
        )
        self.assertIn(
            "🟣 Program: PROGRAM1",
            review
        )
        self.assertIn(
            "🕒 Executed: 20240101003000",
            review
        )
        self.assertNotIn("INVENTED", review)


if __name__ == "__main__":
    unittest.main()
