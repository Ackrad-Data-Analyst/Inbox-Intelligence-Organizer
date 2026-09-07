from __future__ import annotations

import json
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

from inbox_organizer.audit import append_audit
from inbox_organizer.classifier import SemanticClassifier, conservative_fallback, parse_classification
from inbox_organizer.mime import gmail_body, message_text, parse_rfc822
from inbox_organizer.models import Action, Category, Classification, MailMessage
from inbox_organizer.policy import plan_operation, recommended_action, validate_confirmation
from inbox_organizer.providers.microsoft import MicrosoftProvider


def message(body: str = "Complete message body") -> MailMessage:
    return MailMessage("id-123", "Application update", "Employer <hr@example.test>",
                       ["person@example.test"], "2026-01-01", body, "INBOX", size_bytes=2048)


class FakeClassifier(SemanticClassifier):
    captured: dict | None = None

    def _post(self, body: dict, extra_headers=None) -> dict:
        self.captured = body
        return {"message": {"content": json.dumps({
            "category": "job_rejection", "confidence": 0.98,
            "rationale": "The current message communicates a final unsuccessful decision.",
            "protected": False, "evidence": ["Final negative hiring outcome"],
        })}}


class FakeMicrosoft(MicrosoftProvider):
    def __init__(self):
        super().__init__("client")
        self.access_token = "synthetic"
        self.calls = []

    def _request(self, method: str, url: str, body=None):
        self.calls.append((method, url, body))
        return {}


class CoreTests(unittest.TestCase):
    def test_rfc822_prefers_plain_body_and_skips_attachment(self):
        email = EmailMessage()
        email["Subject"] = "Synthetic"
        email.set_content("Full plain message")
        email.add_alternative("<b>HTML version</b>", subtype="html")
        email.add_attachment(b"secret attachment", maintype="application", subtype="octet-stream", filename="x.bin")
        parsed = parse_rfc822(email.as_bytes())
        self.assertEqual(message_text(parsed), "Full plain message")

    def test_gmail_nested_payload_reads_all_text_parts(self):
        import base64
        encoded = base64.urlsafe_b64encode(b"Semantic body content").decode().rstrip("=")
        self.assertIn("Semantic body", gmail_body({"parts": [{"mimeType": "text/plain", "body": {"data": encoded}}]}))

    def test_classifier_receives_full_message_context(self):
        body = "Opening context\n" + ("detail " * 200) + "\nFinal decision context"
        classifier = FakeClassifier()
        result = classifier.classify(message(body))
        prompt = classifier.captured["messages"][1]["content"]
        self.assertIn("Opening context", prompt)
        self.assertIn("Final decision context", prompt)
        self.assertEqual(result.category, Category.JOB_REJECTION)

    def test_low_confidence_result_is_protected(self):
        result = parse_classification(json.dumps({
            "category": "promotion_ad", "confidence": 0.7, "rationale": "uncertain",
            "protected": False, "evidence": [],
        }))
        self.assertTrue(result.protected)
        self.assertEqual(recommended_action(result), Action.KEEP)

    def test_positive_or_actionable_hiring_mail_is_always_protected(self):
        result = parse_classification(json.dumps({
            "category": "job_offer_or_interview", "confidence": 1,
            "rationale": "Interview invitation", "protected": False, "evidence": [],
        }))
        self.assertTrue(result.protected)

    def test_high_confidence_rejection_can_be_recommended_for_trash(self):
        result = Classification(Category.JOB_REJECTION, 0.98, "final decision", False)
        self.assertEqual(recommended_action(result), Action.TRASH)

    def test_protected_trash_needs_per_message_override(self):
        result = Classification(Category.OTHER, 0.4, "ambiguous", True)
        with self.assertRaises(ValueError):
            plan_operation(message(), result, Action.TRASH)

    def test_bulk_trash_needs_exact_confirmation(self):
        result = Classification(Category.JOB_REJECTION, 0.98, "final", False)
        operation = plan_operation(message(), result, Action.TRASH)
        with self.assertRaises(ValueError):
            validate_confirmation([operation], "yes")
        validate_confirmation([operation], "MOVE TO TRASH")

    def test_fallback_never_recommends_mailbox_change(self):
        result = conservative_fallback(message())
        self.assertTrue(result.protected)
        self.assertEqual(recommended_action(result), Action.KEEP)

    def test_audit_excludes_subject_and_body(self):
        result = Classification(Category.JOB_REJECTION, 0.98, "final", False)
        operation = plan_operation(message("private body"), result, Action.TRASH)
        # Keep the test artifact inside the project so restricted/sandboxed
        # environments can still validate the audit writer.
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            path = Path(folder) / "audit.jsonl"
            append_audit(path, "synthetic", operation, "applied")
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("Application update", content)
            self.assertNotIn("private body", content)
            self.assertNotIn("id-123", content)

    def test_microsoft_trash_is_recoverable_move_not_delete(self):
        provider = FakeMicrosoft()
        result = Classification(Category.JOB_REJECTION, 0.98, "final", False)
        provider.apply(plan_operation(message(), result, Action.TRASH))
        method, url, body = provider.calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/move"))
        self.assertEqual(body["destinationId"], "deleteditems")

    def test_provider_sources_do_not_implement_permanent_delete(self):
        providers = Path(__file__).parents[1] / "src" / "inbox_organizer" / "providers"
        gmail = (providers / "gmail.py").read_text(encoding="utf-8")
        microsoft = (providers / "microsoft.py").read_text(encoding="utf-8")
        imap = (providers / "imap.py").read_text(encoding="utf-8")
        self.assertIn(".trash(", gmail)
        self.assertNotIn(".delete(", gmail)
        self.assertNotIn('\"DELETE\"', microsoft)
        self.assertNotIn(".expunge(", imap)


if __name__ == "__main__":
    unittest.main()
