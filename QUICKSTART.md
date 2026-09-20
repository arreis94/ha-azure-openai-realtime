# Quick Start Guide

## Installation

### Option 1: HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/shiipou/home-assistant-openai`
6. Category: Integration
7. Click "Add"
8. Search for "OpenAI Realtime Voice Assistant"
9. Click "Download"
10. Restart Home Assistant

### Option 2: Manual Installation

1. Download the latest release
2. Extract the `custom_components/openai_realtime` folder
3. Copy it to your Home Assistant's `custom_components` directory
4. Restart Home Assistant

## Configuration

### Step 1: Get OpenAI API Key

1. Go to https://platform.openai.com/api-keys
2. Sign in or create an account
3. Click "Create new secret key"
4. Copy the key (save it somewhere safe!)

### Step 2: Add Integration

1. Go to Settings → Devices & Services
2. Click "+ Add Integration"
3. Search for "OpenAI Realtime Voice Assistant"
4. Paste your API key
5. Click Submit

### Step 3: Configure Voice Assistant

1. Go to Settings → Voice Assistants
2. Click on your assistant (default: "Home Assistant")
3. Under "Speech-to-text", select **OpenAI Realtime STT**
4. Under "Text-to-speech", select **OpenAI Realtime TTS**
5. Save changes

### Step 4: Test It!

1. Click the microphone icon in the top right of Home Assistant
2. Say "What's the weather like today?"
3. Listen to the AI response
4. Try interrupting by speaking again while it's responding!

## Optional: Configure Options

1. Go to Settings → Devices & Services
2. Find "OpenAI Realtime Voice Assistant"
3. Click "Configure"
4. Adjust:
   - Voice (Alloy, Echo, Shimmer)
   - Custom instructions

## Troubleshooting

### "Cannot connect to OpenAI"
- Check your API key is correct
- Verify you have internet connection
- Check OpenAI account has credits

### No audio playback
- Check Home Assistant audio settings
- Verify audio devices are configured
- Test with other TTS providers

### High latency
- Check internet connection speed
- Verify using realtime model

## Next Steps

- Set up voice satellites (ESPHome devices)
- Create automations with voice commands
- Customize system instructions
- Monitor API usage at https://platform.openai.com/usage

## Need Help?

- Check the [full README](README.md) for detailed documentation
- Open an issue on GitHub
- Visit Home Assistant Community forums

Enjoy your new voice assistant! 🎤✨
