"""x402 payment helper.

Implements the EIP-3009 ``transferWithAuthorization`` typed-data signing
used by the Suede AI x402 endpoints. On a 402 challenge from the server,
we read the ``accepts`` array, sign an authorization for the canonical
USDC contract on Base, and replay the request with a ``PAYMENT-SIGNATURE``
header containing the base64-encoded x402-v2 payload.

References:
    - x402 spec: https://x402.gitbook.io/x402/
    - EIP-3009: https://eips.ethereum.org/EIPS/eip-3009
    - Live manifest: https://app.suedeai.ai/.well-known/x402.json
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data

# Canonical USDC on Base (verified against the live x402 manifest).
USDC_BASE_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_CHAIN_ID = 8453
BASE_NETWORK_ID = "eip155:8453"


class X402Error(Exception):
    """Base error for x402 sign / settle problems."""


class PaymentRequired(X402Error):
    """Raised when the server returns 402 but no acceptable scheme is offered."""


@dataclass
class PaymentRequirement:
    """One row from the server's ``accepts`` array.

    Only fields needed for EIP-3009 signing are typed; the rest stays in ``raw``.
    """

    scheme: str
    network: str
    asset: str
    pay_to: str
    max_amount_required: str
    max_timeout_seconds: int
    resource: str
    extra: dict[str, Any]
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaymentRequirement:
        return cls(
            scheme=data["scheme"],
            network=data["network"],
            asset=data["asset"],
            pay_to=data["payTo"],
            max_amount_required=str(data.get("amount") or data["maxAmountRequired"]),
            max_timeout_seconds=int(data.get("maxTimeoutSeconds", 300)),
            resource=data.get("resource", ""),
            extra=data.get("extra", {}),
            raw=data,
        )

    def as_v2_accepted(self) -> dict[str, Any]:
        """Return the strict x402-v2 ``accepted`` requirement shape."""
        accepted: dict[str, Any] = {
            "scheme": self.scheme,
            "network": self.network,
            "amount": self.max_amount_required,
            "asset": self.asset,
            "payTo": self.pay_to,
            "maxTimeoutSeconds": self.max_timeout_seconds,
        }
        if self.extra:
            accepted["extra"] = self.extra
        return accepted


def select_requirement(
    accepts: list[dict[str, Any]],
    *,
    preferred_asset: str = USDC_BASE_ADDRESS,
    preferred_network: str = BASE_NETWORK_ID,
) -> PaymentRequirement:
    """Pick a usable accept entry, requiring USDC on Base + exact scheme."""
    if not accepts:
        raise PaymentRequired("Server returned 402 with no acceptable schemes.")

    matching = [
        entry
        for entry in accepts
        if entry.get("scheme") == "exact"
        and entry.get("asset", "").lower() == preferred_asset.lower()
        and entry.get("network") == preferred_network
    ]
    if not matching:
        raise PaymentRequired(
            "No 'exact' scheme offering USDC on Base was found in the server's accepts array."
        )
    return PaymentRequirement.from_dict(matching[0])


def build_authorization(
    requirement: PaymentRequirement,
    *,
    from_address: str,
    valid_for_seconds: int = 600,
) -> dict[str, Any]:
    """Build the EIP-3009 ``transferWithAuthorization`` message body.

    ``validAfter`` is set to (now - 60) to absorb modest clock skew between
    client and facilitator. ``validBefore`` extends a bit past the server's
    declared timeout so the facilitator has room to settle.
    """
    now = int(time.time())
    nonce_bytes = secrets.token_bytes(32)
    nonce_hex = "0x" + nonce_bytes.hex()
    valid_after = now - 60
    valid_before = now + max(valid_for_seconds, requirement.max_timeout_seconds + 60)

    return {
        "from": from_address,
        "to": requirement.pay_to,
        "value": requirement.max_amount_required,
        "validAfter": str(valid_after),
        "validBefore": str(valid_before),
        "nonce": nonce_hex,
    }


def build_typed_data(
    requirement: PaymentRequirement,
    authorization: dict[str, Any],
    *,
    chain_id: int = BASE_CHAIN_ID,
) -> dict[str, Any]:
    """Build the EIP-712 typed data for ``transferWithAuthorization``.

    The ``extra`` block in the x402 ``accepts`` entry carries the EIP-712
    domain ``name`` and ``version`` from the USDC contract (e.g. "USD Coin", "2").
    """
    domain_name = requirement.extra.get("name", "USD Coin")
    domain_version = requirement.extra.get("version", "2")

    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "TransferWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
            ],
        },
        "domain": {
            "name": domain_name,
            "version": domain_version,
            "chainId": chain_id,
            "verifyingContract": requirement.asset,
        },
        "primaryType": "TransferWithAuthorization",
        "message": {
            "from": authorization["from"],
            "to": authorization["to"],
            "value": int(authorization["value"]),
            "validAfter": int(authorization["validAfter"]),
            "validBefore": int(authorization["validBefore"]),
            "nonce": authorization["nonce"],
        },
    }


def sign_payment(
    private_key: str,
    requirement: PaymentRequirement,
    *,
    chain_id: int = BASE_CHAIN_ID,
    resource: dict[str, Any] | None = None,
    extensions: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Sign an EIP-3009 authorization and return ``(payment_header, payload)``.

    The header value is the base64-encoded JSON x402-v2 PaymentPayload. The
    selected requirement is echoed as ``accepted`` and challenge-level
    resource metadata and extensions are echoed when supplied.
    """
    account = Account.from_key(private_key)
    authorization = build_authorization(requirement, from_address=account.address)
    typed_data = build_typed_data(requirement, authorization, chain_id=chain_id)

    signable = encode_typed_data(full_message=typed_data)
    signed = Account.sign_message(signable, private_key=private_key)
    signature = signed.signature.hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature

    payload = {
        "x402Version": 2,
        "resource": resource,
        "accepted": requirement.as_v2_accepted(),
        "extensions": extensions,
        "payload": {
            "signature": signature,
            "authorization": authorization,
        },
    }
    if resource is None:
        payload.pop("resource")
    if extensions is None:
        payload.pop("extensions")
    header = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return header, payload
