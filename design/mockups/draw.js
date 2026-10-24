// Window drawings from the engine's "drawing" data (here: simplified sample shapes).
window.drawWindow = function ({ w, h, leaves = 2, type = "sliding", scale = 1, dims = false, color = "#FFFFFF" }) {
  const pad = dims ? 34 : 4;
  const W = w * scale, H = h * scale;
  const f = Math.max(5, 9 * scale);
  let inner = "";
  const glass = (x, y, ww, hh) => `<rect x="${x}" y="${y}" width="${ww}" height="${hh}" fill="url(#gl)" stroke="#5B6B80" stroke-width="1"/>`;
  if (type === "sliding") {
    const lw = (W - 2 * f) / leaves;
    for (let i = 0; i < leaves; i++) {
      const x = pad + f + i * lw;
      inner += `<rect x="${x}" y="${pad + f}" width="${lw}" height="${H - 2 * f}" fill="${color}" stroke="#5B6B80"/>`;
      inner += glass(x + f * .8, pad + f * 1.8, lw - f * 1.6, H - f * 3.6);
      const ax = x + lw / 2, ay = pad + H / 2, d = i % 2 ? -1 : 1;
      inner += `<path d="M${ax - 12 * d} ${ay} h${24 * d} m${-6 * d} -5 l${6 * d} 5 l${-6 * d} 5" stroke="#1663D6" stroke-width="1.6" fill="none"/>`;
    }
  } else if (type === "casement") {
    const lw = (W - 2 * f) / leaves;
    for (let i = 0; i < leaves; i++) {
      const x = pad + f + i * lw, y = pad + f, hh = H - 2 * f;
      inner += `<rect x="${x}" y="${y}" width="${lw}" height="${hh}" fill="${color}" stroke="#5B6B80"/>`;
      inner += glass(x + f * .8, y + f * .8, lw - f * 1.6, hh - f * 1.6);
      const hinge = i % 2 === 0 ? x + lw - f : x + f;
      const tip = i % 2 === 0 ? x + f : x + lw - f;
      inner += `<path d="M${hinge} ${y + f} L${tip} ${y + hh / 2} L${hinge} ${y + hh - f}" stroke="#1663D6" stroke-width="1.3" fill="none" stroke-dasharray="5 3"/>`;
    }
  } else if (type === "shutter") {
    const box = H * .16;
    inner += `<rect x="${pad}" y="${pad}" width="${W}" height="${box}" fill="#D9DEE5" stroke="#5B6B80"/>`;
    for (let y = pad + box + 3; y < pad + H - 4; y += Math.max(4, 7 * scale)) {
      inner += `<line x1="${pad + f}" x2="${pad + W - f}" y1="${y}" y2="${y}" stroke="#9AA6B5" stroke-width="1"/>`;
    }
  }
  let dim = "";
  if (dims) {
    const y0 = pad + H + 16, x0 = pad - 16;
    dim = `<g stroke="#6A7686" stroke-width="1" fill="#6A7686" font-family="Cairo" font-size="11">
      <line x1="${pad}" x2="${pad + W}" y1="${y0}" y2="${y0}"/><line x1="${pad}" x2="${pad}" y1="${y0 - 5}" y2="${y0 + 5}"/>
      <line x1="${pad + W}" x2="${pad + W}" y1="${y0 - 5}" y2="${y0 + 5}"/>
      <text x="${pad + W / 2}" y="${y0 + 15}" text-anchor="middle" stroke="none">${dims.w}</text>
      <line x1="${x0}" x2="${x0}" y1="${pad}" y2="${pad + H}"/><line x1="${x0 - 5}" x2="${x0 + 5}" y1="${pad}" y2="${pad}"/>
      <line x1="${x0 - 5}" x2="${x0 + 5}" y1="${pad + H}" y2="${pad + H}"/>
      <text x="${x0 - 6}" y="${pad + H / 2}" text-anchor="middle" stroke="none" transform="rotate(-90 ${x0 - 6} ${pad + H / 2})">${dims.h}</text></g>`;
  }
  return `<svg viewBox="0 0 ${W + pad * 2} ${H + pad * 2 + (dims ? 10 : 0)}" width="${W + pad * 2}" height="${H + pad * 2 + (dims ? 10 : 0)}" direction="ltr">
    <defs><linearGradient id="gl" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#DCEFFC"/><stop offset=".55" stop-color="#C3E2F7"/><stop offset="1" stop-color="#E8F5FD"/></linearGradient></defs>
    <rect x="${pad}" y="${pad}" width="${W}" height="${H}" fill="${color}" stroke="#334155" stroke-width="1.5"/>${inner}${dim}</svg>`;
};
document.querySelectorAll("[data-win]").forEach((el) => {
  el.innerHTML = drawWindow(JSON.parse(el.dataset.win));
});
