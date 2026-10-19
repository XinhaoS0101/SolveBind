from __future__ import annotations

import html as html_escape
import json
import random
import re
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple


from web.captcha.base import CaptchaResult
from web.captcha.logic_arithmetic_captcha import LogicArithmeticCaptcha


_NOISE_SVG = (
    "%3Csvg xmlns='http://www.w3.org/2000/svg' width='100' height='100'%3E"
    "%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' "
    "baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E"
    "%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.11'/%3E"
    "%3C/svg%3E"
)

_LOGIC_STYLES = f"""
<style>
.logic-block {{ margin-bottom: 8px; }}
.logic-prompt {{
  font-size: 15px; color: #374151; font-weight: 600; margin: 0 0 12px; line-height: 1.55;
  padding: 10px 12px; background: #f3f4f6; border-radius: 10px; border: 1px solid #e5e7eb;
}}
.logic-hint {{ font-size: 13px; color: #9ca3af; margin: 0 0 8px; }}
.logic-sub {{ font-size: 13px; color: #6b7280; margin-top: 8px; }}
.logic-rotate-wrap {{ display: flex; align-items: center; justify-content: center; gap: 16px; }}
.logic-arrow {{
  width: 44px; height: 44px; border-radius: 50%; border: 2px solid #e5e7eb;
  background: #f9fafb; font-size: 20px; cursor: pointer; color: #4b5563;
}}
.logic-arrow:hover {{ border-color: #4f46e5; color: #4f46e5; }}
.logic-rotate-ring {{
  width: 120px; height: 120px; border-radius: 50%; border: 2px solid #d1d5db;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(180deg,#f3f4f6,#e5e7eb);
  transform-origin: center center;
}}
.logic-rotate-char {{
  font-size: 42px; font-weight: 800; color: #6b7280; display: inline-block;
  transform-origin: center center;
}}
.logic-visual .logic-letter-grid {{
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px;
  background: #f3f4f6; padding: 16px; border-radius: 12px; min-height: 140px;
}}
.logic-letter {{
  font-size: 28px; font-weight: 800; border: none; background: transparent; cursor: pointer;
  padding: 12px; border-radius: 8px; transition: background .15s;
  transform-origin: center center;
  text-shadow: 1px 2px 0 rgba(0,0,0,0.12);
}}
.logic-letter:hover {{ background: rgba(79,70,229,0.08); }}
.logic-letter.picked {{ outline: 2px solid #4f46e5; background: rgba(79,70,229,0.12); }}
.logic-ref-row {{
  display: flex; align-items: center; gap: 14px; margin-bottom: 14px;
  padding: 14px 16px; background: linear-gradient(180deg,#f9fafb,#f3f4f6);
  border-radius: 12px; border: 1px solid #e5e7eb;
}}
.logic-ref-label {{ font-size: 13px; color: #6b7280; font-weight: 600; }}
.logic-ref-digit {{
  font-size: 40px; font-weight: 900; line-height: 1; display: inline-block;
  transform-origin: center center;
  letter-spacing: 0;
}}
.logic-scene-wrap {{
  position: relative; border-radius: 14px; overflow: hidden;
  border: 1px solid #c4c4cc; box-shadow: inset 0 1px 0 rgba(255,255,255,0.45), 0 4px 14px rgba(0,0,0,0.06);
}}
.logic-scene {{
  position: relative; width: 100%; min-height: 268px;
  box-sizing: border-box;
}}
.logic-scene.bg0 {{
  background-color: #c6c6ce;
  background-image:
    linear-gradient(118deg, rgba(255,255,255,0.42) 0%, transparent 42%),
    linear-gradient(180deg, #dedee4 0%, #b8b8c2 55%, #aeaeb8 100%),
    url("data:image/svg+xml,{_NOISE_SVG}");
}}
.logic-scene.bg1 {{
  background-color: #b9c0c8;
  background-image:
    radial-gradient(ellipse 80% 50% at 30% 20%, rgba(255,255,255,0.5), transparent),
    linear-gradient(168deg, #d8dde3 0%, #a8b0ba 100%),
    repeating-linear-gradient(-12deg, transparent, transparent 6px, rgba(0,0,0,0.03) 6px, rgba(0,0,0,0.03) 7px),
    url("data:image/svg+xml,{_NOISE_SVG}");
}}
.logic-scene.bg2 {{
  background-color: #cfcfd6;
  background-image:
    linear-gradient(90deg, rgba(255,255,255,0.2) 0%, transparent 35%, rgba(0,0,0,0.05) 100%),
    linear-gradient(0deg, #e2e2e8 0%, #bdbdc6 100%),
    url("data:image/svg+xml,{_NOISE_SVG}");
}}
.logic-spot {{
  position: absolute; margin: 0; padding: 2px 6px; line-height: 1;
  font-weight: 900; border: none; background: transparent;
  transform-origin: center center;
  -webkit-tap-highlight-color: transparent;
  pointer-events: none;
  user-select: none;
  text-shadow:
    2px 3px 0 rgba(0,0,0,0.22),
    -1px -1px 0 rgba(255,255,255,0.2);
  filter: drop-shadow(1px 3px 2px rgba(0,0,0,0.18));
  transition: filter .12s;
  border-radius: 4px;
}}
.logic-scene {{ cursor: crosshair; }}
.logic-scene .logic-scene-marker {{
  position: absolute;
  width: 28px;
  height: 28px;
  margin: 0;
  padding: 0;
  border: 3px solid rgba(79, 70, 229, 0.95);
  border-radius: 50%;
  background: rgba(129, 140, 248, 0.22);
  box-shadow: 0 0 0 2px rgba(255,255,255,0.9), 0 3px 10px rgba(0,0,0,0.18);
  pointer-events: none;
  z-index: 35;
  transform: translate(-50%, -50%);
  display: none;
}}
.logic-scene .logic-scene-marker.is-on {{
  display: block;
}}
#result-modal.modal {{
  z-index: 10000 !important;
}}
.logic-ref-float {{
  position: absolute; pointer-events: none; user-select: none; font-weight: 900;
  text-shadow: 2px 3px 0 rgba(0,0,0,0.2), -1px -1px 0 rgba(255,255,255,0.15);
  filter: drop-shadow(2px 4px 3px rgba(0,0,0,0.2));
}}
.logic-ref-cap {{
  position: absolute; left: 8px; top: 8px; font-size: 11px; color: rgba(55,65,81,0.85);
  font-weight: 700; pointer-events: none; letter-spacing: 0.02em;
}}
.seq-panels {{ display: grid; grid-template-columns: 1fr 0.95fr; gap: 16px; align-items: start; }}
@media (max-width: 520px) {{ .seq-panels {{ grid-template-columns: 1fr; }} }}
.seq-ref {{ background: #f9fafb; border-radius: 12px; padding: 12px; border: 1px solid #e5e7eb; }}
.seq-ref-title {{ font-size: 12px; color: #6b7280; margin-bottom: 8px; font-weight: 600; }}
.seq-col {{ display: flex; flex-direction: column; gap: 8px; align-items: center; }}
.seq-dot span {{ font-size: 22px; }}
.seq-dot {{
  width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  border: 2px solid #a5b4fc; background: #eef2ff;
}}
.seq-picker {{ background: #1f2937; border-radius: 12px; padding: 12px 12px 10px; color: #e5e7eb; }}
.seq-canvas {{ min-height: 48px; display: flex; align-items: center; justify-content: center; }}
.seq-row {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: center; }}
.seq-icon {{ font-size: 24px; }}
.seq-join {{ opacity: 0.5; }}
.seq-nav {{ display: flex; align-items: center; justify-content: center; gap: 12px; margin-top: 12px; }}
.btn-mini {{
  width: 36px; height: 36px; border-radius: 50%; border: none; background: #374151; color: #fff;
  cursor: pointer; font-size: 14px;
}}
.btn-mini:hover {{ background: #4f46e5; }}
.logic-label {{ display: block; font-size: 13px; color: #6b7280; margin-bottom: 6px; font-weight: 500; }}
.logic-text-input {{
  width: 100%; padding: 12px 14px; border: 2px solid #e5e7eb; border-radius: 12px; font-size: 16px;
}}
.logic-text-input:focus {{ border-color: #4f46e5; outline: none; box-shadow: 0 0 0 4px rgba(79,70,229,0.1); }}
.logic-arith {{ font-size: 22px; font-weight: 700; color: #1f2937; margin-bottom: 12px; letter-spacing: 0.02em; }}
.logic-pathmatch {{ margin-top: 2px; }}
.pathmatch-prompt-box {{
  margin: 0 0 18px 0;
  padding: 14px 16px 14px 18px;
  border-radius: 12px;
  border: 1px solid #e5e7eb;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
  background:
    linear-gradient(180deg, #a5b4fc 0%, #6366f1 52%, #4f46e5 100%) left / 5px 100% no-repeat,
    linear-gradient(180deg, #fafafa 0%, #f3f4f6 100%);
}}
.logic-visual-ext > .pathmatch-prompt-box {{ margin-bottom: 14px; }}
.pathmatch-prompt-box + .pathmatch-prompt-box {{ margin-top: -4px; }}
.pathmatch-prompt-box + .logic-block {{ margin-top: 2px; }}
.pathmatch-label {{
  display: block;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  color: #4f46e5;
  margin-bottom: 10px;
}}
.pathmatch-zh {{
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: #111827;
  line-height: 1.55;
}}
.path-panels {{
  display: grid;
  grid-template-columns: 0.9fr 1.1fr;
  gap: 18px;
  align-items: start;
}}
@media (max-width: 520px) {{
  .path-panels {{ grid-template-columns: 1fr; gap: 16px; }}
}}
.path-col {{ display: flex; flex-direction: column; min-width: 0; }}
.path-col-title {{
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  margin: 0 0 8px 2px;
  letter-spacing: 0.03em;
}}
.path-ref {{
  position: relative;
  flex: 1;
  border: 2px solid #0f172a;
  border-radius: 12px;
  overflow: hidden;
  min-height: 260px;
  background: linear-gradient(180deg, #bae6fd 0%, #38bdf8 38%, #1d4ed8 72%, #172554 100%);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.35), 0 4px 14px rgba(15,23,42,0.08);
}}
.path-ref-inner {{
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 220px;
  padding: 18px 16px 40px;
  box-sizing: border-box;
}}
.path-ref-icon {{
  font-size: 4rem;
  line-height: 1;
  filter: drop-shadow(3px 5px 8px rgba(0,0,0,0.35));
}}
.path-ref-badge {{
  position: absolute;
  left: 0;
  bottom: 0;
  right: 0;
  background: #0f172a;
  color: #fff;
  font-size: 11px;
  font-weight: 800;
  padding: 8px 14px;
  letter-spacing: 0.05em;
  text-align: center;
}}
.path-game {{
  position: relative;
  flex: 1;
  border: 2px solid #9ca3af;
  border-radius: 12px;
  min-height: 260px;
  overflow: hidden;
  background-color: #6b7280;
  box-shadow: 0 4px 14px rgba(0,0,0,0.08);
  background-image:
    linear-gradient(135deg, rgba(255,255,255,0.08) 0%, transparent 40%),
    linear-gradient(180deg, #9ca3af 0%, #4b5563 45%, #374151 100%),
    repeating-linear-gradient(62deg, transparent, transparent 11px, rgba(0,0,0,0.06) 11px, rgba(0,0,0,0.06) 12px),
    url("data:image/svg+xml,{_NOISE_SVG}");
}}
.path-svg {{
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 1;
}}
.path-node {{
  position: absolute;
  transform: translate(-50%, -50%);
  width: 42px;
  height: 42px;
  border-radius: 50%;
  box-sizing: border-box;
  overflow: hidden;
  background: rgba(255,255,255,0.95);
  border: 2px solid rgba(255,255,255,0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2;
  box-shadow: 0 2px 8px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.8);
}}
.path-node-icon {{
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  max-width: 72%;
  max-height: 72%;
  font-size: 22px;
  overflow: hidden;
}}
.path-avatar {{
  position: absolute;
  transform: translate(-50%, -88%);
  font-size: 30px;
  line-height: 1;
  z-index: 6;
  filter: drop-shadow(2px 3px 3px rgba(0,0,0,0.45));
  pointer-events: none;
  transition: left 0.22s ease, top 0.22s ease;
}}
.path-game-arrow {{
  position: absolute;
  bottom: 12px;
  width: 46px;
  height: 46px;
  border-radius: 50%;
  border: 2px solid #1f2937;
  background: #fff;
  font-size: 17px;
  font-weight: 800;
  cursor: pointer;
  z-index: 10;
  color: #111827;
  box-shadow: 0 3px 10px rgba(0,0,0,0.2);
}}
.path-game-arrow:hover {{ border-color: #4f46e5; color: #4f46e5; }}
.path-game-arrow-l {{ left: 12px; }}
.path-game-arrow-r {{ right: 12px; }}
@media (max-width: 420px) {{
  .logic-rotate-wrap {{ gap: 10px; }}
  .logic-rotate-ring {{ width: 96px; height: 96px; }}
  .logic-rotate-char {{ font-size: 34px; }}
  .logic-arrow {{ width: 40px; height: 40px; }}
  .logic-visual .logic-letter-grid {{ gap: 10px; padding: 12px; min-height: 124px; }}
  .logic-letter {{ font-size: 24px; padding: 8px; }}
  .path-ref,
  .path-game {{ min-height: 220px; }}
  .path-ref-inner {{ min-height: 184px; padding: 16px 12px 38px; }}
}}
</style>
"""


_SEQUENCE_LAYOUT_FIX = """
<style>
.captcha-container .logic-seq .seq-panels {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.32fr);
  gap: 14px;
  align-items: stretch;
}
.captcha-container .logic-seq .seq-ref {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  min-height: 200px;
  padding: 14px 12px;
  box-sizing: border-box;
}
.captcha-container .logic-seq .seq-ref-title {
  margin-bottom: 10px;
  align-self: flex-start;
  width: 100%;
  text-align: center;
}
.captcha-container .logic-seq .seq-picker {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 168px;
  max-width: 100%;
  padding: 12px 10px 10px;
  box-sizing: border-box;
}
.captcha-container .logic-seq .seq-col {
  flex: 0 1 auto;
  gap: 10px;
  justify-content: center;
}
.captcha-container .logic-seq .seq-canvas {
  flex: 1 1 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 168px;
  width: 100%;
  padding: 10px 4px 8px;
  box-sizing: border-box;
}
.captcha-container .logic-seq .seq-row {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  max-width: 100%;
}
.captcha-container .logic-seq .seq-row.seq-row-arc {
  padding: 0;
  overflow: visible;
}
.captcha-container .logic-seq .seq-arc-stage {
  position: relative;
  width: 100%;
  max-width: none;
  margin: 0 auto;
  height: 150px;
}
.captcha-container .logic-seq .seq-row-arc.seq-row-seq4 .seq-arc-stage {
  height: 176px;
  max-width: min(100%, 238px);
  margin-left: auto;
  margin-right: auto;
}
.captcha-container .logic-seq .seq-arc-stage.seq-arc-compact {
  max-width: 268px;
  height: 102px;
}
.captcha-container .logic-seq .seq-arc-svg {
  position: absolute;
  left: 0;
  top: 0;
  width: 100%;
  height: 100%;
  z-index: 1;
  pointer-events: none;
  overflow: visible;
}
.captcha-container .logic-seq .seq-arc-nodes {
  position: absolute;
  left: 0;
  top: 0;
  width: 100%;
  height: 100%;
  z-index: 2;
  pointer-events: none;
}
.captcha-container .logic-seq .seq-node,
.captcha-container .logic-seq .seq-node-arc {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 50%;
  background: rgba(55, 65, 81, 0.72);
  border: 2px solid rgba(147, 197, 253, 0.55);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.14),
    0 2px 8px rgba(0,0,0,0.25);
}
.captcha-container .logic-seq .seq-node-arc {
  position: absolute;
  transform: translate(-50%, -50%);
  z-index: 2;
  pointer-events: auto;
  flex-shrink: 0;
}
.captcha-container .logic-seq .seq-row-arc .seq-icon {
  font-size: 22px;
  line-height: 1;
}
.captcha-container .logic-seq .seq-row-arc.seq-row-seq4 .seq-node,
.captcha-container .logic-seq .seq-row-arc.seq-row-seq4 .seq-node-arc {
  width: 46px;
  height: 46px;
  border-width: 2px;
}
.captcha-container .logic-seq .seq-row-arc.seq-row-seq4 .seq-icon {
  font-size: 24px;
}
.captcha-container .logic-seq .seq-arc-seg {
  filter: drop-shadow(0 1px 2px rgba(0,0,0,0.35));
  stroke-width: 3px;
}
.captcha-container .logic-seq .seq-row-arc.seq-row-seq4 .seq-arc-seg {
  stroke: rgba(186, 230, 253, 0.92);
  stroke-width: 3.1px;
}
.captcha-container .logic-seq .seq-join {
  opacity: 0.4;
  font-size: 12px;
  user-select: none;
}
.captcha-container .logic-seq .seq-join.seq-arrow {
  font-size: 22px;
  font-weight: 800;
  color: #7dd3fc;
  opacity: 0.95;
  padding: 0 8px;
  line-height: 1;
  font-family: system-ui, "Segoe UI", sans-serif;
  text-shadow: 0 1px 2px rgba(0,0,0,0.35);
}
.captcha-container .logic-seq .seq-nav {
  margin-top: 0;
  flex-shrink: 0;
  padding-top: 8px;
  border-top: 1px solid rgba(75, 85, 99, 0.45);
}
@media (max-width: 520px) {
  .captcha-container .logic-seq .seq-panels {
    grid-template-columns: 1fr;
  }
  .captcha-container .logic-seq .seq-ref,
  .captcha-container .logic-seq .seq-picker { min-height: 156px; }
  .captcha-container .logic-seq .seq-canvas { min-height: 188px; }
  .captcha-container .logic-seq .seq-arc-stage.seq-arc-compact { max-width: 240px; height: 102px; }
  .captcha-container .logic-seq .seq-row-arc.seq-row-seq4 .seq-arc-stage { height: 162px; max-width: min(100%, 220px); }
}
</style>
"""


_SEQUENCE_ROW_JS_OLD_DOT = """  function row(seq) {
    return '<div class="seq-row">' + seq.map(function(e) {
      return '<span class="seq-icon">' + e + '</span>';
    }).join('<span class="seq-join">·</span>') + '</div>';
  }"""

_SEQUENCE_ROW_JS_OLD_ARROW = """  function row(seq) {
    return '<div class="seq-row">' + seq.map(function(e) {
      return '<span class="seq-icon">' + e + '</span>';
    }).join('<span class="seq-join seq-arrow" aria-hidden="true">→</span>') + '</div>';
  }"""

_SEQUENCE_ROW_JS_NEW = """  function row(seq) {
    var n = seq.length;
    if (n === 0) return '';
    var W, H, cx, cy, R, Rx, Ry, pts, stageCls;
    var a0 = 218 * Math.PI / 180, a1 = 322 * Math.PI / 180;
    var i, u, th, k, d, lx, ly, svg, nodes, arcRowCls;
    function trimChord(a, b, nr) {
      var dx = b.x - a.x, dy = b.y - a.y, len = Math.sqrt(dx * dx + dy * dy);
      if (len < 1e-4) return { sx: a.x, sy: a.y, ex: b.x, ey: b.y };
      dx /= len; dy /= len;
      return { sx: a.x + dx * nr, sy: a.y + dy * nr, ex: b.x - dx * nr, ey: b.y - dy * nr };
    }
    function shrinkSegMid(t, frac) {
      var mx = (t.sx + t.ex) * 0.5, my = (t.sy + t.ey) * 0.5;
      var hx = (t.ex - t.sx) * 0.5 * frac, hy = (t.ey - t.sy) * 0.5 * frac;
      t.sx = mx - hx; t.sy = my - hy;
      t.ex = mx + hx; t.ey = my + hy;
    }
    arcRowCls = 'seq-row seq-row-arc';
    if (n === 4) {
      arcRowCls += ' seq-row-seq4';
      W = 400;
      H = 400;
      cx = W / 2;
      cy = H / 2;
      stageCls = 'seq-arc-stage';
      var pad = W * 0.122;
      var half = (cx - pad) * (2 / 3);
      pts = [
        { x: cx - half, y: cy - half },
        { x: cx + half, y: cy - half },
        { x: cx + half, y: cy + half },
        { x: cx - half, y: cy + half }
      ];
    } else {
      W = 220;
      H = 102;
      cx = 110;
      cy = 102;
      R = 70;
      Rx = R;
      Ry = R;
      stageCls = 'seq-arc-stage seq-arc-compact';
      pts = [];
      for (i = 0; i < n; i++) {
        u = n <= 1 ? 0.5 : i / (n - 1);
        th = a0 + u * (a1 - a0);
        pts.push({ x: cx + R * Math.cos(th), y: cy + R * Math.sin(th) });
      }
    }
    svg = '<svg class="seq-arc-svg" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" aria-hidden="true">';
    svg += '<defs>';
    svg += '<linearGradient id="seqArcLG" x1="0%" y1="0%" x2="100%" y2="0%">';
    svg += '<stop offset="0%" stop-color="rgba(125,211,252,0.35)"/><stop offset="100%" stop-color="rgba(125,211,252,0.95)"/></linearGradient>';
    svg += '<marker id="seqArcMk" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto">';
    svg += '<path d="M0,0 L10,5 L0,10 z" fill="#bae6fd"/></marker></defs>';
    for (k = 0; k < n - 1; k++) {
      if (n === 4) {
        var nodeR = W * 0.044;
        var t = trimChord(pts[k], pts[k + 1], nodeR);
        shrinkSegMid(t, 0.5);
        d = 'M ' + t.sx.toFixed(2) + ' ' + t.sy.toFixed(2);
        d += ' L ' + t.ex.toFixed(2) + ' ' + t.ey.toFixed(2);
      } else {
        d = 'M ' + pts[k].x.toFixed(2) + ' ' + pts[k].y.toFixed(2);
        d += ' A ' + R + ' ' + R + ' 0 0 1 ' + pts[k + 1].x.toFixed(2) + ' ' + pts[k + 1].y.toFixed(2);
      }
      svg += '<path class="seq-arc-seg" d="' + d + '" fill="none" stroke="url(#seqArcLG)" stroke-width="' + (n === 4 ? '3.1' : '2.6') + '" stroke-linecap="round" marker-end="url(#seqArcMk)"/>';
    }
    svg += '</svg>';
    nodes = '<div class="seq-arc-nodes">';
    for (i = 0; i < n; i++) {
      lx = (100 * pts[i].x / W).toFixed(3) + '%';
      ly = (100 * pts[i].y / H).toFixed(3) + '%';
      nodes += '<span class="seq-node seq-node-arc" style="left:' + lx + ';top:' + ly + '"><span class="seq-icon">' + seq[i] + '</span></span>';
    }
    nodes += '</div>';
    return '<div class="' + arcRowCls + '"><div class="' + stageCls + '">' + svg + nodes + '</div></div>';
  }"""

_SPATIAL_MARKER_CLEAR_ON_SUCCESS = """
(function() {
  var origFetch = window.fetch;
  if (typeof origFetch !== 'function') return;
  window.fetch = function() {
    var args = arguments;
    return origFetch.apply(this, args).then(function(response) {
      try {
        var u = args[0];
        if (typeof u === 'string' && u.indexOf('/verify') >= 0) {
          return response.clone().json().then(function(data) {
            if (data && data.success) {
              document.querySelectorAll('.logic-scene-marker').forEach(function(m) {
                m.classList.remove('is-on');
                m.style.display = 'none';
                m.style.left = '';
                m.style.top = '';
              });
            }
            return response;
          }).catch(function() { return response; });
        }
      } catch (e) {}
      return response;
    });
  };
})();
"""


def _letter_pool(exclude: str = "") -> List[str]:
    return [c for c in "ABCDEFGHJKLMNPQRSTUVWXYZ" if c not in "IO" and c != exclude]


def _spatial_free_click_script(container_selector: str, answer_prefix: str) -> str:
    sel = json.dumps(container_selector)
    pre = json.dumps(answer_prefix)
    return f"""
(function() {{
  const root = document.querySelector({sel});
  if (!root) return;
  const scene = root.querySelector('.logic-scene');
  if (!scene) return;
  let picked = '';
  const prefix = {pre};
  let marker = scene.querySelector('.logic-scene-marker');
  if (!marker) {{
    marker = document.createElement('div');
    marker.className = 'logic-scene-marker';
    marker.setAttribute('aria-hidden', 'true');
    scene.appendChild(marker);
  }}
  scene.addEventListener('click', function(ev) {{
    const rect = scene.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8) return;
    const xPct = ((ev.clientX - rect.left) / rect.width) * 100;
    const yPct = ((ev.clientY - rect.top) / rect.height) * 100;
    picked = xPct.toFixed(2) + ',' + yPct.toFixed(2);
    marker.style.left = xPct + '%';
    marker.style.top = yPct + '%';
    marker.classList.add('is-on');
  }});
  window.__logicSync = function() {{
    var el = document.getElementById('captcha-input');
    if (el) el.value = prefix + '|' + picked;
  }};
}})();
"""


def _parse_pct_point(payload: str) -> Optional[Tuple[float, float]]:
    p = (payload or "").strip()
    if not p or "," not in p:
        return None
    a, _, b = p.partition(",")
    try:
        return float(a.strip()), float(b.strip())
    except ValueError:
        return None


def _point_in_spatial_hitbox(px: float, py: float, item: Dict[str, Any]) -> bool:
    lx = float(item["left"])
    ty = float(item["top"])
    rx = float(item.get("hit_rx", 5.0))
    ry = float(item.get("hit_ry", 7.0))
    return abs(px - lx) <= rx and abs(py - ty) <= ry


def _scatter_positions(
    n: int, spreads: List[float], margin_l: float = 10.0, margin_r: float = 90.0
) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    for i in range(n):
        sp = spreads[i] if i < len(spreads) else 1.0
        min_sep = 11.0 + sp * 9.0
        for _ in range(180):
            left = random.uniform(margin_l, margin_r)
            top = random.uniform(14.0, 86.0)
            if all(abs(left - a) + abs(top - b) > min_sep * 0.55 for a, b in out):
                out.append((left, top))
                break
        else:
            out.append((margin_l + (i % 5) * 14.0, 22.0 + (i // 5) * 24.0))
    return out


_PATH_ICON_POOL: List[str] = [
    "📷",
    "🎬",
    "📁",
    "✋",
    "⚙",
    "💾",
    "🖨",
    "🌐",
    "🎵",
    "🐰",
    "⭐",
    "🚌",
    "💎",
    "🍎",
    "🏺",
    "❄️",
    "🎯",
    "📡",
    "🔋",
    "🎮",
    "📦",
    "🎪",
    "🔊",
]


def _path_zigzag_coords(n: int) -> List[Tuple[float, float]]:
    ys = [22.0, 54.0, 36.0, 66.0, 44.0, 58.0, 32.0, 50.0]
    out: List[Tuple[float, float]] = []
    for i in range(n):
        t = i / max(1, n - 1)
        x = 15.0 + t * 70.0 + random.uniform(-3.0, 3.0)
        y = ys[i % len(ys)] + random.uniform(-4.0, 4.0)
        out.append(
            (
                round(min(92.0, max(8.0, x)), 1),
                round(min(82.0, max(12.0, y)), 1),
            )
        )
    return out


_PATHGAME_REF_W_PX = 268.0
_PATHGAME_REF_H_PX = 228.0


def _path_pair_dist_px(ax: float, ay: float, bx: float, by: float) -> float:
    dx_px = (ax - bx) * 0.01 * _PATHGAME_REF_W_PX
    dy_px = (ay - by) * 0.01 * _PATHGAME_REF_H_PX
    return (dx_px * dx_px + dy_px * dy_px) ** 0.5


def _path_diameters_for_fixed_positions(
    pts: List[Tuple[float, float]],
    gap_px: float = 10.0,
    diam_min: int = 26,
    diam_max: int = 46,
) -> List[int]:
    n = len(pts)
    if n == 0:
        return []
    diam: List[float] = [float(diam_max)] * n
    dmin_f = float(diam_min)
    dmax_f = float(diam_max)
    for _ in range(400):
        changed = False
        for i in range(n):
            for j in range(i + 1, n):
                dist = _path_pair_dist_px(pts[i][0], pts[i][1], pts[j][0], pts[j][1])
                half_sum = 0.5 * (diam[i] + diam[j])
                if dist >= half_sum + gap_px:
                    continue
                target_half = max(dmin_f, dist - gap_px)
                cur = max(1e-6, half_sum)
                scale = target_half / cur
                ni = max(dmin_f, min(dmax_f, diam[i] * scale))
                nj = max(dmin_f, min(dmax_f, diam[j] * scale))
                if abs(ni - diam[i]) > 0.01 or abs(nj - diam[j]) > 0.01:
                    diam[i], diam[j] = ni, nj
                    changed = True
        if not changed:
            break
    out_i = [int(round(max(diam_min, min(diam_max, x)))) for x in diam]

    for k in range(n):
        if k % 2 == 0 and out_i[k] > diam_min + 2:
            out_i[k] -= 1
    for _ in range(120):
        bad = False
        for i in range(n):
            for j in range(i + 1, n):
                dist = _path_pair_dist_px(pts[i][0], pts[i][1], pts[j][0], pts[j][1])
                if dist < 0.5 * (out_i[i] + out_i[j]) + gap_px + 0.5:
                    bad = True
                    if out_i[i] >= out_i[j]:
                        out_i[i] = max(diam_min, out_i[i] - 1)
                    else:
                        out_i[j] = max(diam_min, out_i[j] - 1)
                    break
            if bad:
                break
        if not bad:
            break
    return out_i


def _path_jitter_diameters_random(
    pts: List[Tuple[float, float]],
    base: List[int],
    gap_px: float = 10.0,
    diam_min: int = 26,
    diam_max: int = 46,
) -> List[int]:
    n = len(base)
    if n == 0:
        return []
    d: List[int] = [
        max(diam_min, min(diam_max, int(base[i]) + random.randint(-7, 7)))
        for i in range(n)
    ]
    dmin_f = float(diam_min)
    dmax_f = float(diam_max)
    for _ in range(450):
        changed = False
        for i in range(n):
            for j in range(i + 1, n):
                dist = _path_pair_dist_px(pts[i][0], pts[i][1], pts[j][0], pts[j][1])
                half_sum = 0.5 * (d[i] + d[j])
                if dist >= half_sum + gap_px + 0.5:
                    continue
                target_half = max(dmin_f, dist - gap_px)
                cur = max(1e-6, half_sum)
                scale = target_half / cur
                ni = int(round(max(dmin_f, min(dmax_f, d[i] * scale))))
                nj = int(round(max(dmin_f, min(dmax_f, d[j] * scale))))
                if ni != d[i] or nj != d[j]:
                    d[i], d[j] = ni, nj
                    changed = True
        if not changed:
            break
    return [max(diam_min, min(diam_max, x)) for x in d]


_ROTATE_180_SYMMETRIC = frozenset("HINOSXZ")
_ROTATE_LETTER_POOL: Tuple[str, ...] = tuple(
    c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c not in _ROTATE_180_SYMMETRIC
)


def _patch_parent_logic_html(html: str) -> str:

    return html.replace(
        '<p class="logic-hint">Use the controls below to solve the challenge, then click Verify. Click Refresh for a new challenge.</p>',
        "",
    )


_PARENT_INSTRUCT_TITLES = {
    "rotate": "Rotation Alignment",
    "sequence": "Sequence Match",
    "weekday": "Weekday Reasoning",
    "arithmetic": "Arithmetic",
}

_SPATIAL_INSTRUCT_LABELS = {
    "colorref": "Color Match",
    "uprightpick": "Upright Letter",
    "sidewayspick": "Sideways Letter",
    "sizepick": "Size Comparison",
}


def _wrap_first_logic_prompt_in_path_box(html: str, kind: str) -> str:
    title = _PARENT_INSTRUCT_TITLES.get(kind)
    if not title:
        return html
    esc_t = html_escape.escape(title)
    pat = re.compile(
        r'(<div class="logic-block[^"]*">\s*)<p class="logic-prompt">([\s\S]*?)</p>',
        re.DOTALL,
    )

    def repl(m) -> str:
        prefix, inner = m.group(1), m.group(2)
        return (
            f'{prefix}<div class="pathmatch-prompt-box">\n'
            f'    <span class="pathmatch-label">{esc_t}</span>\n'
            f"    <p class=\"pathmatch-zh\">{inner}</p>\n"
            f"  </div>"
        )

    new_html, n = pat.subn(repl, html, count=1)
    return new_html if n else html


def _html_spatial_task_box(esc, kind: str, task_text: str) -> str:
    label = _SPATIAL_INSTRUCT_LABELS.get(kind, "Spatial Selection")
    return (
        f'<div class="pathmatch-prompt-box">\n'
        f'  <span class="pathmatch-label">{esc(label)}</span>\n'
        f'  <p class="pathmatch-zh">{esc(task_text)}</p>\n'
        "</div>"
    )


_KIND_BALANCED_DECK: List[str] = []
_KIND_BALANCED_LOCK = Lock()


def _pop_balanced_kind(kinds: Tuple[str, ...]) -> str:
    global _KIND_BALANCED_DECK
    with _KIND_BALANCED_LOCK:
        if not _KIND_BALANCED_DECK:
            deck = list(kinds)
            random.shuffle(deck)
            _KIND_BALANCED_DECK.extend(deck)
        return _KIND_BALANCED_DECK.pop()


class ExtendedLogicArithmeticCaptcha(LogicArithmeticCaptcha):


    KINDS = (
        "rotate",
        "sequence",


        "pathmatch",
        "colorref",
        "uprightpick",
        "sidewayspick",
        "sizepick",
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._colorref_json: str = "[]"
        self._colorref_ref_digit: str = "0"
        self._colorref_ref_hue: int = 0
        self._colorref_ref_left: float = 15.0
        self._colorref_ref_top: float = 20.0
        self._colorref_ref_rot: float = 0.0
        self._colorref_ref_scale: float = 1.0
        self._colorref_prompt: str = ""
        self._colorref_correct_idx: int = 0
        self._colorref_bg: int = 0
        self._upright_json: str = "[]"
        self._upright_prompt: str = ""
        self._upright_correct_idx: int = 0
        self._upright_bg: int = 0
        self._sideways_json: str = "[]"
        self._sideways_prompt: str = ""
        self._sideways_correct_idx: int = 0
        self._sideways_bg: int = 0
        self._size_json: str = "[]"
        self._size_prompt: str = ""
        self._size_correct_idx: int = 0
        self._size_bg: int = 0
        self._path_icons: str = "[]"
        self._path_points: str = "[]"
        self._path_node_sizes: str = "[]"
        self._path_icon_fracs: str = "[]"
        self._path_target_idx: int = 0
        self._path_start_idx: int = 0
        self._path_polyline: str = ""
        self._path_target_icon: str = ""
        self._path_prompt: str = ""

    def generate(self) -> Dict[str, Any]:
        self._challenge_kind = _pop_balanced_kind(self.KINDS)
        if self._challenge_kind == "pathmatch":
            self._gen_pathmatch()
        elif self._challenge_kind == "colorref":
            self._gen_colorref()
        elif self._challenge_kind == "uprightpick":
            self._gen_uprightpick()
        elif self._challenge_kind == "sidewayspick":
            self._gen_sidewayspick()
        elif self._challenge_kind == "sizepick":
            self._gen_sizepick()
        elif self._challenge_kind == "rotate":
            self._gen_rotate()
        elif self._challenge_kind == "sequence":
            self._gen_sequence()
        elif self._challenge_kind == "weekday":
            self._gen_weekday()
        else:
            self._gen_arithmetic()
        self._generated = True
        return {"kind": self._challenge_kind, "answer": self._answer}

    def _gen_rotate(self) -> None:
        steps = list(range(15, 360, 15))
        self._initial_rotation = random.choice(steps)
        self._rotate_label = random.choice(_ROTATE_LETTER_POOL)
        canonical_delta = (-self._initial_rotation) % 360
        self._answer = f"rotate|{canonical_delta}"

    def _spatial_answer_for_idx(self, letters_json: str, idx: int, kind: str) -> str:
        letters = json.loads(letters_json)
        target = next((x for x in letters if int(x["idx"]) == int(idx)), None)
        if not target:
            return f"{kind}|"
        return f"{kind}|{float(target['left']):.2f},{float(target['top']):.2f}"

    def _finalize_spatial_items(self, raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        spreads = [0.9 + float(r.get("scale", 1.0)) * 0.35 for r in raw]
        coords = _scatter_positions(len(raw), spreads)
        zs = list(range(len(raw)))
        random.shuffle(zs)
        for i, r in enumerate(raw):
            r.setdefault("scale", round(random.uniform(0.78, 1.22), 2))
            r.setdefault("skew_x", random.randint(-10, 10))
            r["left"], r["top"] = coords[i]
            r["z"] = zs[i]
            sc = float(r["scale"])
            rot = abs(float(r.get("rotate", 0)))
            inflate = 1.0 + min(rot, 90.0) / 90.0 * 0.4
            r["hit_rx"] = round((2.9 * sc + 2.3) * inflate, 2)
            r["hit_ry"] = round((4.1 * sc + 2.9) * inflate, 2)
        return raw

    def _gen_pathmatch(self) -> None:
        n = random.randint(5, 7)
        icons = random.sample(_PATH_ICON_POOL, n)
        target_idx = random.randrange(n)
        others = [i for i in range(n) if i != target_idx]
        start_idx = random.choice(others)
        pts = _path_zigzag_coords(n)
        base_sz = _path_diameters_for_fixed_positions(pts)
        sizes_px = _path_jitter_diameters_random(pts, base_sz)
        icon_fracs = [round(random.uniform(0.32, 0.50), 3) for _ in range(n)]
        self._path_icons = json.dumps(icons, ensure_ascii=False)
        self._path_points = json.dumps(
            [{"x": p[0], "y": p[1]} for p in pts], ensure_ascii=False
        )
        self._path_node_sizes = json.dumps(sizes_px, ensure_ascii=True)
        self._path_icon_fracs = json.dumps(icon_fracs, ensure_ascii=True)
        self._path_target_idx = target_idx
        self._path_start_idx = start_idx
        self._path_polyline = " ".join(f"{p[0]},{p[1]}" for p in pts)
        self._path_target_icon = icons[target_idx]
        self._path_prompt = (
            "Use the two round arrow buttons below to move the character along the white path until it stops on the node matching the target icon on the left, then click Verify."
        )
        self._answer = f"pathmatch|{self._path_target_idx}"

    def _gen_colorref(self) -> None:
        ref_digit = random.choice("23456789")
        target = random.choice(_letter_pool())
        ref_hue = random.randint(0, 359)
        wrong_hue = (ref_hue + random.randint(70, 290)) % 360
        n = random.choice([7, 8, 9])
        idx_correct = random.randrange(n)
        idx_wrong_same = random.choice([i for i in range(n) if i != idx_correct])
        pool = _letter_pool(target)
        random.shuffle(pool)
        pi = 0
        letters: List[Dict[str, Any]] = []
        for i in range(n):
            if i == idx_correct:
                letters.append(
                    {
                        "letter": target,
                        "rotate": random.choice([-26, -14, 0, 10, 20, 32]),
                        "idx": i,
                        "hue": ref_hue,
                    }
                )
            elif i == idx_wrong_same:
                letters.append(
                    {
                        "letter": target,
                        "rotate": random.choice([-32, 18, -20, 24]),
                        "idx": i,
                        "hue": wrong_hue,
                    }
                )
            else:
                ch = pool[pi]
                pi += 1
                letters.append(
                    {
                        "letter": ch,
                        "rotate": random.choice([-38, -22, 14, 28, -12, 35]),
                        "idx": i,
                        "hue": random.randint(0, 359),
                    }
                )
        random.shuffle(letters)
        self._finalize_spatial_items(letters)
        self._colorref_json = json.dumps(letters, ensure_ascii=False)
        self._colorref_ref_digit = ref_digit
        self._colorref_ref_hue = ref_hue
        self._colorref_bg = random.randint(0, 2)
        ref_spreads = [1.35]
        letter_spreads = [0.9 + float(x.get("scale", 1.0)) * 0.35 for x in letters]
        ref_coord = _scatter_positions(1, ref_spreads)[0]
        for _ in range(80):
            rl, rt = ref_coord
            if all(
                abs(rl - float(x["left"])) + abs(rt - float(x["top"])) > 20.0
                for x in letters
            ):
                break
            ref_coord = _scatter_positions(1, ref_spreads)[0]
        self._colorref_ref_left, self._colorref_ref_top = ref_coord
        self._colorref_ref_rot = random.choice([-18, -8, 0, 8, 15])
        self._colorref_ref_scale = round(random.uniform(0.95, 1.35), 2)
        templates = [
            f"Look at the color of the reference digit {ref_digit}, then click in the gray scene so the round marker lands on the uppercase {target} with the same color.",
            f"Match the hue of the digit {ref_digit}; click in the gray scene so the center of the marker falls on the same-colored uppercase {target}.",
            f"Find the uppercase {target} that matches the color of the digit {ref_digit}, then place the marker on it and click Verify.",
        ]
        self._colorref_prompt = random.choice(templates)
        self._colorref_correct_idx = next(
            x["idx"]
            for x in letters
            if x["letter"] == target and x["hue"] == ref_hue
        )
        self._answer = self._spatial_answer_for_idx(
            self._colorref_json, self._colorref_correct_idx, "colorref"
        )

    def _gen_uprightpick(self) -> None:
        n = random.choice([7, 8])
        target = random.choice(_letter_pool())
        idx_upright = random.randrange(n)
        idx_tilted_same = random.choice([i for i in range(n) if i != idx_upright])
        pool = _letter_pool(target)
        random.shuffle(pool)
        pi = 0
        letters: List[Dict[str, Any]] = []
        for i in range(n):
            if i == idx_upright:
                letters.append(
                    {
                        "letter": target,
                        "rotate": 0,
                        "idx": i,
                        "hue": random.randint(150, 340),
                    }
                )
            elif i == idx_tilted_same:
                letters.append(
                    {
                        "letter": target,
                        "rotate": random.choice([78, 90, -90, -82, 100, -100]),
                        "idx": i,
                        "hue": random.randint(150, 340),
                    }
                )
            else:
                ch = pool[pi]
                pi += 1
                letters.append(
                    {
                        "letter": ch,
                        "rotate": random.choice(
                            [16, -16, 28, -28, 42, -42, 58, -58, 72, -72]
                        ),
                        "idx": i,
                        "hue": random.randint(30, 230),
                    }
                )
        random.shuffle(letters)
        self._finalize_spatial_items(letters)
        self._upright_json = json.dumps(letters, ensure_ascii=False)
        self._upright_bg = random.randint(0, 2)
        self._upright_prompt = random.choice(
            [
                f"Click in the gray scene so the round marker lands on the upright, non-sideways uppercase {target}.",
                f"Find the upright uppercase {target}, place the marker on its strokes, then click Verify.",
            ]
        )
        self._upright_correct_idx = next(
            x["idx"]
            for x in letters
            if x["letter"] == target and x["rotate"] == 0
        )
        self._answer = self._spatial_answer_for_idx(
            self._upright_json, self._upright_correct_idx, "uprightpick"
        )

    def _gen_sidewayspick(self) -> None:
        n = random.choice([7, 8])
        target = random.choice(_letter_pool())
        idx_side = random.randrange(n)
        idx_upright_same = random.choice([i for i in range(n) if i != idx_side])
        side_rot = random.choice([-90, 90, -84, 96])
        pool = _letter_pool(target)
        random.shuffle(pool)
        pi = 0
        letters: List[Dict[str, Any]] = []
        for i in range(n):
            if i == idx_side:
                letters.append(
                    {
                        "letter": target,
                        "rotate": side_rot,
                        "idx": i,
                        "hue": random.randint(40, 220),
                    }
                )
            elif i == idx_upright_same:
                letters.append(
                    {
                        "letter": target,
                        "rotate": random.choice([-12, 0, 8, 14]),
                        "idx": i,
                        "hue": random.randint(40, 220),
                    }
                )
            else:
                ch = pool[pi]
                pi += 1
                letters.append(
                    {
                        "letter": ch,
                        "rotate": random.choice(
                            [0, 12, -18, 22, -35, 40, -55, 68, -72]
                        ),
                        "idx": i,
                        "hue": random.randint(25, 240),
                    }
                )
        random.shuffle(letters)
        self._finalize_spatial_items(letters)
        self._sideways_json = json.dumps(letters, ensure_ascii=False)
        self._sideways_bg = random.randint(0, 2)
        self._sideways_prompt = random.choice(
            [
                f"Click in the gray scene so the round marker lands on the clearly sideways uppercase {target}.",
                f"Distinguish the upright and sideways letters, then place the marker on the sideways uppercase {target}.",
            ]
        )
        self._sideways_correct_idx = next(
            x["idx"]
            for x in letters
            if x["letter"] == target and abs(int(x["rotate"])) >= 75
        )
        self._answer = self._spatial_answer_for_idx(
            self._sideways_json, self._sideways_correct_idx, "sidewayspick"
        )

    def _gen_sizepick(self) -> None:
        target = random.choice(_letter_pool())
        want_large = random.choice([True, False])
        n = random.choice([8, 9])
        scales_three = sorted(
            [
                round(random.uniform(0.52, 0.72), 2),
                round(random.uniform(0.88, 1.08), 2),
                round(random.uniform(1.28, 1.62), 2),
            ]
        )
        idx_slots = random.sample(range(n), 3)
        correct_slot = idx_slots[2 if want_large else 0]
        pool = _letter_pool(target)
        random.shuffle(pool)
        pi = 0
        letters: List[Dict[str, Any]] = []
        scale_assign = {idx_slots[0]: scales_three[0], idx_slots[1]: scales_three[1], idx_slots[2]: scales_three[2]}
        for i in range(n):
            if i in scale_assign:
                letters.append(
                    {
                        "letter": target,
                        "rotate": random.choice([-20, -8, 0, 10, 18, 25]),
                        "idx": i,
                        "hue": random.randint(100, 300),
                        "scale": scale_assign[i],
                    }
                )
            else:
                ch = pool[pi]
                pi += 1
                letters.append(
                    {
                        "letter": ch,
                        "rotate": random.choice([-30, -15, 12, 22, -25, 35]),
                        "idx": i,
                        "hue": random.randint(35, 220),
                        "scale": round(random.uniform(0.82, 1.12), 2),
                    }
                )
        random.shuffle(letters)
        for item in letters:
            if "scale" not in item:
                item["scale"] = round(random.uniform(0.82, 1.12), 2)
        self._finalize_spatial_items(letters)
        self._size_json = json.dumps(letters, ensure_ascii=False)
        self._size_bg = random.randint(0, 2)
        if want_large:
            self._size_prompt = random.choice(
                [
                    f"Click in the gray scene so the round marker lands on the visually largest uppercase {target}.",
                    f"Several {target} letters have different sizes. Place the marker on the largest one, then click Verify.",
                ]
            )
        else:
            self._size_prompt = random.choice(
                [
                    f"Click in the gray scene so the round marker lands on the visually smallest uppercase {target}.",
                    f"Several {target} letters have different sizes. Place the marker on the smallest one, then click Verify.",
                ]
            )
        self._size_correct_idx = next(
            x["idx"]
            for x in letters
            if x["letter"] == target
            and float(x["scale"]) == (max(scales_three) if want_large else min(scales_three))
        )
        self._answer = self._spatial_answer_for_idx(
            self._size_json, self._size_correct_idx, "sizepick"
        )

    def _html_spot_buttons_fixed(self, esc, items: List[Dict[str, Any]]) -> str:
        parts = []
        for item in items:
            fs = 30.0 * float(item["scale"])
            tr = (
                f"translate(-50%,-50%) rotate({item['rotate']}deg) "
                f"skewX({item['skew_x']}deg)"
            )
            col = f"hsl({item['hue']},72%,34%)"
            parts.append(
                f"""<span class="logic-spot" role="presentation" data-idx="{item['idx']}"
      style="left:{item['left']:.2f}%;top:{item['top']:.2f}%;z-index:{item['z']};transform:{tr};font-size:{fs:.1f}px;color:{col}">{esc(item['letter'])}</span>"""
            )
        return "\n".join(parts)

    def _wrap_spatial_scene(
        self,
        bg: int,
        inner_buttons: str,
        ref_overlay: str,
        scene_extra_class: str,
    ) -> str:
        bgn = max(0, min(2, bg))
        return f"""
<div class="logic-scene-wrap">
  <div class="logic-scene bg{bgn} {scene_extra_class}">
    {ref_overlay}
    {inner_buttons}
  </div>
</div>"""

    def render_html(self) -> str:
        if not self._generated:
            self.generate()

        kind = self._challenge_kind
        esc = html_escape.escape

        if kind == "pathmatch":
            icons = json.loads(self._path_icons)
            points = json.loads(self._path_points)
            try:
                sizes = json.loads(self._path_node_sizes)
            except (json.JSONDecodeError, TypeError, AttributeError):
                sizes = []
            try:
                fracs = json.loads(self._path_icon_fracs)
            except (json.JSONDecodeError, TypeError, AttributeError):
                fracs = []
            if len(sizes) != len(icons):
                sizes = [42] * len(icons)
            if len(fracs) != len(icons):
                fracs = [0.42] * len(icons)
            nodes_lines = []
            for i, (ic, p, spx) in enumerate(zip(icons, points, sizes)):
                spx = int(spx)
                spx = max(26, min(46, spx))
                frac = float(fracs[i])
                frac = max(0.30, min(0.52, frac))

                fs = max(12, min(23, int(round(spx * frac))))
                nodes_lines.append(
                    f'<div class="path-node" data-i="{i}" '
                    f'style="left:{float(p["x"]):.1f}%;top:{float(p["y"]):.1f}%;'
                    f"width:{spx}px;height:{spx}px;\">"
                    f'<span class="path-node-icon" style="font-size:{fs}px;width:{fs}px;height:{fs}px;">'
                    f"{esc(ic)}</span></div>"
                )
            nodes_block = "\n".join(nodes_lines)
            body = f"""
<div class="logic-block logic-pathmatch">
  <div class="pathmatch-prompt-box">
    <span class="pathmatch-label">Path Match</span>
    <p class="pathmatch-zh">{esc(self._path_prompt)}</p>
  </div>
  <div class="path-panels">
    <div class="path-col">
      <div class="path-col-title">Target Icon</div>
      <div class="path-ref">
        <div class="path-ref-inner">
          <span class="path-ref-icon">{esc(self._path_target_icon)}</span>
        </div>
        <div class="path-ref-badge">Match this icon</div>
      </div>
    </div>
    <div class="path-col">
      <div class="path-col-title">Move Along Path</div>
      <div class="path-game" id="path-game-root">
        <svg class="path-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <polyline points="{esc(self._path_polyline)}" fill="none" stroke="rgba(255,255,255,0.92)"
            stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        {nodes_block}
        <div class="path-avatar" id="path-avatar" aria-hidden="true">🧑‍🚀</div>
        <button type="button" class="path-game-arrow path-game-arrow-l" id="path-arrow-l" aria-label="Move backward along path">◀</button>
        <button type="button" class="path-game-arrow path-game-arrow-r" id="path-arrow-r" aria-label="Move forward along path">▶</button>
      </div>
    </div>
  </div>
</div>"""
            pts_js = json.dumps(points, ensure_ascii=True)
            script = f"""
(function() {{
  const points = {pts_js};
  let pos = {int(self._path_start_idx)};
  const avatar = document.getElementById('path-avatar');
  function syncPos() {{
    var p = points[pos];
    avatar.style.left = p.x + '%';
    avatar.style.top = p.y + '%';
  }}
  document.getElementById('path-arrow-l').addEventListener('click', function() {{
    pos = Math.max(0, pos - 1);
    syncPos();
  }});
  document.getElementById('path-arrow-r').addEventListener('click', function() {{
    pos = Math.min(points.length - 1, pos + 1);
    syncPos();
  }});
  syncPos();
  window.__logicSync = function() {{
    document.getElementById('captcha-input').value = 'pathmatch|' + pos;
  }};
}})();
"""
            return self._finish_pathmatch_page(body, script)

        if kind == "colorref":
            letters = json.loads(self._colorref_json)
            buttons = self._html_spot_buttons_fixed(esc, letters)
            rfs = 36.0 * self._colorref_ref_scale
            ref_style = (
                f"left:{self._colorref_ref_left:.2f}%;top:{self._colorref_ref_top:.2f}%;"
                f"font-size:{rfs:.1f}px;color:hsl({self._colorref_ref_hue},78%,30%);"
                f"transform:translate(-50%,-50%) rotate({self._colorref_ref_rot}deg);"
                f"z-index:20;"
            )
            ref_overlay = f"""<div class="logic-ref-float" style="{ref_style}">{esc(self._colorref_ref_digit)}</div>"""
            scene = self._wrap_spatial_scene(
                self._colorref_bg, buttons, ref_overlay, "logic-colorref"
            )
            body = f"""
<div class="logic-block logic-visual-ext logic-colorref">
  {_html_spatial_task_box(esc, kind, self._colorref_prompt)}
  {scene}
</div>"""
            script = _spatial_free_click_script(".logic-colorref", "colorref")
            return self._finish_spatial_page(body, script)

        if kind == "uprightpick":
            letters = json.loads(self._upright_json)
            buttons = self._html_spot_buttons_fixed(esc, letters)
            scene = self._wrap_spatial_scene(
                self._upright_bg, buttons, "", "logic-upright"
            )
            body = f"""
<div class="logic-block logic-visual-ext logic-upright">
  {_html_spatial_task_box(esc, kind, self._upright_prompt)}
  {scene}
</div>"""
            script = _spatial_free_click_script(".logic-upright", "uprightpick")
            return self._finish_spatial_page(body, script)

        if kind == "sidewayspick":
            letters = json.loads(self._sideways_json)
            buttons = self._html_spot_buttons_fixed(esc, letters)
            scene = self._wrap_spatial_scene(
                self._sideways_bg, buttons, "", "logic-sideways"
            )
            body = f"""
<div class="logic-block logic-visual-ext logic-sideways">
  {_html_spatial_task_box(esc, kind, self._sideways_prompt)}
  {scene}
</div>"""
            script = _spatial_free_click_script(".logic-sideways", "sidewayspick")
            return self._finish_spatial_page(body, script)

        if kind == "sizepick":
            letters = json.loads(self._size_json)
            buttons = self._html_spot_buttons_fixed(esc, letters)
            scene = self._wrap_spatial_scene(
                self._size_bg, buttons, "", "logic-size"
            )
            body = f"""
<div class="logic-block logic-visual-ext logic-size">
  {_html_spatial_task_box(esc, kind, self._size_prompt)}
  {scene}
</div>"""
            script = _spatial_free_click_script(".logic-size", "sizepick")
            return self._finish_spatial_page(body, script)

        html = _patch_parent_logic_html(super().render_html())
        html = _wrap_first_logic_prompt_in_path_box(html, kind)
        if kind == "sequence":
            html = _SEQUENCE_LAYOUT_FIX + html
            if _SEQUENCE_ROW_JS_OLD_DOT in html:
                html = html.replace(_SEQUENCE_ROW_JS_OLD_DOT, _SEQUENCE_ROW_JS_NEW, 1)
            elif _SEQUENCE_ROW_JS_OLD_ARROW in html:
                html = html.replace(_SEQUENCE_ROW_JS_OLD_ARROW, _SEQUENCE_ROW_JS_NEW, 1)
        return _LOGIC_STYLES + html

    def _finish_pathmatch_page(self, body: str, script: str) -> str:
        return f"""{_LOGIC_STYLES}
{body}
<input type="hidden" id="captcha-input" name="captcha" value="" />
<script>
{script}
(function() {{
  const form = document.getElementById('captcha-form');
  if (form) {{
    form.addEventListener('submit', function() {{
      if (typeof window.__logicSync === 'function') window.__logicSync();
    }}, true);
  }}
}})();
</script>
"""

    def _finish_spatial_page(self, body: str, script: str) -> str:
        return f"""{_LOGIC_STYLES}
{body}
<input type="hidden" id="captcha-input" name="captcha" value="" />
<script>
{_SPATIAL_MARKER_CLEAR_ON_SUCCESS}
{script}
(function() {{
  const form = document.getElementById('captcha-form');
  if (form) {{
    form.addEventListener('submit', function() {{
      if (typeof window.__logicSync === 'function') window.__logicSync();
    }}, true);
  }}
}})();
</script>
"""

    def verify(self, user_input: Any) -> CaptchaResult:
        if not self._generated:
            return CaptchaResult(
                success=False,
                message="Captcha not generated. Please refresh.",
                expected=None,
                received=str(user_input),
            )
        raw = (user_input or "").strip()
        if "|" not in raw:
            return CaptchaResult(
                success=False,
                message="Invalid submission format.",
                expected=self._answer,
                received=raw,
            )
        kind, _, payload = raw.partition("|")
        payload = payload.strip()
        if kind == "colorref":
            return self._verify_colorref(payload)
        if kind == "uprightpick":
            return self._verify_uprightpick(payload)
        if kind == "sidewayspick":
            return self._verify_sidewayspick(payload)
        if kind == "sizepick":
            return self._verify_sizepick(payload)
        if kind == "pathmatch":
            return self._verify_pathmatch(payload)
        return super().verify(user_input)

    def _verify_spatial_marker(
        self,
        payload: str,
        letters_json: str,
        correct_idx: int,
        fail_hint: str,
    ) -> CaptchaResult:
        pt = _parse_pct_point(payload)
        if pt is None:
            return CaptchaResult(
                success=False,
                message="Please click inside the scene first so a round marker appears before verifying.",
                expected=self._answer,
                received=payload,
            )
        px, py = pt
        letters = json.loads(letters_json)
        correct = next(
            (x for x in letters if int(x["idx"]) == int(correct_idx)),
            None,
        )
        if not correct:
            return CaptchaResult(
                success=False,
                message="Challenge data is invalid. Please refresh.",
                expected=self._answer,
                received=payload,
            )
        ok = _point_in_spatial_hitbox(px, py, correct)
        return CaptchaResult(
            success=ok,
            message="Verification successful!" if ok else fail_hint,
            expected=self._answer,
            received=payload,
        )

    def _verify_pathmatch(self, payload: str) -> CaptchaResult:
        if not (payload or "").strip().isdigit():
            return CaptchaResult(
                success=False,
                message="Use the arrow buttons to move the character to the target node before verifying.",
                expected=self._answer,
                received=payload,
            )
        pos = int(payload.strip())
        ok = pos == int(self._path_target_idx)
        return CaptchaResult(
            success=ok,
            message="Verification successful!" if ok else "The character is not standing on the node matching the icon on the left.",
            expected=self._answer,
            received=payload,
        )

    def _verify_colorref(self, payload: str) -> CaptchaResult:
        return self._verify_spatial_marker(
            payload,
            self._colorref_json,
            self._colorref_correct_idx,
            "The round marker did not land on the letter matching the reference digit color.",
        )

    def _verify_uprightpick(self, payload: str) -> CaptchaResult:
        return self._verify_spatial_marker(
            payload,
            self._upright_json,
            self._upright_correct_idx,
            "The round marker did not land on the upright target letter.",
        )

    def _verify_sidewayspick(self, payload: str) -> CaptchaResult:
        return self._verify_spatial_marker(
            payload,
            self._sideways_json,
            self._sideways_correct_idx,
            "The round marker did not land on the sideways target letter.",
        )

    def _verify_sizepick(self, payload: str) -> CaptchaResult:
        return self._verify_spatial_marker(
            payload,
            self._size_json,
            self._size_correct_idx,
            "The round marker did not land on the letter with the required size.",
        )

