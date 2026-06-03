    // —— Sonar echogram (zoom / pan + high-res segment fetch) ——
    const uploadId = __UPLOAD_ID_JSON__;
    const canvas = document.getElementById('echogram');
    const ctx = canvas.getContext('2d');
    const hud = document.getElementById('echoHud');
    const zoomLabel = document.getElementById('echoZoomLabel');

    let pingData = echogramPings.slice();
    let totalPings = pingData.length;
    let viewStart = 0;
    let viewEnd = pingData.length;
    let highlightIdx = -1;
    let isPanning = false;
    let panStartX = 0;
    let panStartView = [0, 0];

    function intensityColor(t) {
      const x = Math.max(0, Math.min(1, t));
      return 'rgb(' + Math.floor(20 + x * 235) + ',' + Math.floor(40 + x * 180) + ',' + Math.floor(80 + (1 - x) * 120) + ')';
    }

    function visiblePings() {
      const start = Math.max(0, Math.floor(viewStart));
      const end = Math.min(pingData.length, Math.ceil(viewEnd));
      return pingData.slice(start, end);
    }

    function updateZoomLabel() {
      const n = Math.max(1, Math.ceil(viewEnd - viewStart));
      zoomLabel.textContent = 'Showing ' + n + ' of ' + totalPings + ' pings · scroll zoom · drag pan';
    }

    function drawEchogram(hIdx) {
      highlightIdx = hIdx;
      const w = canvas.width;
      const h = canvas.height;
      ctx.fillStyle = '#0c1222';
      ctx.fillRect(0, 0, w, h);
      const slice = visiblePings();
      if (!slice.length) {
        ctx.fillStyle = '#94a3b8';
        ctx.font = '14px sans-serif';
        ctx.fillText('No ping data', 20, 40);
        return;
      }
      const depths = slice.map(p => p.depth_m).filter(d => d != null && d > 0);
      const maxDepth = depths.length ? Math.max(...depths) * 1.08 : 50;
      const maxI = Math.max(...slice.map(p => p.intensity || 0), 1);
      const n = slice.length;
      const barW = Math.max(1, (w - 4) / n);

      for (let i = 0; i < n; i++) {
        const p = slice[i];
        const x = (i + 0.5) * barW;
        const depth = p.depth_m != null && p.depth_m > 0 ? p.depth_m : maxDepth * 0.5;
        const y = (depth / maxDepth) * (h - 24) + 12;
        ctx.fillStyle = intensityColor((p.intensity || 0) / maxI);
        ctx.fillRect(x - barW / 2, y - 4, Math.max(1, barW), 8);
        const globalIdx = Math.floor(viewStart) + i;
        if (hIdx === globalIdx || hIdx === i) {
          ctx.strokeStyle = '#22d3ee';
          ctx.lineWidth = 2;
          ctx.strokeRect(x - barW / 2 - 1, y - 10, barW + 2, 20);
        }
      }
      ctx.fillStyle = 'rgba(148,163,184,0.9)';
      ctx.font = '11px sans-serif';
      ctx.fillText('0 m', 4, 14);
      ctx.fillText(maxDepth.toFixed(0) + ' m', 4, h - 8);
      updateZoomLabel();
    }

    async function ensureRangeLoaded(start, end) {
      if (!uploadId || end <= pingData.length) return;
      try {
        const res = await fetch('/api/surveys/' + encodeURIComponent(uploadId) + '/echogram?start=' + start + '&limit=' + (end - start));
        const data = await res.json();
        if (data.pings && data.pings.length) {
          totalPings = data.total_pings || totalPings;
          const merged = pingData.slice();
          data.pings.forEach((p, i) => { merged[start + i] = p; });
          pingData = merged.filter(Boolean);
        }
      } catch (e) { /* offline dashboard */ }
    }

    function pingAtCanvas(px, py) {
      const w = canvas.width;
      const h = canvas.height;
      const slice = visiblePings();
      const n = slice.length;
      if (!n) return null;
      const localIdx = Math.max(0, Math.min(n - 1, Math.floor((px / w) * n)));
      const depths = slice.map(p => p.depth_m).filter(d => d != null && d > 0);
      const maxDepth = depths.length ? Math.max(...depths) * 1.08 : 50;
      const depthFromY = ((py - 12) / (h - 24)) * maxDepth;
      const globalIdx = Math.floor(viewStart) + localIdx;
      const p = slice[localIdx];
      return {
        idx: globalIdx,
        localIdx,
        ping: Object.assign({}, p, { depth_m: Math.max(0, depthFromY) }),
      };
    }

    function zoomAt(factor, centerFrac) {
      const span = viewEnd - viewStart;
      const center = viewStart + span * centerFrac;
      let newSpan = span / factor;
      newSpan = Math.max(25, Math.min(pingData.length, newSpan));
      viewStart = center - newSpan / 2;
      viewEnd = center + newSpan / 2;
      if (viewStart < 0) { viewEnd -= viewStart; viewStart = 0; }
      if (viewEnd > pingData.length) { viewStart -= (viewEnd - pingData.length); viewEnd = pingData.length; }
      viewStart = Math.max(0, viewStart);
      ensureRangeLoaded(Math.floor(viewStart), Math.ceil(viewEnd)).then(() => drawEchogram(highlightIdx));
      drawEchogram(highlightIdx);
    }

    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const frac = ((e.clientX - rect.left) / rect.width);
      zoomAt(e.deltaY < 0 ? 1.35 : 0.72, frac);
    }, { passive: false });

    canvas.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      isPanning = true;
      panStartX = e.clientX;
      panStartView = [viewStart, viewEnd];
    });
    window.addEventListener('mouseup', () => { isPanning = false; });
    window.addEventListener('mousemove', (e) => {
      if (isPanning) {
        const rect = canvas.getBoundingClientRect();
        const span = panStartView[1] - panStartView[0];
        const delta = ((e.clientX - panStartX) / rect.width) * span;
        viewStart = panStartView[0] - delta;
        viewEnd = panStartView[1] - delta;
        if (viewStart < 0) { viewEnd -= viewStart; viewStart = 0; }
        if (viewEnd > pingData.length) { viewStart -= (viewEnd - pingData.length); viewEnd = pingData.length; }
        drawEchogram(highlightIdx);
        return;
      }
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      const hit = pingAtCanvas((e.clientX - rect.left) * scaleX, (e.clientY - rect.top) * scaleY);
      if (!hit) return;
      const p = hit.ping;
      hud.textContent = 'Ping ' + hit.idx + '/' + totalPings + ' · depth ' + (p.depth_m != null ? p.depth_m.toFixed(2) : '—') + ' m · I=' + (p.intensity != null ? Math.round(p.intensity) : '—');
      drawEchogram(hit.idx);
      if (p.lat != null && p.lon != null) setPingMarker(p.lat, p.lon);
    });

    canvas.addEventListener('click', (e) => {
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      const hit = pingAtCanvas((e.clientX - rect.left) * scaleX, (e.clientY - rect.top) * scaleY);
      if (!hit) return;
      cursorPing = Object.assign({ source: 'sonar_click' }, hit.ping, { frame: hit.ping.frame || hit.idx });
      document.getElementById('addLabelBtn').disabled = false;
      drawEchogram(hit.idx);
      if (cursorPing.lat != null) setPingMarker(cursorPing.lat, cursorPing.lon);
    });

    document.getElementById('echoZoomIn').addEventListener('click', () => zoomAt(1.5, 0.5));
    document.getElementById('echoZoomOut').addEventListener('click', () => zoomAt(0.65, 0.5));
    document.getElementById('echoReset').addEventListener('click', () => {
      viewStart = 0;
      viewEnd = pingData.length;
      drawEchogram(-1);
    });

    drawEchogram(-1);
