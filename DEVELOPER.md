# Developer Guide

## Project Structure

```
home-assistant-openai/
├── .github/
│   └── copilot-instructions.md     # Development guidelines
├── custom_components/
│   └── openai_realtime/
│       ├── __init__.py              # Integration setup & entry point
│       ├── manifest.json            # Integration metadata
│       ├── const.py                 # Constants & configuration
│       ├── config_flow.py           # Configuration UI flow
│       ├── realtime_client.py       # WebSocket client for OpenAI API
│       ├── stt.py                   # Speech-to-text platform
│       ├── tts.py                   # Text-to-speech platform
│       ├── exceptions.py            # Custom exceptions
│       ├── strings.json             # English translations
│       └── translations/
│           └── fr.json              # French translations
├── examples/
│   └── configuration.yaml           # Example HA configuration
├── README.md                        # Main documentation
├── QUICKSTART.md                    # Quick start guide
├── CONTRIBUTING.md                  # Contribution guidelines
├── LICENSE                          # MIT License
├── hacs.json                        # HACS metadata
└── requirements.txt                 # Python dependencies
```

## Architecture Overview

### WebSocket Communication Flow

```
User Audio Input
    ↓
[Home Assistant]
    ↓ (STT Platform)
[OpenAI Realtime Client]
    ↓ (WebSocket)
[OpenAI Realtime API]
    ↓ (Response)
[OpenAI Realtime Client]
    ↓ (TTS Platform)
[Home Assistant]
    ↓
User Audio Output
```

### Key Components

#### 1. `realtime_client.py` - WebSocket Client

Manages bidirectional WebSocket communication with OpenAI:
- Connects to `wss://api.openai.com/v1/realtime`
- Sends audio chunks in base64-encoded PCM16 format
- Receives audio deltas and transcription deltas
- Handles conversation interruption via VAD events
- Manages session configuration

**Key Methods:**
- `connect()` - Establish WebSocket connection
- `send_audio()` - Stream audio to OpenAI
- `cancel_response()` - Interrupt AI response
- `_handle_message()` - Process incoming events

#### 2. `stt.py` - Speech-to-Text Platform

Implements Home Assistant's STT provider interface:
- Receives audio stream from HA
- Sends to OpenAI via WebSocket
- Collects transcript deltas
- Returns final transcription

#### 3. `tts.py` - Text-to-Speech Platform

Implements Home Assistant's TTS provider interface:
- Receives text from HA
- Sends to OpenAI via WebSocket
- Collects audio deltas
- Converts to WAV format
- Returns audio file

#### 4. `config_flow.py` - Configuration

Provides UI for:
- Initial setup (API key)
- Options (model, voice, instructions)
- Input validation

## OpenAI Realtime API Events

### Client → Server Events

| Event Type | Purpose |
|------------|---------|
| `session.update` | Configure session settings |
| `input_audio_buffer.append` | Send audio chunk |
| `input_audio_buffer.commit` | Finalize audio input |
| `input_audio_buffer.clear` | Clear audio buffer |
| `conversation.item.create` | Add text message |
| `response.create` | Request AI response |
| `response.cancel` | Stop current response |

### Server → Client Events

| Event Type | Purpose |
|------------|---------|
| `session.created` | Session established |
| `session.updated` | Settings applied |
| `response.audio.delta` | Audio chunk received |
| `response.audio_transcript.delta` | Transcript chunk |
| `response.done` | Response complete |
| `input_audio_buffer.speech_started` | User started speaking |
| `input_audio_buffer.speech_stopped` | User stopped speaking |
| `error` | Error occurred |

## Audio Processing

### Format Specifications

- **Format**: PCM16 (16-bit signed PCM)
- **Sample Rate**: 24,000 Hz
- **Channels**: Mono (1 channel)
- **Encoding**: Base64 for transmission

### Conversation Interruption

When user starts speaking:
1. `input_audio_buffer.speech_started` event received
2. Client sends `response.cancel` event
3. Client sends `input_audio_buffer.clear` event
4. AI stops speaking immediately
5. New user audio is processed

## Development Workflow

### Local Testing

1. Set up Home Assistant development environment:
   ```bash
   # Clone HA core
   git clone https://github.com/home-assistant/core.git
   cd core
   
   # Create virtual environment
   python -m venv venv
   source venv/bin/activate
   
   # Install in dev mode
   pip install -e .
   ```

2. Link your custom component:
   ```bash
   ln -s /path/to/home-assistant-openai/custom_components/openai_realtime \
         config/custom_components/openai_realtime
   ```

3. Enable debug logging in `configuration.yaml`:
   ```yaml
   logger:
     default: info
     logs:
       custom_components.openai_realtime: debug
   ```

4. Start Home Assistant:
   ```bash
   hass -c config
   ```

### Testing Checklist

- [ ] Integration loads without errors
- [ ] Configuration flow completes successfully
- [ ] Options flow saves settings
- [ ] STT platform registers correctly
- [ ] TTS platform registers correctly
- [ ] WebSocket connects to OpenAI
- [ ] Audio streaming works
- [ ] Transcription is accurate
- [ ] Speech synthesis works
- [ ] Conversation interruption functions
- [ ] No memory leaks (long running sessions)
- [ ] Error handling for network issues
- [ ] Error handling for API errors

## API Reference

### OpenAI Realtime Client

```python
client = OpenAIRealtimeClient(hass, config_entry)

# Connect to API
await client.connect()

# Send audio
await client.send_audio(audio_bytes)

# Commit audio buffer
await client.commit_audio()

# Cancel response
await client.cancel_response()

# Set callbacks
client.set_audio_callback(lambda audio: handle_audio(audio))
client.set_transcript_callback(lambda text: handle_text(text))
client.set_response_done_callback(lambda: handle_done())

# Disconnect
await client.disconnect()
```

## Common Issues

### WebSocket Connection Fails

**Cause**: Invalid API key or network issues
**Solution**: Verify API key, check network, enable debug logging

### High Latency

**Cause**: Slow internet or server issues
**Solution**: Check connection speed, verify server status

### Audio Quality Issues

**Cause**: Wrong audio format or sample rate
**Solution**: Ensure PCM16 at 24kHz, check input device

### Memory Leaks

**Cause**: Callbacks not cleared, buffers not freed
**Solution**: Properly disconnect client, clear callbacks

## Performance Optimization

### Reducing Latency

1. **Use VAD**: Let server-side VAD detect speech
2. **Stream Audio**: Don't wait for full audio buffer
3. **Reuse Connections**: Keep WebSocket alive between requests
4. **Optimize Buffer Size**: Balance between latency and stability

### Reducing Costs

1. **Monitor Usage**: Track API consumption
2. **Set Timeouts**: Avoid long-running sessions
4. **Limit Max Tokens**: Set reasonable response lengths

## Future Enhancements

Potential features to add:

- [ ] Function calling support (Home Assistant device control)
- [ ] Multi-turn conversations with context
- [ ] Voice customization parameters
- [ ] Audio preprocessing (noise reduction)
- [ ] Offline fallback mode
- [ ] Multiple language models
- [ ] Custom wake word support
- [ ] Conversation history management
- [ ] Analytics and usage tracking

## Resources

- [OpenAI Realtime API Docs](https://platform.openai.com/docs/guides/realtime)
- [Home Assistant Developer Docs](https://developers.home-assistant.io/)
- [WebSocket Protocol](https://websockets.readthedocs.io/)
- [Audio Processing in Python](https://python-sounddevice.readthedocs.io/)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Support

- GitHub Issues: Report bugs and request features
- Home Assistant Community: Get help from the community
- Discord: Join Home Assistant development discussions
