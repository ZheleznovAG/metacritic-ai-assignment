"""HRD-01 / A07: bounded response size/time and bounded transient-failure retry at the HTTP
adapter level — the gap the adapter's own prior docstring called out as not yet implemented.

Exercises `MetacriticGateway._get` directly: these are adapter-level HTTP behaviors, independent
of parsing, which `test_metacritic_parser.py`/`test_metacritic_lists_parser.py` already cover
extensively.

Every response body below is served through a generator, never a plain `bytes` literal: passing
`content=b"..."` to `httpx.Response` makes httpx eagerly `.read()` it at construction time, which
would silently mask a real bug this suite exists to catch (`response.content`/`.text` raising
`ResponseNotRead` after a hand-rolled `iter_bytes()` loop, since only `.read()` populates httpx's
internal cache — a real network transport behaves the same lazy way `MockTransport` does here).
"""

import hashlib
import time
from collections.abc import Callable, Iterator
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase
from metacritic.gateway import (
    MAX_ATTEMPTS,
    MAX_RESPONSE_BYTES,
    RETRY_BACKOFF_SECONDS,
    MetacriticGateway,
)

NEW_RELEASES_URL = "https://www.metacritic.com/game/"


def _streamed(data: bytes) -> Iterator[bytes]:
    yield data


def _make_gateway(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[MetacriticGateway, list[float]]:
    sleeps: list[float] = []
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return MetacriticGateway(client=client, sleep=sleeps.append), sleeps


class DefaultClientTests(SimpleTestCase):
    def test_the_default_client_disables_response_compression(self) -> None:
        # Response compression is decoded transparently by httpx before MAX_RESPONSE_BYTES ever
        # sees the bytes, so a compression bomb could spike memory inside a single decode() call
        # regardless of that bound. Asking the source not to compress at all removes this gap for
        # any server that honours the request, which a normal web server does.
        gateway = MetacriticGateway()
        try:
            self.assertEqual(gateway._client.headers["accept-encoding"], "identity")
        finally:
            gateway.close()


class OversizedResponseTests(SimpleTestCase):
    def test_a_response_exceeding_the_size_bound_is_rejected_without_retry(self) -> None:
        calls = 0

        def oversized_chunks() -> Iterator[bytes]:
            chunk = b"x" * 65536
            for _ in range(MAX_RESPONSE_BYTES // len(chunk) + 2):
                yield chunk

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, content=oversized_chunks())

        gateway, sleeps = _make_gateway(handler)
        body, evidence = gateway._get(NEW_RELEASES_URL, kind="new_releases")

        self.assertIsNone(body)
        self.assertEqual(evidence.outcome, "failed")
        self.assertEqual(evidence.error_code, "response_too_large")
        self.assertIsNone(evidence.response_sha256)
        self.assertEqual(calls, 1)  # not retried — the same oversized page would recur
        self.assertEqual(sleeps, [])


class SlowResponseTests(SimpleTestCase):
    def test_a_response_exceeding_the_time_bound_is_rejected_without_retry(self) -> None:
        calls = 0

        def slow_chunks() -> Iterator[bytes]:
            for _ in range(5):
                time.sleep(0.02)
                yield b"partial-chunk"

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, content=slow_chunks())

        gateway, sleeps = _make_gateway(handler)
        with patch("metacritic.gateway.RESPONSE_DEADLINE_SECONDS", 0.03):
            body, evidence = gateway._get(NEW_RELEASES_URL, kind="new_releases")

        self.assertIsNone(body)
        self.assertEqual(evidence.outcome, "failed")
        self.assertEqual(evidence.error_code, "response_deadline_exceeded")
        self.assertIsNone(evidence.response_sha256)
        self.assertEqual(calls, 1)  # not retried — a genuinely slow source would recur
        self.assertEqual(sleeps, [])


class TransientFailureRetryTests(SimpleTestCase):
    def test_a_connection_error_is_retried_then_succeeds(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls < MAX_ATTEMPTS:
                raise httpx.ConnectError("connection refused", request=request)
            return httpx.Response(200, content=_streamed(b"final body"))

        gateway, sleeps = _make_gateway(handler)
        body, evidence = gateway._get(NEW_RELEASES_URL, kind="new_releases")

        self.assertEqual(calls, MAX_ATTEMPTS)
        self.assertEqual(sleeps, list(RETRY_BACKOFF_SECONDS[: MAX_ATTEMPTS - 1]))
        self.assertEqual(body, "final body")
        self.assertEqual(evidence.outcome, "succeeded")
        self.assertEqual(evidence.response_sha256, hashlib.sha256(b"final body").hexdigest())

    def test_a_connection_error_exhausts_retries_and_fails(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ConnectError("connection refused", request=request)

        gateway, sleeps = _make_gateway(handler)
        body, evidence = gateway._get(NEW_RELEASES_URL, kind="new_releases")

        self.assertIsNone(body)
        self.assertEqual(calls, MAX_ATTEMPTS)
        self.assertEqual(sleeps, list(RETRY_BACKOFF_SECONDS[: MAX_ATTEMPTS - 1]))
        self.assertEqual(evidence.outcome, "failed")
        self.assertEqual(evidence.error_code, "ConnectError")
        self.assertIsNone(evidence.http_status)

    def test_a_non_transport_http_error_is_not_retried(self) -> None:
        # httpx.HTTPError also covers non-transient, content/protocol-level failures (malformed
        # content-encoding, too many redirects) that would fail identically on retry.
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.DecodingError("bad content-encoding", request=request)

        gateway, sleeps = _make_gateway(handler)
        body, evidence = gateway._get(NEW_RELEASES_URL, kind="new_releases")

        self.assertIsNone(body)
        self.assertEqual(calls, 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(evidence.outcome, "failed")
        self.assertEqual(evidence.error_code, "DecodingError")

    def test_a_5xx_status_is_retried_then_succeeds(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(503, content=_streamed(b"upstream hiccup"))
            return httpx.Response(200, content=_streamed(b"final body"))

        gateway, sleeps = _make_gateway(handler)
        body, evidence = gateway._get(NEW_RELEASES_URL, kind="new_releases")

        self.assertEqual(calls, 2)
        self.assertEqual(sleeps, [RETRY_BACKOFF_SECONDS[0]])
        self.assertEqual(body, "final body")
        self.assertEqual(evidence.http_status, 200)
        self.assertEqual(evidence.outcome, "succeeded")

    def test_a_403_is_not_retried(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(403, content=_streamed(b"forbidden"))

        gateway, sleeps = _make_gateway(handler)
        body, evidence = gateway._get(NEW_RELEASES_URL, kind="new_releases")

        self.assertIsNone(body)
        self.assertEqual(calls, 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(evidence.outcome, "failed")
        self.assertEqual(evidence.error_code, "http_403")

    def test_a_429_is_not_retried_in_call(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                429, content=_streamed(b"rate limited"), headers={"Retry-After": "60"}
            )

        gateway, sleeps = _make_gateway(handler)
        body, evidence = gateway._get(NEW_RELEASES_URL, kind="new_releases")

        self.assertIsNone(body)
        self.assertEqual(calls, 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(evidence.outcome, "failed")
        self.assertEqual(evidence.error_code, "http_429")

    def test_retries_exhaust_at_the_configured_bound_regardless_of_status(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(502, content=_streamed(b"bad gateway"))

        gateway, sleeps = _make_gateway(handler)
        body, evidence = gateway._get(NEW_RELEASES_URL, kind="new_releases")

        self.assertIsNone(body)
        self.assertEqual(calls, MAX_ATTEMPTS)
        self.assertEqual(sleeps, list(RETRY_BACKOFF_SECONDS[: MAX_ATTEMPTS - 1]))
        self.assertEqual(evidence.error_code, "http_502")
        self.assertEqual(evidence.http_status, 502)


class SuccessPathTests(SimpleTestCase):
    def test_a_normal_response_is_read_fully_and_hashed_on_the_first_attempt(self) -> None:
        body_text = "<html><body>fine</body></html>"
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, content=_streamed(body_text.encode()))

        gateway, sleeps = _make_gateway(handler)
        body, evidence = gateway._get(NEW_RELEASES_URL, kind="new_releases")

        self.assertEqual(calls, 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(body, body_text)
        self.assertEqual(evidence.outcome, "succeeded")
        self.assertIsNone(evidence.error_code)
        self.assertEqual(evidence.response_sha256, hashlib.sha256(body_text.encode()).hexdigest())

    def test_a_response_split_across_many_chunks_is_reassembled_correctly(self) -> None:
        # A single chunk (the common MockTransport shortcut) can't prove reassembly is correct;
        # this forces the real multi-chunk accumulation path with a body larger than one
        # `_STREAM_CHUNK_SIZE` iteration.
        body_text = "<html>" + ("word " * 20000) + "</html>"

        def chunks() -> Iterator[bytes]:
            data = body_text.encode()
            for offset in range(0, len(data), 4096):
                yield data[offset : offset + 4096]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=chunks())

        gateway, _sleeps = _make_gateway(handler)
        body, evidence = gateway._get(NEW_RELEASES_URL, kind="new_releases")

        self.assertEqual(body, body_text)
        self.assertEqual(evidence.response_sha256, hashlib.sha256(body_text.encode()).hexdigest())
