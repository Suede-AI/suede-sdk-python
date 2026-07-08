# suede-ai

[![PyPI](https://img.shields.io/pypi/v/suede-ai)](https://pypi.org/project/suede-ai/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/suede-ai)](https://pypi.org/project/suede-ai/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/suede-ai)](https://pypi.org/project/suede-ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![x402](https://img.shields.io/badge/x402-eip--3009-purple)](https://app.suedeai.ai/.well-known/x402.json)

> **A [Suede Labs AI](https://suedeai.ai) project · Built by [Jason Colapietro](https://suedeai.ai/founder)**

**Python SDK for [Suede Labs AI](https://suedeai.ai)** — x402 pay-per-call music, video, image, and 17 more musician and utility tools, all settled in USDC on Base. 20 client methods hit a live `402 Payment Required` challenge today; only 3 (plus credit purchase) are in the public discovery manifest, but every method below works. No API keys. No subscriptions. Sign an EIP-3009 authorization and call the resource.

The SDK wraps the 402-challenge / sign / retry loop so your agent code spends its time writing creative prompts, not encoding typed data.

## Install

```bash
pip install suede-ai
```

Requires Python 3.10+. Pulls in `httpx`, `eth-account`, and `pydantic`.

## 60-second quickstart

```python
from suede_ai import SuedeClient

# Funded EOA on Base with USDC. Treat this like any other secret.
PRIVATE_KEY = "0x..."

with SuedeClient(wallet_private_key=PRIVATE_KEY) as suede:
    track = suede.create_music(
        prompt="lo-fi rainy afternoon, vinyl crackle, soft piano",
        duration_seconds=30,
    )
    print(track["assetUrl"])      # https://cdn.suedeai.ai/audio/trk_...mp3
    print(track["provenance"])    # {"fingerprint": "0x..."} — on-chain attestation
```

The first call returns 402 with the x402 challenge. The SDK signs an EIP-3009 `transferWithAuthorization` for USDC on Base, replays with `X-PAYMENT`, and returns the JSON body. You never touch the typed data.

## Current paid resources

In the public discovery manifest (`/.well-known/x402.json`) plus credit purchase:

| Method                      | Endpoint                       | Price (USDC) | What it does                                          |
| --------------------------- | ------------------------------ | ------------ | ----------------------------------------------------- |
| `create_music`              | `POST /create-music`           | 0.20         | Rights-aware music generation                         |
| `agent_video`               | `POST /agent/video`            | 1.50         | Short music-video clip generation                     |
| `agent_image`               | `POST /agent/image`            | 0.05         | Rights-aware image generation                         |

Live and callable directly (same pipeline, not currently in the public discovery manifest):

| Method          | Endpoint                | Price (USDC) | What it does                                                      |
| --------------- | ------------------------ | ------------ | ------------------------------------------------------------------ |
| `agent_generate`| `POST /agent/generate`   | 0.20         | Agent-facing music generation (same pipeline as `create_music`)    |
| `rights_lookup` | `GET /v1/rights/{hash}`  | 0.005        | Registry attestation lookup (rights, owner, on-chain metadata)     |
| `analyze`       | `POST /v1/analyze`       | 0.003        | Audio analysis (BPM, key, mode, energy, danceability)              |
| `prompt_analyze`| `POST /v1/prompt-analyze`| 0.003        | Route a prompt by genre, mood, instrumentation, structure          |
| `chain_chat`    | `POST /v1/chain-chat`    | 0.02         | Plain-language Q&A against a registered asset's on-chain rights    |
| `extend`        | `POST /v1/extend`        | 0.40         | Extend an existing track                                           |
| `cover`         | `POST /v1/cover`         | 0.40         | Generate a cover version                                           |
| `continue_track`| `POST /v1/continue`      | 0.40         | Continue a track from a point                                      |
| `voice_cover`   | `POST /v1/vox`           | 0.40         | Voice swap                                                          |
| `stems_pro`     | `POST /v1/stems-pro`     | 0.40         | 4-track stem split                                                  |
| `stems_basic`   | `POST /v1/stems`         | 0.20         | 2-track stem split                                                  |
| `vox`           | `POST /v1/acapella`      | 0.20         | Vocal isolation                                                     |
| `midi`          | `POST /v1/midi`          | 0.10         | MIDI transcription                                                  |
| `wav_master`    | `POST /v1/mastering`     | 0.10         | WAV mastering                                                       |
| `lyric_sync`    | `POST /v1/lyric-sync`    | 0.10         | Lyric-to-audio sync                                                 |
| `lyrics`        | `POST /v1/lyrics`        | 0.04         | Lyric generation                                                    |
| `style_coach`   | `POST /v1/style-coach`   | 0.02         | Style/tag coaching                                                  |

All 20 methods above were verified live against `app.suedeai.ai` on 2026-07-07 — each returned a priced `402` challenge when called without payment. Prices are enforced server-side and can drift from this table; call `suede.manifest()` for the live discovery subset or read the full reference at [suede-x402-acp](https://github.com/Suede-AI/suede-x402-acp).

`rig_analyze`, `rig_oracle`, and `rig_roast` also exist as client methods but did not return a valid `402` challenge in the last verification pass (a plain validation error instead) — treat these as unconfirmed until re-verified.

## How payment works

1. Client calls `POST /create-music`.
2. Server returns **402 Payment Required** with a JSON `accepts` array. Each entry declares scheme (`exact`), network (`eip155:8453`), asset (USDC on Base), `payTo` address, and `maxAmountRequired`.
3. SDK builds an EIP-3009 `TransferWithAuthorization` typed message and signs it with the configured wallet.
4. SDK base64-encodes the payment payload and replays the original request with the `X-PAYMENT` header.
5. Suede's facilitator settles on-chain; the response body returns asset URL + on-chain provenance.

You can inspect the live manifest yourself:

```bash
curl https://app.suedeai.ai/.well-known/x402.json | jq
```

## Advanced

### Reuse an `httpx.Client`

```python
import httpx
from suede_ai import SuedeClient

http = httpx.Client(http2=True, timeout=120.0)
suede = SuedeClient(wallet_private_key=PRIVATE_KEY, http_client=http)
```

### Direct call to any current resource

```python
result = suede.request("POST", "/agent/image", json={"prompt": "lo-fi rainy afternoon album art"})
```

### Inspect the live manifest

```python
manifest = suede.manifest()  # free — no payment required
```

### Rights and on-chain tools

```python
# Q&A about on-chain rights for a specific asset
answer = suede.chain_chat(
    question="Who owns this track and what licenses are active?",
    asset_hash="0xabc123...",
)

# Analyze what genre/mood a text prompt implies
analysis = suede.prompt_analyze(prompt="dark cinematic orchestral tension build")
```

### Unconfirmed: guitar rig tools

`rig_analyze`, `rig_oracle`, and `rig_roast` are callable client methods, but `rig_analyze` returned a plain validation error (not a priced `402` challenge) in the last verification pass — these may not be wired to the payment gate on all deployments. Confirm live before relying on them.

```python
# What signal chain is this guitar recording running?
chain = suede.rig_analyze(audio_url="https://cdn.example.com/riff.mp3")

# Recommend a rig for a target tone
rig = suede.rig_oracle(goal="warm blues crunch", genre="blues", budget_usd=1500)

# Roast your pedalboard
roast = suede.rig_roast(goal="tight metal", gear=["Boss DS-1", "Line 6 Spider"])
```

## Roadmap

- Async client (`AsyncSuedeClient`)
- Pydantic response models per endpoint
- `examples/` folder: LangChain tool wrappers, CrewAI tasks, agentcash adapter

## License

MIT. See [LICENSE](LICENSE).

---

Built by [Jason Colapietro](https://github.com/JasonColapietro) · [Suede Labs AI](https://suedeai.ai) · [x402 manifest](https://app.suedeai.ai/.well-known/x402.json)
