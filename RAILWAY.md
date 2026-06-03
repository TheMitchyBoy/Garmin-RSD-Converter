# Deploy on Railway

One-click-style deploy for the Garmin Sonar web app using Railway's Docker builder.

## Prerequisites

- [Railway account](https://railway.app/)
- GitHub repo connected to Railway (this project)
- **Hobby or Pro plan** recommended — the app needs always-on service and ~2 GB RAM for PINGVerter/numpy

## Quick deploy

1. **New Project** → **Deploy from GitHub repo** → select `Garmin-RSD-Converter`
2. Railway detects `railway.toml` and builds from `Dockerfile` **or** Railpack (Python)
3. Start command (if prompted):  
   `python sonar_upload_server.py --host 0.0.0.0 --port $PORT`  
   Or use the auto-detected `main.py` entry point.
4. After the first deploy, open **Settings → Networking → Generate Domain**
5. Visit the URL — you should see the sonar web app home page

Health check: `GET /api/health` → `{"status":"ok","service":"sonar-web"}`

## Required: persistent volume

Without a volume, uploaded RSD files and session outputs are **lost on every redeploy**.

1. In your Railway service, click **Volumes**
2. **Add Volume**
3. Mount path: **`/data`**
4. Redeploy

This matches `SONAR_DATA_DIR=/data` in the Dockerfile.

## Recommended service settings

| Setting | Value | Why |
|---------|-------|-----|
| **Memory** | 2 GB (4 GB for large surveys) | numpy/pandas + RSD decode |
| **Volume mount** | `/data` | Persist uploads & outputs |
| **Health check** | `/api/health` | Set automatically via `railway.toml` |

## Environment variables (optional)

Set these under **Variables** in the Railway dashboard:

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | *(set by Railway)* | Do not override — Railway assigns the public port |
| `SONAR_DATA_DIR` | `/data` | Session storage (use with volume) |
| `SONAR_MAX_UPLOAD_BYTES` | `2147483648` | Max upload size (2 GB). Lower if needed. |
| `SONAR_HOST` | `0.0.0.0` | Bind address inside container |

## What works on Railway

| Feature | Notes |
|---------|--------|
| Sonar playback (HTML) | ✅ No ffmpeg needed |
| Convert to CSV | ✅ |
| Full pipeline | ✅ May take several minutes on large RSD files |
| MP4 export via web | ❌ ffmpeg not in container — use CLI locally if needed |

## Custom domain

1. **Settings → Networking → Custom Domain**
2. Add your domain and follow Railway's DNS instructions (CNAME)

No nginx required — Railway terminates HTTPS and proxies to the container `PORT`.

## Local test (same as Railway)

```bash
docker build -t sonar-web .
docker run --rm -p 8080:8080 -e PORT=8080 -v sonar-data:/data sonar-web
# → http://localhost:8080/
```

## Troubleshooting

**Build uses Railpack instead of Docker / “could not detect start command”**  
Set the start command in Railway **Settings → Deploy → Start Command**:

```bash
python sonar_upload_server.py --host 0.0.0.0 --port $PORT
```

Or simply:

```bash
python main.py
```

Both read Railway's `PORT` automatically. Redeploy after saving.

**502 / health check failing**  
Check deploy logs. The app must listen on `$PORT` (handled automatically).

**Upload fails / out of memory**  
Increase Railway memory to 2–4 GB or use `--max-pings` in playback for large files.

**Files missing after redeploy**  
Attach a volume at `/data` (see above).

**Request timeout on large RSD**  
Railway proxy timeout may cut off very long jobs. For huge recordings, run conversion locally via CLI and use the web app for playback/smaller files.

## Deploy button (optional)

Add to your GitHub README after linking the repo to Railway:

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/new?template=https://github.com/TheMitchyBoy/Garmin-RSD-Converter)

*(Replace the GitHub URL with your fork if needed.)*
