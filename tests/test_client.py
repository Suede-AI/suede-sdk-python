"""Tests for the Suede AI SDK scaffold.

These tests are offline-only and never call any paid endpoint. We mock the
402 challenge / paid retry handshake to verify the EIP-3009 typed-data
structure matches what the live USDC-on-Base contract expects.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from eth_account import Account

from suede_ai import SuedeClient, X402Error
from suede_ai.x402 import (
    BASE_CHAIN_ID,
    BASE_NETWORK_ID,
    USDC_BASE_ADDRESS,
    PaymentRequirement,
    build_typed_data,
    select_requirement,
    sign_payment,
)

# Deterministic burner key — never funded, never used outside tests.
TEST_PRIVATE_KEY = "0x" + "11" * 32


def _accept_entry(
    *,
    amount: str = "500000",
    asset: str = USDC_BASE_ADDRESS,
    pay_to: str = "0xb5a05466712fd5bcdf2883f43cC6B1799428032d",
    network: str = BASE_NETWORK_ID,
    price_usd: str = "$0.50",
    resource_url: str = "https://app.suedeai.ai/create-music",
    output_schema: dict | None = None,
) -> dict:
    entry = {
        "scheme": "exact",
        "network": network,
        "maxAmountRequired": amount,
        "amount": amount,
        "asset": asset,
        "payTo": pay_to,
        "maxTimeoutSeconds": 300,
        "docs": "https://app.suedeai.ai/developers",
        "extra": {
            "name": "USD Coin",
            "version": "2",
            "decimals": 6,
            "priceUsd": price_usd,
        },
        "resource": resource_url,
        "description": "Paid media generation for agents.",
        "mimeType": "application/json",
    }
    if output_schema is not None:
        entry["outputSchema"] = output_schema
    return entry


VIDEO_RESOURCE = {
    "url": "https://app.suedeai.ai/agent/video",
    "description": "Text-to-video generation for agents.",
    "mimeType": "application/json",
    "serviceName": "Suede AI",
    "tags": ["video", "video-generation", "text-to-video"],
}
VIDEO_EXTENSIONS = {
    "skyfire": {
        "header": "PAYMENT-SIGNATURE",
        "tokenTypes": ["pay+jwt", "kya-pay+jwt"],
    },
    "bazaar": {
        "info": {
            "input": {
                "type": "http",
                "method": "POST",
                "bodyType": "json",
                "body": {"prompt": "<prompt>", "durationSeconds": 8},
            },
            "output": {
                "type": "json",
                "example": {
                    "jobId": "video-job-example",
                    "status": "queued",
                    "provider": "suede",
                    "pollUrl": "https://app.suedeai.ai/agent/video/video-job-example",
                },
            },
        }
    },
}


def _live_shaped_video_challenge() -> dict:
    """Mirror the live dual-network x402-v2 challenge without making a paid call."""
    output_schema = {
        "input": {
            "type": "http",
            "method": "POST",
            "discoverable": True,
            "bodyType": "json",
            "body": {"prompt": "<prompt>", "durationSeconds": 8, "aspectRatio": "16:9"},
        },
        "output": {
            "jobId": "video-job-example",
            "status": "queued",
            "provider": "suede",
            "pollUrl": "https://app.suedeai.ai/agent/video/video-job-example",
        },
    }
    common = {
        "amount": "4990000",
        "pay_to": "0x10FF767043A1723E0BB5B9207bC37D3442cC9E4F",
        "price_usd": "$4.99",
        "resource_url": VIDEO_RESOURCE["url"],
        "output_schema": output_schema,
    }
    return {
        "x402Version": 2,
        "error": "PAYMENT-SIGNATURE header is required",
        "resource": VIDEO_RESOURCE,
        "accepts": [
            _accept_entry(network="base", **common),
            _accept_entry(network=BASE_NETWORK_ID, **common),
        ],
        "extensions": VIDEO_EXTENSIONS,
    }


# --------------------------------------------------------------------------- basics
def test_client_instantiates_with_private_key() -> None:
    client = SuedeClient(wallet_private_key=TEST_PRIVATE_KEY)
    assert client is not None
    client.close()


def test_client_rejects_missing_key() -> None:
    with pytest.raises(ValueError):
        SuedeClient(wallet_private_key="")


def test_context_manager_closes() -> None:
    with SuedeClient(wallet_private_key=TEST_PRIVATE_KEY) as client:
        assert client is not None


# --------------------------------------------------------------------------- typed-data shape
def test_typed_data_matches_eip_3009_for_usdc_base() -> None:
    requirement = PaymentRequirement.from_dict(_accept_entry())
    authorization = {
        "from": "0x0000000000000000000000000000000000000001",
        "to": requirement.pay_to,
        "value": requirement.max_amount_required,
        "validAfter": "1",
        "validBefore": "100000",
        "nonce": "0x" + "ab" * 32,
    }
    typed = build_typed_data(requirement, authorization)

    # Domain — must match the live USDC contract on Base.
    assert typed["domain"]["name"] == "USD Coin"
    assert typed["domain"]["version"] == "2"
    assert typed["domain"]["chainId"] == BASE_CHAIN_ID
    assert typed["domain"]["verifyingContract"].lower() == USDC_BASE_ADDRESS.lower()

    # Primary type & field order — EIP-3009 spec.
    assert typed["primaryType"] == "TransferWithAuthorization"
    fields = [f["name"] for f in typed["types"]["TransferWithAuthorization"]]
    assert fields == ["from", "to", "value", "validAfter", "validBefore", "nonce"]


def test_select_requirement_prefers_usdc_base_exact() -> None:
    accepts = [
        {**_accept_entry(), "scheme": "exact", "network": "eip155:1"},
        _accept_entry(),  # the USDC-on-Base entry
    ]
    chosen = select_requirement(accepts)
    assert chosen.network == BASE_NETWORK_ID
    assert chosen.asset.lower() == USDC_BASE_ADDRESS.lower()


def test_select_requirement_raises_when_no_accepts() -> None:
    with pytest.raises(X402Error):
        select_requirement([])


# --------------------------------------------------------------------------- signing
def test_sign_payment_produces_full_v2_payment_payload() -> None:
    challenge = _live_shaped_video_challenge()
    requirement = select_requirement(challenge["accepts"])
    header, payload = sign_payment(
        TEST_PRIVATE_KEY,
        requirement,
        resource=challenge["resource"],
        extensions=challenge["extensions"],
    )

    # Header must be base64-decodable and round-trip back to the payload.
    decoded = json.loads(base64.b64decode(header))
    assert decoded == payload

    # Full x402-v2 envelope. The accepted requirement is the CAIP-2 option,
    # uses `amount`, and does not leak the v1 `maxAmountRequired` alias.
    assert set(payload) == {"x402Version", "resource", "accepted", "extensions", "payload"}
    assert payload["x402Version"] == 2
    assert payload["resource"] == VIDEO_RESOURCE
    assert payload["extensions"] == VIDEO_EXTENSIONS
    assert payload["accepted"] == {
        "scheme": "exact",
        "network": BASE_NETWORK_ID,
        "amount": "4990000",
        "asset": USDC_BASE_ADDRESS,
        "payTo": "0x10FF767043A1723E0BB5B9207bC37D3442cC9E4F",
        "maxTimeoutSeconds": 300,
        "extra": {
            "name": "USD Coin",
            "version": "2",
            "decimals": 6,
            "priceUsd": "$4.99",
        },
    }

    inner = payload["payload"]
    assert inner["signature"].startswith("0x")
    assert len(inner["signature"]) == 132  # 0x + 130 hex chars = 65-byte sig

    auth = inner["authorization"]
    expected_from = Account.from_key(TEST_PRIVATE_KEY).address
    assert auth["from"] == expected_from
    assert auth["to"] == requirement.pay_to
    assert auth["value"] == requirement.max_amount_required
    assert auth["nonce"].startswith("0x") and len(auth["nonce"]) == 66


# --------------------------------------------------------------------------- 402 retry loop
def test_request_prefers_payment_required_header_and_returns_queued_media() -> None:
    call_count = {"n": 0}
    challenge = _live_shaped_video_challenge()
    challenge_header = base64.b64encode(
        json.dumps(challenge, separators=(",", ":")).encode()
    ).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            assert "PAYMENT-SIGNATURE" not in request.headers
            return httpx.Response(
                402,
                headers={"PAYMENT-REQUIRED": challenge_header},
                # Deliberately unusable body: header parsing must win.
                json={"x402Version": 2, "accepts": [_accept_entry(network="base")]},
            )
        assert "PAYMENT-SIGNATURE" in request.headers
        assert "X-PAYMENT" not in request.headers
        header = request.headers["PAYMENT-SIGNATURE"]
        decoded = json.loads(base64.b64decode(header))
        assert decoded["x402Version"] == 2
        assert decoded["accepted"]["network"] == BASE_NETWORK_ID
        assert decoded["accepted"]["amount"] == "4990000"
        assert decoded["resource"] == VIDEO_RESOURCE
        assert decoded["extensions"] == VIDEO_EXTENSIONS
        return httpx.Response(
            202,
            json={
                "jobId": "video-job-001",
                "status": "queued",
                "provider": "suede",
                "pollUrl": "https://app.suedeai.ai/agent/video/video-job-001",
            },
        )

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://app.suedeai.ai")
    client = SuedeClient(wallet_private_key=TEST_PRIVATE_KEY, http_client=http)

    result = client.agent_video(prompt="A rain-soaked neon street")
    assert result == {
        "jobId": "video-job-001",
        "status": "queued",
        "provider": "suede",
        "pollUrl": "https://app.suedeai.ai/agent/video/video-job-001",
    }
    assert call_count["n"] == 2


def test_request_falls_back_to_json_challenge_when_header_is_missing() -> None:
    call_count = {"n": 0}
    challenge = _live_shaped_video_challenge()

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(402, json=challenge)
        decoded = json.loads(base64.b64decode(request.headers["PAYMENT-SIGNATURE"]))
        assert decoded["accepted"]["network"] == BASE_NETWORK_ID
        return httpx.Response(200, json={"trackId": "trk_body_fallback"})

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://app.suedeai.ai")
    client = SuedeClient(wallet_private_key=TEST_PRIVATE_KEY, http_client=http)

    result = client.create_music(prompt="body fallback")

    assert result == {"trackId": "trk_body_fallback"}
    assert call_count["n"] == 2


def test_request_raises_after_max_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"accepts": [_accept_entry()]})

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://app.suedeai.ai")
    client = SuedeClient(
        wallet_private_key=TEST_PRIVATE_KEY,
        http_client=http,
        max_payment_attempts=1,
    )

    with pytest.raises(X402Error):
        client.create_music(prompt="will keep failing")


def test_agent_generate_compatibility_wrapper_uses_create_music_route() -> None:
    """The legacy method name must never send callers to the retired route."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/create-music"
        assert json.loads(request.content) == {
            "prompt": "compatibility call",
            "durationSeconds": 45,
            "style": "ambient",
        }
        return httpx.Response(200, json={"trackId": "trk_compat"})

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://app.suedeai.ai")
    client = SuedeClient(wallet_private_key=TEST_PRIVATE_KEY, http_client=http)

    result = client.agent_generate(
        prompt="compatibility call",
        duration_seconds=45,
        style="ambient",
    )

    assert result == {"trackId": "trk_compat"}


# --------------------------------------------------------------------------- coverage of method surface
@pytest.mark.parametrize(
    "method_name",
    [
        "create_music",
        "agent_video",
        "agent_image",
    ],
)
def test_current_paid_manifest_resources_are_exposed(method_name: str) -> None:
    """All current paid resources from the live manifest have callable methods."""
    client = SuedeClient(wallet_private_key=TEST_PRIVATE_KEY)
    assert callable(getattr(client, method_name))
    client.close()


@pytest.mark.parametrize(
    "method_name",
    [
        "agent_generate",
        "extend",
        "cover",
        "voice_cover",
        "continue_track",
        "stems_pro",
        "stems_basic",
        "vox",
        "midi",
        "wav_master",
        "lyric_sync",
        "lyrics",
        "style_coach",
        "rights_lookup",
        "analyze",
        "prompt_analyze",
        "chain_chat",
        "rig_analyze",
        "rig_oracle",
        "rig_roast",
    ],
)
def test_legacy_convenience_methods_remain_available(method_name: str) -> None:
    """Older helpers remain callable for clients using compatible deployments."""
    client = SuedeClient(wallet_private_key=TEST_PRIVATE_KEY)
    assert callable(getattr(client, method_name))
    client.close()
