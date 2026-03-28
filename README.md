```text
   ░███               ░██                  ░██                              ░██ ░██
  ░██░██              ░██                  ░██                              ░██ ░██
 ░██  ░██   ░███████  ░██    ░██ ░███████  ░████████  ░██    ░██  ░██████   ░██ ░██ ░██    ░██
░█████████ ░██    ░██ ░██   ░██ ░██        ░██    ░██ ░██    ░██       ░██  ░██ ░██ ░██    ░██
░██    ░██ ░██        ░███████   ░███████  ░██    ░██ ░██    ░██  ░███████  ░██ ░██ ░██    ░██
░██    ░██ ░██    ░██ ░██   ░██        ░██ ░██    ░██ ░██   ░███ ░██   ░██  ░██ ░██ ░██   ░███
░██    ░██  ░███████  ░██    ░██ ░███████  ░██    ░██  ░█████░██  ░█████░██ ░██ ░██  ░█████░██
                                                                                           ░██
                                                                                     ░███████
```

A meeting fact-check agent.

## Run

1. Create a local env file:

   ```bash
   cp .env.example .env
   ```

2. Put your Gemini API key in `.env`:

   ```env
   GEMINI_API_KEY=your-key-here
   ```

3. Enable Google Speech-to-Text for your GCP project:

   ```bash
   gcloud services enable speech.googleapis.com --project <YOUR_PROJECT_ID>
   ```

4. Authenticate Google Cloud locally for Speech-to-Text:

   ```bash
   gcloud auth application-default login
   ```

5. Start the app:

   ```bash
   uv run python -m hackathon
   ```

## Headless Mode

This runs the app without the TUI.

```bash
uv run python -m hackathon --no-ui
```

## Device Troubleshooting

- The default output device is `BlackHole 2ch`. If your machine uses a different output, set `AUDIO_DEVICE` in `.env`.
- To list available audio devices:

  ```bash
  uv run python -m hackathon.voiceover.devices
  ```
