"""HRD-04 / A06: the operator-configured `httpx.Client` timeout must actually reach the request,
not be silently overridden by a request-level `timeout=` kwarg."""

import httpx
from django.test import SimpleTestCase
from summaries import groq_adapter


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
