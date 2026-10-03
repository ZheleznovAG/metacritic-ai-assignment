"""The real providers behind `letsplays.worker.Providers`: YouTube, yt-dlp and Groq."""

from __future__ import annotations

from typing import Any

import httpx

from letsplays import groq, youtube
from letsplays.groq import ChatResult
from letsplays.youtube import Found, Heard, VideoFacts


class LiveProviders:
    def __init__(
        self, *, youtube_key: str, groq_key: str, groq_base_url: str, client: httpx.Client
    ) -> None:
        self._youtube_key = youtube_key
        self._groq_key = groq_key
        self._groq_base_url = groq_base_url
        self._client = client

    def search(self, title: str) -> list[Found]:
        return youtube.search(self._client, self._youtube_key, title)

    def facts(self, video_id: str) -> VideoFacts:
        return youtube.facts(video_id)

    def captions(self, video_id: str, language: str | None, seconds: int) -> Heard | None:
        return youtube.captions(video_id, language, seconds)

    def whisper(self, audio_url: str) -> tuple[Heard, dict[str, str]]:
        fragment = youtube.audio_fragment(audio_url, self._client)
        try:
            result = groq.transcribe(
                self._client, api_key=self._groq_key, base_url=self._groq_base_url, audio=fragment
            )
        finally:
            fragment.unlink(missing_ok=True)
        heard = Heard(result.language, result.text, result.seconds or youtube.FRAGMENT_SECONDS)
        return heard, result.headers

    def chat(self, payload: dict[str, Any]) -> ChatResult:
        return groq.chat(
            self._client, api_key=self._groq_key, base_url=self._groq_base_url, payload=payload
        )
