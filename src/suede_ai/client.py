"""SuedeClient — synchronous Python client for the Suede AI x402 surface.

The client wraps the 402-challenge / sign / retry loop so callers can spend
their time writing creative prompts rather than signing EIP-3009 typed data.

The current paid resources exposed by the live manifest at
``https://app.suedeai.ai/.well-known/x402.json`` have typed methods below.
Older convenience helpers remain for callers using compatible deployments.
Pricing is enforced server-side; client-side amounts shown in docstrings
are sourced from the manifest at the time of writing and may change.
"""

from __future__ import annotations

import base64
import binascii
import json as jsonlib
import re
from typing import Any

import httpx

from suede_ai.x402 import (
    X402Error,
    select_requirement,
    sign_payment,
)

DEFAULT_BASE_URL = "https://app.suedeai.ai"
DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
MANIFEST_PATH = "/.well-known/x402.json"
_HEX_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class SuedeClient:
    """Synchronous client for the Suede AI x402 surface.

    Args:
        wallet_private_key: Hex-encoded private key (with or without ``0x`` prefix).
            Used to sign EIP-3009 authorizations for USDC on Base.
        base_url: Override for the API host. Defaults to ``https://app.suedeai.ai``.
        http_client: Optional pre-configured :class:`httpx.Client`. If provided,
            ``base_url`` and ``timeout`` are ignored on this argument.
        timeout: Per-request timeout. Defaults to 60s read / 10s connect.
        max_payment_attempts: How many times to replay after a 402. Defaults to 1
            (one challenge, one paid retry).

    Example:
        >>> client = SuedeClient(wallet_private_key="0x...")
        >>> track = client.create_music(prompt="lo-fi rainy afternoon")
        >>> track["assetUrl"]
        'https://cdn.suedeai.ai/audio/trk_....mp3'
    """

    def __init__(
        self,
        wallet_private_key: str,
        base_url: str = DEFAULT_BASE_URL,
        *,
        http_client: httpx.Client | None = None,
        timeout: httpx.Timeout | float | None = None,
        max_payment_attempts: int = 1,
    ) -> None:
        if not wallet_private_key:
            raise ValueError("wallet_private_key is required")
        self._private_key = wallet_private_key
        self._base_url = base_url.rstrip("/")
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            base_url=self._base_url,
            timeout=timeout or DEFAULT_TIMEOUT,
            headers={"User-Agent": "suede-ai-python/0.3.1"},
        )
        self._max_payment_attempts = max_payment_attempts

    # ------------------------------------------------------------------ lifecycle
    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> SuedeClient:  # noqa: PYI034 - Python 3.10 support
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------ low-level
    def manifest(self) -> dict[str, Any]:
        """Fetch the live x402 manifest (free, no payment required)."""
        response = self._http.get(MANIFEST_PATH)
        response.raise_for_status()
        return response.json()

    def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a paid request: on 402, sign EIP-3009 and replay with PAYMENT-SIGNATURE.

        Raises:
            PaymentRequired: server returned 402 but no acceptable scheme.
            httpx.HTTPStatusError: any non-2xx response after the paid retry.
        """
        attempt = 0
        last_response: httpx.Response | None = None
        payment_header: str | None = None
        while attempt <= self._max_payment_attempts:
            req_headers = {"PAYMENT-SIGNATURE": payment_header} if payment_header else None
            response = self._http.request(
                method, path, json=json, params=params, headers=req_headers
            )
            last_response = response
            if response.status_code != 402:
                response.raise_for_status()
                return _safe_json(response)

            challenge = _payment_challenge(response)
            accepts = challenge.get("accepts") or []
            requirement = select_requirement(accepts)
            resource = challenge.get("resource")
            extensions = challenge.get("extensions")
            payment_header, _payload = sign_payment(
                self._private_key,
                requirement,
                resource=resource if isinstance(resource, dict) else None,
                extensions=extensions if isinstance(extensions, dict) else None,
            )
            attempt += 1

        # We replayed but still got 402.
        assert last_response is not None
        raise X402Error(
            f"Payment exchange failed after {self._max_payment_attempts} retr(y/ies); "
            f"final status {last_response.status_code}"
        )

    # ------------------------------------------------------------------ endpoints
    # Music generation -----------------------------------------------------
    def create_music(
        self,
        *,
        prompt: str,
        duration_seconds: int = 30,
        style: str | None = None,
    ) -> dict[str, Any]:
        """``POST /create-music`` — rights-aware music generation (0.50 USDC).

        Returns ``{trackId, shareUrl, assetUrl, provenance: {fingerprint}}``.
        """
        body: dict[str, Any] = {"prompt": prompt, "durationSeconds": duration_seconds}
        if style:
            body["style"] = style
        return self.request("POST", "/create-music", json=body)

    def agent_generate(
        self,
        *,
        prompt: str,
        duration_seconds: int = 30,
        style: str | None = None,
    ) -> dict[str, Any]:
        """Deprecated compatibility wrapper for ``create_music`` (0.50 USDC).

        The retired ``/agent/generate`` route is not called. New and existing
        integrations are sent to the current public ``/create-music`` resource.
        """
        return self.create_music(
            prompt=prompt,
            duration_seconds=duration_seconds,
            style=style,
        )

    def agent_video(
        self,
        *,
        prompt: str,
        duration_seconds: int = 8,
        aspect_ratio: str | None = None,
        resolution: str | None = None,
    ) -> dict[str, Any]:
        """``POST /agent/video`` — 8-second 720p video with native audio (4.99 USDC).

        ``aspect_ratio`` one of ``"16:9" | "9:16" | "1:1"``;
        ``resolution`` one of ``"720p" | "1024p"``.
        """
        body: dict[str, Any] = {"prompt": prompt, "durationSeconds": duration_seconds}
        if aspect_ratio:
            body["aspectRatio"] = aspect_ratio
        if resolution:
            body["resolution"] = resolution
        return self.request("POST", "/agent/video", json=body)

    def agent_image(
        self,
        *,
        prompt: str,
        aspect_ratio: str | None = None,
        output_format: str | None = None,
    ) -> dict[str, Any]:
        """``POST /agent/image`` — rights-aware image generation (0.15 USDC).

        ``aspect_ratio`` examples include ``"1:1"``, ``"9:16"``, and ``"16:9"``;
        ``output_format`` one of ``"png" | "jpeg"``.
        """
        body: dict[str, Any] = {"prompt": prompt}
        if aspect_ratio:
            body["aspectRatio"] = aspect_ratio
        if output_format:
            body["outputFormat"] = output_format
        return self.request("POST", "/agent/image", json=body)

    # Music tools ----------------------------------------------------------
    def extend(
        self,
        *,
        source_clip_id: str | None = None,
        audio_url: str | None = None,
        prompt: str | None = None,
        title: str | None = None,
        tags: str | None = None,
        continue_at_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Legacy compatibility helper for ``POST /v1/extend``; read the live quote."""
        if not (source_clip_id or audio_url):
            raise ValueError("Provide source_clip_id or audio_url")
        body: dict[str, Any] = {}
        if source_clip_id:
            body["sourceClipId"] = source_clip_id
        if audio_url:
            body["audioUrl"] = audio_url
        if prompt:
            body["prompt"] = prompt
        if title:
            body["title"] = title
        if tags:
            body["tags"] = tags
        if continue_at_seconds is not None:
            body["continueAtSeconds"] = continue_at_seconds
        return self.request("POST", "/v1/extend", json=body)

    def cover(
        self,
        *,
        source_clip_id: str | None = None,
        audio_url: str | None = None,
        prompt: str | None = None,
        title: str | None = None,
        tags: str | None = None,
        style: str | None = None,
    ) -> dict[str, Any]:
        """Legacy compatibility helper for ``POST /v1/cover``; read the live quote."""
        if not (source_clip_id or audio_url):
            raise ValueError("Provide source_clip_id or audio_url")
        body: dict[str, Any] = {}
        if source_clip_id:
            body["sourceClipId"] = source_clip_id
        if audio_url:
            body["audioUrl"] = audio_url
        if prompt:
            body["prompt"] = prompt
        if title:
            body["title"] = title
        if tags:
            body["tags"] = tags
        if style:
            body["style"] = style
        return self.request("POST", "/v1/cover", json=body)

    def voice_cover(
        self,
        *,
        audio_url: str,
        voice_id: str | None = None,
        pitch_shift: float | None = None,
    ) -> dict[str, Any]:
        """Legacy compatibility helper for ``POST /v1/vox``; read the live quote."""
        body: dict[str, Any] = {"audioUrl": audio_url}
        if voice_id:
            body["voiceId"] = voice_id
        if pitch_shift is not None:
            body["pitchShift"] = pitch_shift
        return self.request("POST", "/v1/vox", json=body)

    def continue_track(
        self,
        *,
        audio_url: str,
        prompt: str | None = None,
        continue_at_seconds: float | None = None,
        duration_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Legacy compatibility helper for ``POST /v1/continue``; read the live quote."""
        body: dict[str, Any] = {"audioUrl": audio_url}
        if prompt:
            body["prompt"] = prompt
        if continue_at_seconds is not None:
            body["continueAtSeconds"] = continue_at_seconds
        if duration_seconds is not None:
            body["durationSeconds"] = duration_seconds
        return self.request("POST", "/v1/continue", json=body)

    def stems_pro(self, *, audio_url: str) -> dict[str, Any]:
        """Legacy compatibility helper for ``POST /v1/stems-pro``; read the live quote."""
        return self.request("POST", "/v1/stems-pro", json={"audioUrl": audio_url})

    def stems_basic(self, *, audio_url: str) -> dict[str, Any]:
        """Legacy compatibility helper for ``POST /v1/stems``; read the live quote."""
        return self.request("POST", "/v1/stems", json={"audioUrl": audio_url})

    def vox(self, *, audio_url: str) -> dict[str, Any]:
        """Legacy compatibility helper for ``POST /v1/acapella``; read the live quote."""
        return self.request("POST", "/v1/acapella", json={"audioUrl": audio_url})

    def midi(self, *, audio_url: str) -> dict[str, Any]:
        """Legacy compatibility helper for ``POST /v1/midi``; read the live quote."""
        return self.request("POST", "/v1/midi", json={"audioUrl": audio_url})

    def wav_master(self, *, audio_url: str) -> dict[str, Any]:
        """Legacy compatibility helper for ``POST /v1/mastering``; read the live quote."""
        return self.request("POST", "/v1/mastering", json={"audioUrl": audio_url})

    def lyric_sync(
        self,
        *,
        audio_url: str,
        lyrics: str | None = None,
    ) -> dict[str, Any]:
        """Legacy compatibility helper for ``POST /v1/lyric-sync``; read the live quote."""
        body: dict[str, Any] = {"audioUrl": audio_url}
        if lyrics:
            body["lyrics"] = lyrics
        return self.request("POST", "/v1/lyric-sync", json=body)

    def lyrics(self, *, prompt: str, style: str | None = None) -> dict[str, Any]:
        """Legacy compatibility helper for ``POST /v1/lyrics``; read the live quote."""
        body: dict[str, Any] = {"prompt": prompt}
        if style:
            body["style"] = style
        return self.request("POST", "/v1/lyrics", json=body)

    def style_coach(self, *, tags: str, target_count: int | None = None) -> dict[str, Any]:
        """Legacy compatibility helper for ``POST /v1/style-coach``; read the live quote."""
        body: dict[str, Any] = {"tags": tags}
        if target_count is not None:
            body["targetCount"] = target_count
        return self.request("POST", "/v1/style-coach", json=body)

    # Rights / analysis ----------------------------------------------------
    def rights_lookup(self, asset_hash: str) -> dict[str, Any]:
        """``GET /v1/rights/{assetHash}`` — Registry lookup (0.015 USDC live quote).

        ``asset_hash`` is a 32-byte content hash (sha256, hex-encoded, with or
        without ``0x`` prefix).
        """
        clean = asset_hash.removeprefix("0x")
        if not _HEX_HASH_RE.fullmatch(clean):
            raise ValueError("asset_hash must be a 64-character hex string")
        return self.request("GET", f"/v1/rights/{clean}")

    def analyze(self, *, audio_url: str) -> dict[str, Any]:
        """``POST /v1/analyze`` — BPM/key/mode/energy analysis (0.01 USDC live quote)."""
        return self.request("POST", "/v1/analyze", json={"audioUrl": audio_url})

    def prompt_analyze(self, *, prompt: str) -> dict[str, Any]:
        """Legacy compatibility helper for ``POST /v1/prompt-analyze``; read the live quote."""
        return self.request("POST", "/v1/prompt-analyze", json={"prompt": prompt})

    def chain_chat(self, *, question: str, asset_hash: str) -> dict[str, Any]:
        """Legacy compatibility helper for ``POST /v1/chain-chat``; read the live quote."""
        clean = asset_hash.removeprefix("0x")
        return self.request(
            "POST", "/v1/chain-chat", json={"question": question, "assetHash": clean}
        )

    # Guitar rig tools -----------------------------------------------------
    def rig_analyze(self, *, audio_url: str) -> dict[str, Any]:
        """Legacy compatibility helper for ``POST /v1/rig/analyze``; read the live quote."""
        return self.request("POST", "/v1/rig/analyze", json={"audioUrl": audio_url})

    def rig_oracle(
        self,
        *,
        goal: str,
        genre: str | None = None,
        budget_usd: float | None = None,
    ) -> dict[str, Any]:
        """Legacy compatibility helper for ``POST /v1/rig/oracle``; read the live quote."""
        body: dict[str, Any] = {"goal": goal}
        if genre:
            body["genre"] = genre
        if budget_usd is not None:
            body["budgetUsd"] = budget_usd
        return self.request("POST", "/v1/rig/oracle", json=body)

    def rig_roast(
        self,
        *,
        goal: str,
        gear: list[str] | None = None,
    ) -> dict[str, Any]:
        """Legacy compatibility helper for ``POST /v1/rig/roast``; read the live quote."""
        body: dict[str, Any] = {"goal": goal}
        if gear:
            body["gear"] = gear
        return self.request("POST", "/v1/rig/roast", json=body)


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def _payment_challenge(response: httpx.Response) -> dict[str, Any]:
    """Read the v2 challenge header first, with the JSON response as fallback."""
    encoded = response.headers.get("PAYMENT-REQUIRED")
    if encoded:
        try:
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
            challenge = jsonlib.loads(decoded)
            if isinstance(challenge, dict):
                return challenge
        except (binascii.Error, UnicodeDecodeError, ValueError):
            pass
    return _safe_json(response)
