#!/usr/bin/env python3
"""
Garmin-style scrolling sonar playback from RSD files.

Renders a live-like waterfall echogram (depth vertical, time scrolling
horizontally) using PINGVerter raw samples and the same palette/scaling as
Garmin unit displays. Outputs MP4 video, animated GIF, or an offline HTML player.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pingverter_adapter import PREFERRED_BEAMS, parse_rsd_with_pingverter

logger = logging.getLogger(__name__)


@dataclass
class PingMeta:
    """Telemetry aligned with one sonar ping column."""

    time_s: Optional[float] = None
    depth_m: Optional[float] = None
    temp_c: Optional[float] = None
    min_range_m: Optional[float] = None
    max_range_m: Optional[float] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


@dataclass
class PlaybackChannel:
    """Decoded ping samples and metadata for one RSD channel."""

    channel_id: int
    label: str
    samples: List[np.ndarray]
    meta: List[PingMeta]
    scaled: np.ndarray  # shape (n_pings, max_samples), uint8 palette indices


def _safe_float(value) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f


def pick_playback_channel_id(sonar, channel_id: Optional[int] = None) -> int:
    """Choose the best channel for live-style playback (prefers down-looking beams)."""
    df = sonar.header_dat
    if channel_id is not None:
        return int(channel_id)

    if 'beam' in df.columns:
        for beam in PREFERRED_BEAMS:
            subset = df[df['beam'] == beam]
            if len(subset) > 0:
                return int(subset.iloc[0]['channel_id'])

    return int(df['channel_id'].dropna().iloc[0])


def _channel_label(sonar, channel_id: int) -> str:
    try:
        desc = sonar.describe_channel(channel_id)
        return desc.get('label') or f'Channel {channel_id}'
    except Exception:
        return f'Channel {channel_id}'


def load_playback_channel(
    sonar,
    channel_id: Optional[int] = None,
    max_pings: Optional[int] = None,
) -> PlaybackChannel:
    """
    Load raw uint16 samples and telemetry for one channel.

    Samples are scaled once with PINGVerter's Garmin waterfall transform so
    colors stay consistent across the entire recording.
    """
    cid = pick_playback_channel_id(sonar, channel_id)
    df = sonar.header_dat
    channel_df = df[df['channel_id'] == cid].reset_index(drop=True)
    if max_pings is not None and max_pings > 0:
        channel_df = channel_df.iloc[:max_pings].reset_index(drop=True)

    samples_by_channel = sonar.extract_raw_sample_arrays(channel_df)
    samples = samples_by_channel.get(cid, [])
    if not samples:
        raise ValueError(f'No sonar samples found for channel {cid}')

    meta: List[PingMeta] = []
    for _, row in channel_df.iterrows():
        meta.append(PingMeta(
            time_s=_safe_float(row.get('time_s')),
            depth_m=_safe_float(row.get('inst_dep_m', row.get('bottom_depth'))),
            temp_c=_safe_float(row.get('tempC', row.get('water_temp'))),
            min_range_m=_safe_float(row.get('min_range')),
            max_range_m=_safe_float(row.get('max_range')),
            lat=_safe_float(row.get('lat')),
            lon=_safe_float(row.get('lon')),
        ))

    # Trim meta if sample extraction skipped some pings.
    if len(meta) > len(samples):
        meta = meta[:len(samples)]
    elif len(samples) > len(meta):
        samples = samples[:len(meta)]

    max_len = max(len(p) for p in samples)
    raw = np.zeros((len(samples), max_len), dtype=np.uint16)
    for row_idx, ping in enumerate(samples):
        n = min(len(ping), max_len)
        raw[row_idx, :n] = ping[:n]

    scaled = sonar._scale_samples_for_waterfall(raw)

    return PlaybackChannel(
        channel_id=cid,
        label=_channel_label(sonar, cid),
        samples=samples,
        meta=meta,
        scaled=scaled,
    )


def palette_rgb(sonar) -> np.ndarray:
    """Return Garmin waterfall palette as (256, 3) RGB uint8 array."""
    pal = sonar._garmin_waterfall_palette()
    return np.array(pal, dtype=np.uint8).reshape(256, 3)


def _resize_nearest(rgb: np.ndarray, width: int, height: int) -> np.ndarray:
    """Nearest-neighbor upscale/downscale preserving sonar pixel look."""
    src_h, src_w = rgb.shape[:2]
    if src_w == width and src_h == height:
        return rgb

    y_idx = (np.arange(height) * src_h / height).astype(np.int64)
    x_idx = (np.arange(width) * src_w / width).astype(np.int64)
    y_idx = np.clip(y_idx, 0, src_h - 1)
    x_idx = np.clip(x_idx, 0, src_w - 1)
    return rgb[y_idx[:, None], x_idx[None, :], :]


def _draw_bottom_line(
    rgb: np.ndarray,
    meta: List[PingMeta],
    ping_start: int,
    ping_end: int,
) -> None:
    """Overlay a Garmin-style bottom track line on the echogram."""
    h, w = rgb.shape[:2]
    for col, ping_idx in enumerate(range(ping_start, ping_end)):
        if ping_idx >= len(meta):
            break
        pm = meta[ping_idx]
        if pm.depth_m is None or pm.min_range_m is None or pm.max_range_m is None:
            continue
        span = pm.max_range_m - pm.min_range_m
        if span <= 0:
            continue
        row = int((pm.depth_m - pm.min_range_m) / span * (h - 1))
        row = max(0, min(h - 1, row))
        for dr in (-1, 0, 1):
            r = row + dr
            if 0 <= r < h:
                rgb[r, col] = (255, 220, 60)


def _draw_hud(
    rgb: np.ndarray,
    channel: PlaybackChannel,
    ping_idx: int,
    ping_start: int,
    ping_end: int,
) -> None:
    """Draw a simple live-style telemetry bar at the top."""
    hud_h = max(28, rgb.shape[0] // 14)
    rgb[:hud_h, :, :] = (8, 12, 24)

    pm = channel.meta[ping_idx] if ping_idx < len(channel.meta) else PingMeta()
    parts = [channel.label]
    if pm.depth_m is not None:
        parts.append(f'Depth {pm.depth_m:.1f} m')
    if pm.temp_c is not None:
        parts.append(f'{pm.temp_c:.1f} °C')
    if pm.time_s is not None:
        parts.append(f'T {pm.time_s:.1f} s')
    parts.append(f'Ping {ping_idx + 1}/{len(channel.scaled)}')
    parts.append(f'Window {ping_end - ping_start}')

    text = '  |  '.join(parts)
    img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype('DejaVuSans.ttf', max(12, hud_h - 10))
    except OSError:
        font = ImageFont.load_default()
    draw.text((8, 4), text, fill=(230, 240, 255), font=font)
    rgb[:] = np.array(img)


def render_live_frame(
    channel: PlaybackChannel,
    palette: np.ndarray,
    ping_idx: int,
    window_pings: int,
    width: int,
    height: int,
    hud: bool = True,
    bottom_line: bool = True,
) -> np.ndarray:
    """
    Render one scrolling sonar frame ending at ``ping_idx``.

    Time scrolls left as new pings arrive on the right, matching typical
    Garmin live display behavior.
    """
    n_pings = channel.scaled.shape[0]
    ping_idx = max(0, min(ping_idx, n_pings - 1))
    start = max(0, ping_idx + 1 - window_pings)
    end = ping_idx + 1

    window = channel.scaled[start:end, :]
    indices = window.T  # depth x time
    rgb = palette[indices]

    plot_h = height - (32 if hud else 0)
    rgb = _resize_nearest(rgb, width, plot_h)

    if bottom_line:
        _draw_bottom_line(rgb, channel.meta, start, end)

    if hud:
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[32:, :, :] = rgb
        _draw_hud(frame, channel, ping_idx, start, end)
        return frame

    return rgb


def iter_live_frames(
    channel: PlaybackChannel,
    palette: np.ndarray,
    window_pings: int,
    width: int,
    height: int,
    step: int = 1,
    hud: bool = True,
    bottom_line: bool = True,
) -> Iterator[np.ndarray]:
    """Yield RGB frames for the full recording."""
    step = max(1, step)
    for ping_idx in range(0, len(channel.scaled), step):
        yield render_live_frame(
            channel, palette, ping_idx, window_pings, width, height, hud, bottom_line,
        )


def _ffmpeg_available() -> bool:
    return shutil.which('ffmpeg') is not None


def export_mp4(
    frames: Iterator[np.ndarray],
    output_file: Path,
    fps: float,
    width: int,
    height: int,
) -> Path:
    """Pipe raw RGB frames to ffmpeg and write H.264 MP4."""
    if not _ffmpeg_available():
        raise RuntimeError('ffmpeg is required for MP4 export (install ffmpeg and ensure it is on PATH)')

    output_file = Path(output_file)
    cmd = [
        'ffmpeg', '-y',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{width}x{height}',
        '-pix_fmt', 'rgb24',
        '-r', str(fps),
        '-i', '-',
        '-an',
        '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart',
        str(output_file),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    frame_count = 0
    try:
        for frame in frames:
            if frame.shape[0] != height or frame.shape[1] != width:
                raise ValueError(f'Frame size {frame.shape[:2]} != expected {(height, width)}')
            proc.stdin.write(frame.tobytes())
            frame_count += 1
        proc.stdin.close()
        stderr = proc.stderr.read().decode('utf-8', errors='replace') if proc.stderr else ''
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f'ffmpeg failed (exit {rc}): {stderr[-500:]}')
    except Exception:
        proc.kill()
        raise

    if frame_count == 0:
        raise ValueError('No frames rendered for video export')

    logger.info('Wrote %d frames to %s', frame_count, output_file)
    return output_file


def export_gif(
    frames: Iterator[np.ndarray],
    output_file: Path,
    fps: float,
) -> Path:
    """Write an animated GIF from RGB frames."""
    output_file = Path(output_file)
    pil_frames: List[Image.Image] = []
    for frame in frames:
        pil_frames.append(Image.fromarray(frame, mode='RGB'))

    if not pil_frames:
        raise ValueError('No frames rendered for GIF export')

    duration_ms = max(1, int(round(1000.0 / max(fps, 0.1))))
    pil_frames[0].save(
        output_file,
        save_all=True,
        append_images=pil_frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
    )
    logger.info('Wrote %d frames to %s', len(pil_frames), output_file)
    return output_file


def export_html_player(
    channel: PlaybackChannel,
    palette: np.ndarray,
    output_file: Path,
    window_pings: int = 400,
    width: int = 960,
    height: int = 540,
) -> Path:
    """
    Write a self-contained HTML canvas player with play/pause and scrubbing.

    Sample data is stored as base64-packed uint8 palette indices per ping to
    keep file size manageable for typical recordings.
    """
    output_file = Path(output_file)
    n_pings, n_samples = channel.scaled.shape

    # Pack each ping row (fixed width) for compact JSON transport.
    packed_rows = []
    for row in channel.scaled:
        packed_rows.append(base64.b64encode(row.tobytes()).decode('ascii'))

    meta_json = []
    for pm in channel.meta:
        meta_json.append({
            'time_s': pm.time_s,
            'depth_m': pm.depth_m,
            'temp_c': pm.temp_c,
            'min_range_m': pm.min_range_m,
            'max_range_m': pm.max_range_m,
            'lat': pm.lat,
            'lon': pm.lon,
        })

    palette_flat = palette.reshape(-1).tolist()
    title = output_file.stem

    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sonar Playback — {title}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #070b14;
      --panel: #111827;
      --ink: #e5eefc;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --line: #1e293b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    header {{
      padding: 20px 24px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(135deg, #0c4a6e, #1d4ed8);
    }}
    header h1 {{ margin: 0 0 6px; font-size: 22px; }}
    header p {{ margin: 0; opacity: 0.9; font-size: 14px; }}
    header p.legal {{ margin-top: 8px; font-size: 12px; opacity: 0.88; max-width: 900px; line-height: 1.35; }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 20px; }}
    canvas {{
      width: 100%;
      max-width: {width}px;
      height: auto;
      display: block;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #000;
    }}
    .controls {{
      margin-top: 16px;
      padding: 16px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      display: grid;
      gap: 12px;
    }}
    .row {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }}
    button {{
      background: var(--accent);
      color: #04101f;
      border: none;
      border-radius: 8px;
      padding: 8px 16px;
      font-weight: 700;
      cursor: pointer;
    }}
    button.secondary {{
      background: #334155;
      color: var(--ink);
    }}
    input[type="range"] {{ flex: 1; min-width: 180px; }}
    .telemetry {{
      font-family: Consolas, monospace;
      font-size: 13px;
      color: var(--muted);
    }}
    .legend {{
      margin-top: 12px;
      height: 14px;
      border-radius: 6px;
      border: 1px solid var(--line);
      background: linear-gradient(90deg,
        #000000 0%, #001448 9%, #005ca0 25%, #00b2c4 41%,
        #1eb946 56%, #e6cd2d 72%, #e64e1e 87%, #fff5d2 100%);
    }}
  </style>
</head>
<body>
  <header>
    <h1>Garmin Sonar Playback</h1>
    <p id="channel-label">{channel.label} — scrolling echogram (live-style)</p>
    <p class="legal">Disclaimer: This software is independent and is not affiliated with, endorsed by, or sponsored by Garmin. It visualizes sonar data collected from compatible devices.</p>
  </header>
  <main>
    <canvas id="sonar" width="{width}" height="{height}"></canvas>
    <div class="legend" title="Garmin-style intensity palette"></div>
    <div class="controls">
      <div class="row">
        <button id="play-btn">Play</button>
        <button id="restart-btn" class="secondary">Restart</button>
        <label>Speed <input id="speed" type="range" min="0.25" max="8" step="0.25" value="1"></label>
        <span id="speed-label">1.0×</span>
      </div>
      <div class="row">
        <input id="scrub" type="range" min="0" max="{max(0, n_pings - 1)}" value="0" style="flex:1">
        <span id="ping-label">Ping 1 / {n_pings}</span>
      </div>
      <div class="telemetry" id="telemetry">—</div>
    </div>
  </main>
  <script>
    const DATA = {{
      nPings: {n_pings},
      nSamples: {n_samples},
      windowPings: {window_pings},
      width: {width},
      height: {height},
      hudHeight: 32,
      palette: {json.dumps(palette_flat)},
      rows: {json.dumps(packed_rows)},
      meta: {json.dumps(meta_json)},
    }};

    const canvas = document.getElementById('sonar');
    const ctx = canvas.getContext('2d');
    const playBtn = document.getElementById('play-btn');
    const restartBtn = document.getElementById('restart-btn');
    const scrub = document.getElementById('scrub');
    const speedInput = document.getElementById('speed');
    const speedLabel = document.getElementById('speed-label');
    const pingLabel = document.getElementById('ping-label');
    const telemetry = document.getElementById('telemetry');

    const paletteCanvas = document.createElement('canvas');
    paletteCanvas.width = 256;
    paletteCanvas.height = 1;
    const pctx = paletteCanvas.getContext('2d');
    const img = pctx.createImageData(256, 1);
    for (let i = 0; i < 256; i++) {{
      img.data[i * 4] = DATA.palette[i * 3];
      img.data[i * 4 + 1] = DATA.palette[i * 3 + 1];
      img.data[i * 4 + 2] = DATA.palette[i * 3 + 2];
      img.data[i * 4 + 3] = 255;
    }}
    pctx.putImageData(img, 0, 0);

    function decodeRow(b64) {{
      const bin = atob(b64);
      const arr = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
      return arr;
    }}

    const rows = DATA.rows.map(decodeRow);
    let pingIdx = 0;
    let playing = false;
    let lastTs = 0;
    const baseFps = 10;

    function drawBottomLine(plotY, plotH, start, end, scaleX) {{
      ctx.strokeStyle = '#ffdc3c';
      ctx.lineWidth = 2;
      ctx.beginPath();
      let started = false;
      for (let col = 0; col < end - start; col++) {{
        const idx = start + col;
        const m = DATA.meta[idx];
        if (!m || m.depth_m == null || m.min_range_m == null || m.max_range_m == null) continue;
        const span = m.max_range_m - m.min_range_m;
        if (span <= 0) continue;
        const row = Math.round((m.depth_m - m.min_range_m) / span * (DATA.nSamples - 1));
        const y = plotY + (row / (DATA.nSamples - 1)) * plotH;
        const x = col * scaleX + scaleX * 0.5;
        if (!started) {{ ctx.moveTo(x, y); started = true; }} else {{ ctx.lineTo(x, y); }}
      }}
      if (started) ctx.stroke();
    }}

    function render() {{
      const w = DATA.width;
      const h = DATA.height;
      const hud = DATA.hudHeight;
      ctx.fillStyle = '#080c18';
      ctx.fillRect(0, 0, w, hud);
      ctx.fillStyle = '#000';
      ctx.fillRect(0, hud, w, h - hud);

      const end = pingIdx + 1;
      const start = Math.max(0, end - DATA.windowPings);
      const win = end - start;
      const plotH = h - hud;
      const scaleX = w / win;
      const scaleY = plotH / DATA.nSamples;

      for (let col = 0; col < win; col++) {{
        const row = rows[start + col];
        for (let s = 0; s < DATA.nSamples; s++) {{
          const idx = row[s] || 0;
          ctx.fillStyle = `rgb(${{DATA.palette[idx*3]}},${{DATA.palette[idx*3+1]}},${{DATA.palette[idx*3+2]}})`;
          const x = Math.floor(col * scaleX);
          const x2 = Math.floor((col + 1) * scaleX);
          const y = hud + Math.floor(s * scaleY);
          const y2 = hud + Math.floor((s + 1) * scaleY);
          ctx.fillRect(x, y, Math.max(1, x2 - x), Math.max(1, y2 - y));
        }}
      }}

      drawBottomLine(hud, plotH, start, end, scaleX);

      const m = DATA.meta[pingIdx] || {{}};
      const parts = [];
      if (m.depth_m != null) parts.push(`Depth ${{m.depth_m.toFixed(1)}} m`);
      if (m.temp_c != null) parts.push(`${{m.temp_c.toFixed(1)}} °C`);
      if (m.time_s != null) parts.push(`T ${{m.time_s.toFixed(1)}} s`);
      parts.push(`Ping ${{pingIdx + 1}}/${{DATA.nPings}}`);
      ctx.fillStyle = '#e6eefc';
      ctx.font = '14px Arial';
      ctx.fillText(parts.join('  |  '), 10, 20);
      telemetry.textContent = parts.join('  |  ');
      pingLabel.textContent = `Ping ${{pingIdx + 1}} / ${{DATA.nPings}}`;
      scrub.value = String(pingIdx);
    }}

    function tick(ts) {{
      if (!playing) return;
      if (!lastTs) lastTs = ts;
      const speed = parseFloat(speedInput.value);
      const interval = 1000 / (baseFps * speed);
      if (ts - lastTs >= interval) {{
        pingIdx = Math.min(DATA.nPings - 1, pingIdx + 1);
        render();
        lastTs = ts;
        if (pingIdx >= DATA.nPings - 1) {{
          playing = false;
          playBtn.textContent = 'Play';
        }}
      }}
      requestAnimationFrame(tick);
    }}

    playBtn.addEventListener('click', () => {{
      playing = !playing;
      playBtn.textContent = playing ? 'Pause' : 'Play';
      if (playing) {{
        if (pingIdx >= DATA.nPings - 1) pingIdx = 0;
        lastTs = 0;
        requestAnimationFrame(tick);
      }}
    }});

    restartBtn.addEventListener('click', () => {{
      pingIdx = 0;
      playing = false;
      playBtn.textContent = 'Play';
      render();
    }});

    scrub.addEventListener('input', () => {{
      pingIdx = parseInt(scrub.value, 10) || 0;
      render();
    }});

    speedInput.addEventListener('input', () => {{
      speedLabel.textContent = `${{parseFloat(speedInput.value).toFixed(2)}}×`;
    }});

    render();
  </script>
</body>
</html>
"""
    output_file.write_text(document, encoding='utf-8')
    logger.info('Wrote HTML player to %s (%d pings)', output_file, n_pings)
    return output_file


def resolve_output_format(output: Optional[Path], fmt: str) -> Tuple[Path, str]:
    """Pick output path and format (mp4, gif, html) from user args."""
    fmt = (fmt or 'auto').lower()
    if output is None:
        if fmt == 'auto':
            fmt = 'mp4' if _ffmpeg_available() else 'html'
        ext = {'mp4': '.mp4', 'gif': '.gif', 'html': '.html'}.get(fmt, '.html')
        raise ValueError(f'--output is required (suggested extension: {ext})')

    output = Path(output)
    suffix = output.suffix.lower()
    if fmt == 'auto':
        if suffix == '.mp4':
            fmt = 'mp4'
        elif suffix == '.gif':
            fmt = 'gif'
        elif suffix in ('.html', '.htm'):
            fmt = 'html'
        else:
            fmt = 'mp4' if _ffmpeg_available() else 'html'
            output = output.with_suffix({ 'mp4': '.mp4', 'gif': '.gif', 'html': '.html' }[fmt])
    return output, fmt


def generate_playback(
    input_file: Path,
    output_file: Optional[Path] = None,
    fmt: str = 'auto',
    channel_id: Optional[int] = None,
    nchunk: int = 500,
    fps: float = 10.0,
    width: int = 960,
    height: int = 540,
    window_pings: int = 400,
    frame_step: int = 1,
    max_pings: Optional[int] = None,
    hud: bool = True,
    bottom_line: bool = True,
) -> Path:
    """
    Generate sonar playback from an RSD file.

    Returns the path to the written MP4, GIF, or HTML player file.
    """
    input_file = Path(input_file)
    if not input_file.exists():
        raise FileNotFoundError(f'Input file not found: {input_file}')

    if output_file is not None:
        out_path, fmt = resolve_output_format(Path(output_file), fmt)
    else:
        if fmt == 'auto':
            fmt = 'mp4' if _ffmpeg_available() else 'html'
        ext = {'mp4': '.mp4', 'gif': '.gif', 'html': '.html'}[fmt]
        out_path = input_file.with_suffix(ext)

    meta_dir = tempfile.mkdtemp(prefix='pingverter_playback_')
    try:
        sonar = parse_rsd_with_pingverter(input_file, nchunk=nchunk, meta_dir=Path(meta_dir))
        channel = load_playback_channel(sonar, channel_id=channel_id, max_pings=max_pings)
        pal = palette_rgb(sonar)

        logger.info(
            'Playback: channel %s (%d pings, %d samples/ping)',
            channel.label, len(channel.scaled), channel.scaled.shape[1],
        )

        if fmt == 'html':
            return export_html_player(
                channel, pal, out_path,
                window_pings=window_pings, width=width, height=height,
            )

        frames = iter_live_frames(
            channel, pal, window_pings, width, height,
            step=frame_step, hud=hud, bottom_line=bottom_line,
        )

        if fmt == 'mp4':
            return export_mp4(frames, out_path, fps=fps, width=width, height=height)
        if fmt == 'gif':
            return export_gif(frames, out_path, fps=fps)

        raise ValueError(f'Unsupported format: {fmt}')
    finally:
        shutil.rmtree(meta_dir, ignore_errors=True)
