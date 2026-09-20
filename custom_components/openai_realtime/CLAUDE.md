# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Home Assistant custom integration (`openai_realtime`) providing streaming STT and TTS via the **Azure OpenAI Realtime API over WebRTC** (GA protocol, using `aiortc`). The working directory is the component itself; the repo root (`../..`, `ha-realtime-gpt-azure/`) holds README.md, DEVELOPER.md, `hacs.json`, and `examples/configuration.yaml`. The Azure WebRTC flow is documented at https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/realtime-audio-webrtc

## Development workflow

There are no automated tests, linters, or build steps. Development is manual against a live Home Assistant instance:

1. Copy or symlink this folder into a HA instance's `config/custom_components/openai_realtime/`.
2. Restart Home Assistant (a restart is required after every code change — HA does not hot-reload custom components).
3. Enable debug logging in HA's `configuration.yaml`:
   ```yaml
   logger:
     logs:
       custom_components.openai_realtime: debug
   ```

Requires an Azure OpenAI resource (endpoint + API key) with a realtime model deployment (e.g. `gpt-realtime`) in a supported region.

## Architecture

One shared WebRTC client per config entry, consumed by two legacy-style HA platforms:

- `__init__.py` creates a single `OpenAIRealtimeClient` and stores it in `hass.data[DOMAIN][entry_id]["client"]`, then loads the STT and TTS platforms via the legacy `async_load_platform` discovery mechanism (not modern config-entry platform forwarding / entity classes). `stt.py` and `tts.py` implement the legacy `Provider` interfaces and expose both `async_setup_platform` and `async_get_engine`. Config entries are version 2 (endpoint + API key in `data`, deployment/voice/instructions in `options`); version 1 entries (old OpenAI WebSocket config) can't be migrated — `async_migrate_entry` returns False.

- `realtime_client.py` owns the WebRTC session (Azure GA protocol):
  1. `connect()` POSTs the session config (model deployment, instructions, `semantic_vad`, voice) to `{endpoint}/openai/v1/realtime/client_secrets` with the `api-key` header → ephemeral client secret.
  2. Builds an aiortc `RTCPeerConnection` with an outgoing `MicrophoneStreamTrack` and a data channel named `realtime-channel`, then POSTs the SDP offer to `{endpoint}/openai/v1/realtime/calls` (`Authorization: Bearer <ephemeral>`, `Content-Type: application/sdp`; answer comes back with 200/201 + a `Location` header carrying the call id).
  3. **Audio flows over media tracks, events over the data channel.** `MicrophoneStreamTrack` paces buffered PCM16 into 20 ms `av.AudioFrame`s (silence when idle — required to keep server VAD alive); aiortc's Opus encoder resamples internally. The remote track is consumed continuously and resampled to PCM16/24 kHz mono, but frames are only forwarded to the audio callback while `output_audio_buffer.started`…`stopped` is active (the track streams silence between responses).
  4. Client events (`input_audio_buffer.commit`, `response.create`, `response.cancel`, `conversation.item.create`, `output_audio_buffer.clear`) are JSON over the data channel; `input_audio_buffer.append` is NOT used (audio goes via the track). Barge-in: on `input_audio_buffer.speech_started` the client sends `response.cancel` + `output_audio_buffer.clear`.

- STT and TTS follow the same request pattern: (re)connect if needed, register callbacks on the shared client, push results into an `asyncio.Queue` where `None` is the completion sentinel, with a 30 s timeout; both drain stale queue items at request start. **Completion signals differ**: STT finishes on `response.done` (transcript complete), TTS finishes on `output_audio_buffer.stopped` via `set_audio_done_callback` — because WebRTC audio plays out in real time and outlives `response.done`. STT must call `client.set_input_sample_rate(int(metadata.sample_rate))` before streaming since frame timestamps depend on the actual PCM rate. `commit_audio()` waits for the mic track to drain (media is real-time paced) before committing.

Because both platforms overwrite callbacks on the *same* client instance, concurrent STT and TTS requests will steal each other's callbacks — keep this in mind when touching the callback flow.

Note the STT quirk (inherited design): the "STT result" returned to HA is the transcript of the *model's spoken response* (`response.output_audio_transcript.delta`), not a transcription of the user's input.

## Gotchas

- The only external dependency is `aiortc` (pulls in `av`); it's pinned in `manifest.json` and repo-root `requirements.txt`.
- Timing: the mic media track transmits at real-time pace, so committing before `MicrophoneStreamTrack.wait_drained()` returns would truncate the utterance; similarly TTS collection takes as long as the audio playout.
- Ephemeral client secrets are short-lived — they're fetched fresh inside every `connect()`; the WebRTC call itself persists across requests.
- Expected/ignorable API error codes (`response_cancel_not_active`, `conversation_already_has_active_response`, `input_audio_buffer_commit_empty`) are logged at debug level; `semantic_vad` may auto-create responses, making the explicit `response.create` after commit racy by design.
- Translations: `translations/en.json` is what HA actually loads for a custom component (`strings.json` is kept in sync as the source); update `fr.json` too when changing config/options flow fields.
