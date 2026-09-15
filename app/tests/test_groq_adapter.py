"""HRD-04 / A06: the operator-configured `httpx.Client` timeout must actually reach the request,
not be silently overridden by a request-level `timeout=` kwarg."""

import httpx
from django.test import SimpleTestCase
from summaries import groq_adapter
from summaries.groq_adapter import GroqApiError


class RequestTimeoutTests(SimpleTestCase):
    def test_the_clients_own_timeout_reaches_the_request_unmodified(self) -> None:
        seen_timeouts: list[dict[str, float | None]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_timeouts.append(request.extensions["timeout"])
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-1",
                    "model": "openai/gpt-oss-20b",
                    "choices": [
                        {
                            "message": {
                                "content": '{"case_id":"c1","audience":"critic","status":"ok",'
                                '"likes":[],"dislikes":[],"insufficient_data_reason":null}'
                            },
                            "finish_reason": "stop",
                        }
                    ],
                },
            )

        distinctive_timeout = httpx.Timeout(37.5)
        client = httpx.Client(transport=httpx.MockTransport(handler), timeout=distinctive_timeout)
        try:
            groq_adapter.generate_summary(
                client,
                api_key="test-key",
                base_url=groq_adapter.DEFAULT_BASE_URL,
                correlation_id="c1",
                audience="critic",
                reviews=[{"id": "r1", "text": "Great."}],
            )
        finally:
            client.close()

        self.assertEqual(len(seen_timeouts), 1)
        effective = seen_timeouts[0]
        self.assertEqual(
            (effective["connect"], effective["read"], effective["write"], effective["pool"]),
            (37.5, 37.5, 37.5, 37.5),
        )


class ApiKeyRedactionTests(SimpleTestCase):
    """HRD-05: `GroqApiError`'s message is stored verbatim into `SummaryAttempt`/`candidate.
    last_error` and can reach bounded logs -- the operator's real credential must never survive
    into either, even in the worst case where the provider's own error body echoes it back."""

    def test_a_provider_error_body_that_echoes_the_api_key_is_redacted(self) -> None:
        secret = "gsk_super_secret_credential_value"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                json={
                    "error": {
                        "type": "invalid_request_error",
                        "code": "invalid_api_key",
                        "message": f"Incorrect API key provided: {secret}",
                    }
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        try:
            with self.assertRaises(GroqApiError) as caught:
                groq_adapter.generate_summary(
                    client,
                    api_key=secret,
                    base_url=groq_adapter.DEFAULT_BASE_URL,
                    correlation_id="c1",
                    audience="critic",
                    reviews=[{"id": "r1", "text": "Great."}],
                )
        finally:
            client.close()

        message = str(caught.exception)
        self.assertNotIn(secret, message)
        self.assertIn("[REDACTED]", message)
        self.assertIn("invalid_api_key", message)
