# Standalone Kokoro Voice Studio

This is the small VPS profile. It includes twelve English Kokoro voices, optional EQ and loudness finishing, audio upload, selectable audio filters, a persistent library, and original/WAV/MP3 downloads. There is no Piper, cloning, music, SFX, neural enhancement, or video editor in this profile. No PC worker or paid voice API is used.

The web process does not load the neural model. One isolated CPU process generates each narration and exits to release its memory. The queue accepts up to two outstanding jobs. Long scripts can be slow on a single CPU core.

## Requirements

Linux x86-64 with Docker, a hostname pointing to the server, and ports 80/443 available. The app was verified with a 384 MB container memory limit and 768 MB combined RAM/swap allowance on a 1 GB VPS with existing swap. Available memory and workload determine whether another server can support the same limits.

## Build and models

Build the image with `docker build -t voice-studio:local .`.

Create `/srv/voice-studio/data/models` and `/srv/voice-studio/data/outputs`, owned by numeric user/group `10001:10001`. Download these published model files over HTTPS:

- `https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.int8.onnx` as `data/models/kokoro.int8.onnx`
- `https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin` as `data/models/voices.bin`

Model license and voice information are maintained by [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) and the [ONNX runtime project](https://github.com/thewh1teagle/kokoro-onnx). These files are not committed to this repository.

## Private configuration

Run `python3 setup_env.py /srv/voice-studio/app.env` and choose a strong login password. This creates a private environment file with a random session secret and a PBKDF2 password hash. The login username is `admin`. Never commit that generated file.

Start the app:

```sh
docker network create voice-studio-net
docker run -d --name voice-studio --restart unless-stopped \
  --memory 384m --memory-swap 768m --cpus 0.8 --pids-limit 128 \
  --read-only --tmpfs /tmp:size=64m,mode=1777,exec \
  --cap-drop ALL --security-opt no-new-privileges \
  --network voice-studio-net \
  --env-file /srv/voice-studio/app.env \
  -v /srv/voice-studio/data:/data \
  -p 127.0.0.1:7860:7860 voice-studio:local
```

The executable temporary mount is needed by phonemizer's temporary native library. The app itself runs as user 10001 and its image is read-only.

Use an HTTPS reverse proxy on the same Docker network. A Caddyfile can contain:

```caddyfile
voice.example.com {
    encode gzip
    reverse_proxy voice-studio:7860
}
```

Replace the hostname with one whose DNS points to the server. Run the official `caddy:2-alpine` image on `voice-studio-net`, publish ports 80/443, and persist its `/data` and `/config` directories. Mount the Caddyfile read-only at `/etc/caddy/Caddyfile`. The app's session cookie requires HTTPS. Keep port 7860 bound to loopback.

## Operations

- Health: `curl http://127.0.0.1:7860/health`
- Logs: `docker logs --tail 50 voice-studio`
- Resources: `docker stats --no-stream voice-studio`
- Restart: `docker restart voice-studio`

Both containers use Docker's restart policy. Audio and model files persist in the mounted data folder. Resetting or replacing a container does not remove the library. Jobs that were still running during a restart must be submitted again.

Login, audio files and APIs require an authenticated session. State-changing requests also require a session CSRF token. Audio upload is limited to 30 MB and is restricted to audio formats. No local filesystem path input is exposed.
