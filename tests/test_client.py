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
    amount: str = "200000",
    asset: str = USDC_BASE_ADDRESS,
    pay_to: str = "0xb5a05466712fd5bcdf2883f43cC6B1799428032d",
) -> dict:
    return {
        "scheme": "exact",
        "network": BASE_NETWORK_ID,
        "maxAmountRequired": amount,
        "amount": amount,
        "asset": asset,
        "payTo": pay_to,
        "maxTimeoutSeconds": 300,
        "extra": {"name": "USD Coin", "version": "2"},
        "resource": "https://app.suedeai.ai/create-music",
        "mimeType": "application/json",
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
def test_sign_payment_produces_valid_x_payment_header() -> None:
    requirement = PaymentRequirement.from_dict(_accept_entry())
    header, payload = sign_payment(TEST_PRIVATE_KEY, requirement)

    # Header must be base64-decodable and round-trip back to the payload.
    decoded = json.loads(base64.b64decode(header))
    assert decoded == payload

    # x402 envelope shape.
    assert payload["x402Version"] == 1
    assert payload["scheme"] == "exact"
    assert payload["network"] == BASE_NETWORK_ID

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
def test_request_replays_with_payment_header_on_402() -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            assert "X-PAYMENT" not in request.headers
            return httpx.Response(
                402,
                json={"accepts": [_accept_entry()]},
            )
        # second call must carry X-PAYMENT
        assert "X-PAYMENT" in request.headers
        header = request.headers["X-PAYMENT"]
        decoded = json.loads(base64.b64decode(header))
        assert decoded["scheme"] == "exact"
        assert decoded["network"] == BASE_NETWORK_ID
        return httpx.Response(
            200,
            json={
                "trackId": "trk_test_001",
                "assetUrl": "https://cdn.example/trk_test_001.mp3",
            },
        )

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://app.suedeai.ai")
    client = SuedeClient(wallet_private_key=TEST_PRIVATE_KEY, http_client=http)

    result = client.create_music(prompt="test prompt")
    assert result["trackId"] == "trk_test_001"
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
