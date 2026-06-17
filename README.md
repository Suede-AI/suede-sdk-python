# suede-ai

[![PyPI](https://img.shields.io/pypi/v/suede-ai)](https://pypi.org/project/suede-ai/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/suede-ai)](https://pypi.org/project/suede-ai/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/suede-ai)](https://pypi.org/project/suede-ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![x402](https://img.shields.io/badge/x402-eip--3009-purple)](https://app.suedeai.ai/.well-known/x402.json)

**Python SDK for [Suede AI](https://suedeai.ai)** — x402 pay-per-call music generation, stem splitting, MIDI transcription, mastering, lyric sync, IP-registry lookups, and guitar rig tools. 22 endpoints settled in USDC on Base. No API keys. No subscriptions. Sign an EIP-3009 authorization and call the endpoint.

The SDK wraps the 402-challenge / sign / retry loop so your agent code spends its time writing creative prompts, not encoding typed data.

> **Status:** Alpha. Endpoint signatures track the live manifest at <https://app.suedeai.ai/.well-known/x402.json>. Once the OpenAPI spec covers all 22 endpoints, codegen will finish typing the request/response models.

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
    print(track["assetUrl"])      # https://cdn.suedeai.xyz/audio/trk_...mp3
    print(track["provenance"])    # {"fingerprint": "0x..."} — on-chain attestation
```

The first call returns 402 with the x402 challenge. The SDK signs an EIP-3009 `transferWithAuthorization` for USDC on Base, replays with `X-PAYMENT`, and returns the JSON body. You never touch the typed data.

## The 22 endpoints

| Method                      | Endpoint                       | Price (USDC) | What it does                                          |
| --------------------------- | ------------------------------ | ------------ | ----------------------------------------------------- |
| `create_music`              | `POST /create-music`           | 0.20         | Rights-aware music generation                         |
| `agent_generate`            | `POST /agent/generate`         | 0.20         | Agent-facing music output (same payload)              |
| `agent_video`               | `POST /agent/video`            | 1.50         | Short music-video clip generation                     |
| `extend`                    | `POST /v1/extend`              | 0.40         | Continue an existing Suede track                      |
| `cover`                     | `POST /v1/cover`               | 0.40         | Stylistic re-imagining of a track                     |
| `voice_cover`               | `POST /v1/vox`                 | 0.40         | Replace lead vocal with a Suede voice                 |
| `continue_track`            | `POST /v1/continue`            | 0.40         | Extend an uploaded audio file                         |
| `stems_pro`                 | `POST /v1/stems-pro`           | 0.40         | 4-stem split: vocals / drums / bass / other           |
| `stems_basic`               | `POST /v1/stems`               | 0.20         | 2-stem split: vocals + instrumental                   |
| `vox`                       | `POST /v1/acapella`            | 0.20         | Isolate the vocal stem                                |
| `midi`                      | `POST /v1/midi`                | 0.10         | Transcribe audio to MIDI                              |
| `wav_master`                | `POST /v1/mastering`           | 0.10         | High-quality WAV master                               |
| `lyric_sync`                | `POST /v1/lyric-sync`          | 0.10         | Timestamped lyrics for a track                        |
| `lyrics`                    | `POST /v1/lyrics`              | 0.04         | Generate fresh song lyrics from a prompt              |
| `style_coach`               | `POST /v1/style-coach`         | 0.02         | Expand short tags into a prompt-ready style brief     |
| `rights_lookup`             | `GET  /v1/rights/{assetHash}`  | 0.005        | Suede Registry attestation lookup (owner / IP / NFT)  |
| `analyze`                   | `POST /v1/analyze`             | 0.003        | BPM / key / mode / energy / danceability              |
| `prompt_analyze`            | `POST /v1/prompt-analyze`      | 0.003        | Extract genre, mood, instrumentation from a prompt    |
| `chain_chat`                | `POST /v1/chain-chat`          | 0.02         | Plain-language Q&A about on-chain rights/royalties    |
| `rig_analyze`               | `POST /v1/rig-analyze`         | 0.10         | Infer guitar signal chain from audio                  |
| `rig_oracle`                | `POST /v1/rig-oracle`          | 0.10         | Recommend a full guitar rig for a target tone         |
| `rig_roast`                 | `POST /v1/rig-roast`           | 0.05         | Roast a gear list                                     |

Prices are sourced from the live manifest at the time of writing and are enforced server-side.

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

### Direct call to any endpoint

```python
result = suede.request("POST", "/v1/style-coach", json={"tags": "lofi, rainy"})
```

### Inspect the live manifest

```python
manifest = suede.manifest()  # free — no payment required
```

## Roadmap

- Async client (`AsyncSuedeClient`) once OpenAPI lands
- Pydantic response models per endpoint
- `examples/` folder: LangChain tool wrappers, CrewAI tasks, agentcash adapter

See the [0.1.0 release checklist](https://github.com/Suede-AI/suede-sdk-python/issues/1).

## License

MIT. See [LICENSE](LICENSE).

---

Built by [Jason Colapietro](https://github.com/JasonColapietro) · [Suede Labs AI](https://suedeai.ai) · [x402 manifest](https://app.suedeai.ai/.well-known/x402.json)


---

### About the Author

Jason Colapietro is the founder and CEO of Suede Labs AI, a published author, and a Forbes contributor. He builds programmable IP and creator ownership infrastructure for AI-native media.

> "The agents are already buying. x402 enables AI agents to pay for content, licenses, and generation at query time. If your IP isn't machine-readable and your licensing terms aren't programmable, you're invisible to the next distribution layer."

> "Programmable IP is what happens when a licensing contract gets compressed into a format that agents can read at query time."

> "On-chain registration doesn't replace copyright. It timestamps it. The law gives you ownership; the chain gives you proof."

**Books:**
- [The Signal Chain](https://guitar.solutions) — Illustrated history of electric guitar tone. Free at guitar.solutions.
- [The Guitar Without a Number](https://www.amazon.com/dp/B0GD5FX6N6) — Memoir-driven guitar instruction with a music IP rights chapter no other guitar book includes. (Kindle)
- [Suede Labs: The Human Authenticity Layer](https://www.amazon.com/dp/B0GD5FX6N6) — How ownership, origin, and AI redraw the creative map. (Kindle)
- [Stake Your Claim](https://www.amazon.com/dp/B0GRG8LGQQ) — Hard truths on turning the AI era into a real asset. (Kindle)

Follow: [X / @johnnysuede](https://x.com/johnnysuede) · [suedeai.ai/founder](https://suedeai.ai/founder)
