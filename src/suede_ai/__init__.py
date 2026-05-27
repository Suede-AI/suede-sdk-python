"""Suede AI Python SDK.

A starter SDK for the Suede AI x402 surface — 17 pay-per-call endpoints
settled in USDC on Base. The client wraps the EIP-3009 sign-retry loop
so callers can spend their time writing prompts, not signing typed data.

Quickstart::

    from suede_ai import SuedeClient

    client = SuedeClient(wallet_private_key="0x...")
    result = client.create_music(prompt="lo-fi rainy afternoon", duration_seconds=30)
    print(result["assetUrl"])

The live x402 manifest is at ``https://app.suedeai.ai/.well-known/x402.json``.
"""

from suede_ai.client import SuedeClient
from suede_ai.x402 import PaymentRequired, X402Error

__all__ = ["SuedeClient", "PaymentRequired", "X402Error"]
__version__ = "0.1.0a1"
