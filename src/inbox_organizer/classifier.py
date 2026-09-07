from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass

from .models import Category, Classification, MailMessage


SYSTEM_PROMPT = """You classify one email using its complete supplied content. Return JSON only.
Categories:
- job_rejection: a definite unsuccessful application/candidacy response.
- promotion_ad: commercial advertising, sales promotion, lead generation, or product marketing.
- newsletter: recurring informational/bulk publication that is not a transactional receipt.
- recruiter_response_or_action: recruiter/employer conversation needing a reply, application step,
  assessment, reference request, scheduling, or ambiguous status.
- job_offer_or_interview: interview invitation, offer, onboarding, or positive hiring decision.
- receipt_or_financial: receipt, invoice, payment, banking, tax, insurance, order, or subscription record.
- security_or_account: login, password, authentication, legal, privacy, account, or service alert.
- personal: person-to-person message that is not bulk mail.
- other: none of the above or insufficient evidence.

Judge the meaning and communicative intent of the whole message, not isolated keywords. Quoted
history, signatures, ads embedded in receipts, and phrases such as 'not rejected' must not reverse
the current message's actual intent. Set protected=true for offers, interviews, recruiter actions,
financial/receipt, security/account, legal, personal, ambiguous, or low-confidence messages.
Evidence must be short paraphrases, never long verbatim excerpts.

Return exactly: {"category": string, "confidence": number 0..1, "rationale": string,
"protected": boolean, "evidence": [string]}"""


def _extract_json(value: str) -> dict:
    match = re.search(r"\{.*\}", value, flags=re.DOTALL)
    if not match:
        raise ValueError("Classifier did not return a JSON object")
    return json.loads(match.group(0))


def parse_classification(value: str, model: str = "") -> Classification:
    payload = _extract_json(value)
    category = Category(payload["category"])
    classification = Classification(
        category=category,
        confidence=float(payload["confidence"]),
        rationale=str(payload.get("rationale", "")),
        protected=bool(payload.get("protected", False)),
        evidence=list(payload.get("evidence", [])),
        model=model,
    )
    if classification.confidence < 0.90:
        classification.protected = True
    if category not in {Category.JOB_REJECTION, Category.PROMOTION_AD, Category.NEWSLETTER}:
        classification.protected = True
    return classification


@dataclass(slots=True)
class SemanticClassifier:
    provider: str = "ollama"
    url: str = "http://localhost:11434/api/chat"
    model: str = "llama3.2:3b"
    api_key: str = ""
    timeout: int = 120

    def classify(self, message: MailMessage) -> Classification:
        content = message.classifier_text()
        if self.provider == "ollama":
            body = {
                "model": self.model,
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                "options": {"temperature": 0},
            }
            payload = self._post(body)
            text = payload["message"]["content"]
        elif self.provider == "openai_compatible":
            if not self.api_key:
                raise ValueError("An API key is required for the remote classifier")
            body = {
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                "response_format": {"type": "json_object"},
            }
            payload = self._post(body, {"Authorization": f"Bearer {self.api_key}"})
            text = payload["choices"][0]["message"]["content"]
        else:
            raise ValueError("provider must be 'ollama' or 'openai_compatible'")
        return parse_classification(text, self.model)

    def _post(self, body: dict, extra_headers: dict[str, str] | None = None) -> dict:
        headers = {"Content-Type": "application/json", **(extra_headers or {})}
        request = urllib.request.Request(self.url, json.dumps(body).encode("utf-8"), headers)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.load(response)


def conservative_fallback(message: MailMessage) -> Classification:
    """Non-semantic fallback never recommends trash; it exists only for offline preview."""
    return Classification(
        Category.OTHER, 0.0,
        "Semantic classifier unavailable; the message was not categorized automatically.",
        True, [], "safe-fallback",
    )

