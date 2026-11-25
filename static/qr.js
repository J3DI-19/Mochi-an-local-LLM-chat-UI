/* Tiny QR code encoder (byte mode, ECC level M, versions 1-15, auto mask). Self-written, no dependencies.
   window.QR.svg(text, {size, dark, light}) -> SVG string;  window.QR.matrix(text) -> boolean[][] */
(function () {
  'use strict';
  // EC codewords per block and block layout for level M, versions 1..15: [ecPerBlock, [g1Blocks, g1Data], [g2Blocks, g2Data]]
  const M = [null,
    [10, [1, 16]], [16, [1, 28]], [26, [1, 44]], [18, [2, 32]], [24, [2, 43]], [16, [4, 27]], [18, [4, 31]], [22, [2, 38], [2, 39]],
    [22, [3, 36], [2, 37]], [26, [4, 43], [1, 44]], [30, [1, 50], [4, 51]], [22, [6, 36], [2, 37]], [22, [8, 37], [1, 38]],
    [24, [4, 40], [5, 41]], [24, [5, 41], [5, 42]]];
  const ALIGN = [null, [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50], [6, 30, 54],
    [6, 32, 58], [6, 34, 62], [6, 26, 46, 66], [6, 26, 48, 70]];
  // GF(256) with poly 0x11d
  const EXP = new Array(512), LOG = new Array(256);
  for (let i = 0, x = 1; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 256) x ^= 0x11d; }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
  const mul = (a, b) => (a && b) ? EXP[LOG[a] + LOG[b]] : 0;
  function rsGen(n) { let g = [1]; for (let i = 0; i < n; i++) { const ng = new Array(g.length + 1).fill(0); for (let j = 0; j < g.length; j++) { ng[j] ^= g[j]; ng[j + 1] ^= mul(g[j], EXP[i]); } g = ng; } return g; }
  function rsRem(data, n) { const g = rsGen(n), r = data.concat(new Array(n).fill(0)); for (let i = 0; i < data.length; i++) { const c = r[i]; if (c) for (let j = 0; j < g.length; j++) r[i + j] ^= mul(g[j], c); } return r.slice(data.length); }
  const dataCap = v => { const e = M[v]; return e[1][0] * e[1][1] + (e[2] ? e[2][0] * e[2][1] : 0); };

  function encode(text) {
    const bytes = Array.from(new TextEncoder().encode(text));
    let v = 1; while (v <= 15 && 4 + (v < 10 ? 8 : 16) + bytes.length * 8 > dataCap(v) * 8) v++;
    if (v > 15) throw new Error('text too long for QR');
    const bits = []; const put = (val, n) => { for (let i = n - 1; i >= 0; i--) bits.push((val >>> i) & 1); };
    put(4, 4); put(bytes.length, v < 10 ? 8 : 16); bytes.forEach(b => put(b, 8));
    const cap = dataCap(v) * 8; put(0, Math.min(4, cap - bits.length)); while (bits.length % 8) bits.push(0);
    const data = []; for (let i = 0; i < bits.length; i += 8) data.push(parseInt(bits.slice(i, i + 8).join(''), 2));
    for (let p = 0; data.length < dataCap(v); p++) data.push(p % 2 ? 0x11 : 0xEC);
    // blocks + interleave
    const e = M[v], ec = e[0], blocks = []; let off = 0;
    for (const g of [e[1], e[2]]) if (g) for (let b = 0; b < g[0]; b++) { const d = data.slice(off, off + g[1]); off += g[1]; blocks.push({ d, e: rsRem(d, ec) }); }
    const out = []; const maxD = Math.max(...blocks.map(b => b.d.length));
    for (let i = 0; i < maxD; i++) for (const b of blocks) if (i < b.d.length) out.push(b.d[i]);
    for (let i = 0; i < ec; i++) for (const b of blocks) out.push(b.e[i]);
    return { v, cw: out };
  }
  function build(text) {
    const { v, cw } = encode(text), n = 17 + 4 * v;
    const m = Array.from({ length: n }, () => new Array(n).fill(false)), fn = Array.from({ length: n }, () => new Array(n).fill(false));
    const set = (x, y, d) => { m[y][x] = d; fn[y][x] = true; };
    const finder = (cx, cy) => { for (let dy = -4; dy <= 4; dy++) for (let dx = -4; dx <= 4; dx++) { const x = cx + dx, y = cy + dy; if (x < 0 || y < 0 || x >= n || y >= n) continue; const d = Math.max(Math.abs(dx), Math.abs(dy)); set(x, y, d !== 2 && d !== 4); } };
    finder(3, 3); finder(n - 4, 3); finder(3, n - 4);
    for (let i = 8; i < n - 8; i++) { set(i, 6, i % 2 === 0); set(6, i, i % 2 === 0); }
    const al = ALIGN[v];
    for (const ay of al) for (const ax of al) {
      if ((ax === 6 && ay === 6) || (ax === 6 && ay === n - 7) || (ax === n - 7 && ay === 6)) continue;
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) set(ax + dx, ay + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    }
    // reserve format + version areas
    for (let i = 0; i < 9; i++) { if (!fn[8][i]) set(i, 8, false); if (!fn[i][8]) set(8, i, false); }
    for (let i = 0; i < 8; i++) { set(n - 1 - i, 8, false); set(8, n - 1 - i, false); }
    set(8, n - 8, true); // dark module
    if (v >= 7) { let r = v; for (let i = 0; i < 12; i++) r = (r << 1) ^ ((r >>> 11) * 0x1F25); const bitsV = (v << 12) | r;
      for (let i = 0; i < 18; i++) { const b = ((bitsV >>> i) & 1) === 1, a = n - 11 + (i % 3), c = Math.floor(i / 3); set(a, c, b); set(c, a, b); } }
    // data placement (zigzag)
    const bits = []; cw.forEach(c => { for (let i = 7; i >= 0; i--) bits.push((c >>> i) & 1); });
    let k = 0;
    for (let right = n - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (let vert = 0; vert < n; vert++) for (let j = 0; j < 2; j++) {
        const x = right - j, upward = ((right + 1) & 2) === 0, y = upward ? n - 1 - vert : vert;
        if (!fn[y][x] && k < bits.length) { m[y][x] = bits[k++] === 1; }
      }
    }
    const MASKS = [(x, y) => (x + y) % 2 === 0, (x, y) => y % 2 === 0, (x) => x % 3 === 0, (x, y) => (x + y) % 3 === 0,
      (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0, (x, y) => x * y % 2 + x * y % 3 === 0,
      (x, y) => (x * y % 2 + x * y % 3) % 2 === 0, (x, y) => ((x + y) % 2 + x * y % 3) % 2 === 0];
    const fmt = (mask) => { const d = (0 << 3) | mask; /* level M = 00 */ let r = d; for (let i = 0; i < 10; i++) r = (r << 1) ^ ((r >>> 9) * 0x537); return ((d << 10) | r) ^ 0x5412; };
    const drawFmt = (g, mask) => {
      const b = fmt(mask), bit = i => ((b >>> i) & 1) === 1;
      for (let i = 0; i <= 5; i++) g[i][8] = bit(i);
      g[7][8] = bit(6); g[8][8] = bit(7); g[8][7] = bit(8);
      for (let i = 9; i < 15; i++) g[8][14 - i] = bit(i);
      for (let i = 0; i < 8; i++) g[8][n - 1 - i] = bit(i);
      for (let i = 8; i < 15; i++) g[n - 15 + i][8] = bit(i);
      g[n - 8][8] = true;
    };
    const penalty = g => {
      let p = 0;
      for (let pass = 0; pass < 2; pass++) for (let a = 0; a < n; a++) {
        let run = 1; const at = b => pass ? g[b][a] : g[a][b];
        for (let b = 1; b < n; b++) { if (at(b) === at(b - 1)) { run++; if (run === 5) p += 3; else if (run > 5) p++; } else run = 1; }
        for (let b = 0; b + 10 < n + 1; b++) {
          const s = [...Array(11)].map((_, i) => b + i < n ? at(b + i) : false).map(x => x ? 1 : 0).join('');
          if (s === '10111010000' || s === '00001011101') p += 40;
        }
      }
      for (let y = 0; y < n - 1; y++) for (let x = 0; x < n - 1; x++) { const c = g[y][x]; if (c === g[y][x + 1] && c === g[y + 1][x] && c === g[y + 1][x + 1]) p += 3; }
      let dark = 0; g.forEach(r => r.forEach(c => { if (c) dark++; }));
      p += Math.floor(Math.abs(dark * 20 - n * n * 10) / (n * n)) * 10;
      return p;
    };
    let best = null, bestP = Infinity;
    for (let mask = 0; mask < 8; mask++) {
      const g = m.map((row, y) => row.map((c, x) => fn[y][x] ? c : (MASKS[mask](x, y) ? !c : c)));
      drawFmt(g, mask); const p = penalty(g); if (p < bestP) { bestP = p; best = g; }
    }
    return best;
  }
  function svg(text, o) {
    o = o || {}; const g = build(text), n = g.length, q = 4, size = n + q * 2;
    let d = ''; g.forEach((row, y) => row.forEach((c, x) => { if (c) d += `M${x + q} ${y + q}h1v1h-1z`; }));
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" width="${o.size || 200}" height="${o.size || 200}" shape-rendering="crispEdges"><rect width="${size}" height="${size}" fill="${o.light || '#fff'}"/><path d="${d}" fill="${o.dark || '#000'}"/></svg>`;
  }
  const api = { matrix: build, svg };
  if (typeof window !== 'undefined') window.QR = api;
  if (typeof module !== 'undefined') module.exports = api;
})();
