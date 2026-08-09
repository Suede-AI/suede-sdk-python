"""Suede AI Python SDK.

Python SDK for the current public Suede AI x402 surface: music, video, and
image generation settled in USDC on Base. Legacy convenience helpers remain
available for compatible deployments, but they are not current public inventory.
The client wraps the EIP-3009 sign-retry loop so callers can spend their
time writing prompts, not signing typed data.

Quickstart::

    from suede_ai import SuedeClient

    client = SuedeClient(wallet_private_key="0x...")
    result = client.create_music(prompt="lo-fi rainy afternoon")
    print(result["assetUrl"])

The live x402 manifest is at ``https://app.suedeai.ai/.well-known/x402.json``.
Public offering reference: https://github.com/JasonColapietro/suede-x402
"""

from suede_ai.client import SuedeClient
from suede_ai.x402 import PaymentRequired, X402Error

__all__ = ["PaymentRequired", "SuedeClient", "X402Error"]
__version__ = "0.3.1"
