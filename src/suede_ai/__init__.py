"""Suede AI Python SDK.

Python SDK for the Suede AI x402 surface: 20 confirmed-live paid endpoints
settled in USDC on Base (music, video, image, stem splitting, MIDI,
mastering, rights lookup, and more). Only 3 (plus credit purchase) are in
the public discovery manifest; every client method below works regardless.
The client wraps the EIP-3009 sign-retry loop so callers can spend their
time writing prompts, not signing typed data.

Quickstart::

    from suede_ai import SuedeClient

    client = SuedeClient(wallet_private_key="0x...")
    result = client.create_music(prompt="lo-fi rainy afternoon")
    print(result["assetUrl"])

The live x402 manifest is at ``https://app.suedeai.ai/.well-known/x402.json``.
Full endpoint reference: https://github.com/Suede-AI/suede-x402-acp
"""

from suede_ai.client import SuedeClient
from suede_ai.x402 import PaymentRequired, X402Error

__all__ = ["SuedeClient", "PaymentRequired", "X402Error"]
__version__ = "0.3.1"
