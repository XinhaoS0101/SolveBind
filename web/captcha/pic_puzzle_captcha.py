import base64
import io
import json
import os
import random
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw

from .base import BaseCaptcha, CaptchaType, CaptchaResult


class PicPuzzleCaptcha(BaseCaptcha):

    DEFAULT_UNSPLASH_ACCESS_KEY = ""

    def __init__(
        self,
        rows: int = 3,
        cols: int = 4,
        tile_size: int = 96,
        gap: int = 6,
        unsplash_access_key: Optional[str] = None,
        unsplash_secret_key: Optional[str] = None,
        unsplash_query: str = "nature",
        difficulty: str = "normal",
        **kwargs,
    ):
        super().__init__(CaptchaType.PUZZLE, **kwargs)

        if rows <= 1 or cols <= 1:
            raise ValueError("rows and cols must be greater than 1")
        if tile_size < 48:
            raise ValueError("tile_size should be >= 48")

        self.swap_count = 2 if difficulty == "hard" else 1
        self.difficulty = difficulty
        self.rows = rows
        self.cols = cols
        self.tile_size = tile_size
        self.gap = gap
        self.unsplash_access_key = (
            unsplash_access_key
            or os.getenv("UNSPLASH_ACCESS_KEY")
            or self.DEFAULT_UNSPLASH_ACCESS_KEY
        )
        self.unsplash_secret_key = unsplash_secret_key
        self.unsplash_query = (unsplash_query or "nature").strip()

        self.width = self.cols * self.tile_size
        self.height = self.rows * self.tile_size

        self._pieces_base64: List[str] = []
        self._shuffled_order: List[int] = []
        self._swap_pairs: List[Tuple[int, int]] = []

    @staticmethod
    def _pair_to_answer(a: int, b: int) -> str:
        left, right = sorted((int(a), int(b)))
        return f"{left}-{right}"

    def _fetch_unsplash_image(self) -> Image.Image:
        if not self.unsplash_access_key:
            return self._build_fallback_image()

        try:
            params = urllib.parse.urlencode(
                {
                    "orientation": "landscape",
                    "query": self.unsplash_query,
                    "content_filter": "high",
                }
            )
            api_url = f"https://api.unsplash.com/photos/random?{params}"
            req = Request(
                api_url,
                headers={"Authorization": f"Client-ID {self.unsplash_access_key}"},
            )
            with urlopen(req, timeout=12) as resp:
                raw = json.loads(resp.read().decode("utf-8"))

            image_url = (
                raw.get("urls", {}).get("regular")
                or raw.get("urls", {}).get("full")
                or raw.get("urls", {}).get("small")
            )
            if not image_url:
                return self._build_fallback_image()

            img_req = Request(image_url, headers={"User-Agent": "HLL/1.0"})
            with urlopen(img_req, timeout=12) as img_resp:
                data = img_resp.read()

            return Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as e:
            print(f"[PicPuzzleCaptcha] Unsplash fetch failed, use fallback image: {e}")
            return self._build_fallback_image()

    def _build_fallback_image(self) -> Image.Image:
        img = Image.new("RGB", (self.width, self.height))
        draw = ImageDraw.Draw(img)

        for y in range(self.height):
            ratio = y / max(self.height - 1, 1)
            r = int(70 + ratio * 110)
            g = int(120 + ratio * 70)
            b = int(180 - ratio * 80)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))

        for _ in range(18):
            x1 = random.randint(0, self.width - 10)
            y1 = random.randint(0, self.height - 10)
            x2 = min(self.width, x1 + random.randint(30, 120))
            y2 = min(self.height, y1 + random.randint(20, 90))
            color = (
                random.randint(120, 245),
                random.randint(120, 245),
                random.randint(120, 245),
            )
            draw.ellipse([x1, y1, x2, y2], fill=color)

        return img

    def _crop_to_ratio_and_resize(self, image: Image.Image) -> Image.Image:
        target_ratio = self.cols / self.rows
        src_w, src_h = image.size
        src_ratio = src_w / src_h if src_h else target_ratio

        if src_ratio > target_ratio:

            crop_h = src_h
            crop_w = int(round(crop_h * target_ratio))
        else:

            crop_w = src_w
            crop_h = int(round(crop_w / target_ratio))

        left = max((src_w - crop_w) // 2, 0)
        top = max((src_h - crop_h) // 2, 0)
        cropped = image.crop((left, top, left + crop_w, top + crop_h))

        return cropped.resize((self.width, self.height), Image.Resampling.LANCZOS)

    def _split_to_pieces_base64(self, image: Image.Image) -> List[str]:
        pieces: List[str] = []
        for r in range(self.rows):
            for c in range(self.cols):
                left = c * self.tile_size
                top = r * self.tile_size
                piece = image.crop(
                    (left, top, left + self.tile_size, top + self.tile_size)
                )
                buff = io.BytesIO()
                piece.save(buff, format="PNG")
                pieces.append(base64.b64encode(buff.getvalue()).decode("utf-8"))
        return pieces

    def generate(self) -> Dict[str, Any]:
        image = self._fetch_unsplash_image()
        image = self._crop_to_ratio_and_resize(image)
        self._pieces_base64 = self._split_to_pieces_base64(image)

        piece_count = self.rows * self.cols
        order = list(range(piece_count))
        self._swap_pairs = []
        for _ in range(self.swap_count):
            a, b = random.sample(range(piece_count), 2)
            order[a], order[b] = order[b], order[a]
            self._swap_pairs.append((a, b))

        self._shuffled_order = order
        self._answer = ",".join(
            self._pair_to_answer(a, b) for a, b in self._swap_pairs
        )
        self._generated = True

        return {
            "type": "pic_puzzle",
            "rows": self.rows,
            "cols": self.cols,
            "tile_size": self.tile_size,
            "gap": self.gap,
            "pieces": self._pieces_base64,
            "shuffled_order": self._shuffled_order,
        }

    def render_html(self) -> str:
        if not self._generated:
            self.generate()

        pieces_json = json.dumps(self._pieces_base64, ensure_ascii=False)
        order_json = json.dumps(self._shuffled_order, ensure_ascii=False)

        max_grid_width = self.cols * self.tile_size + (self.cols - 1) * self.gap + 16
        if self.swap_count == 1:
            instruction = "Drag one tile onto another tile, or tap two tiles on mobile"
            status_idle = "Drag to swap on desktop, or tap two tiles on mobile"
        else:
            instruction = f"Restore the image by completing {self.swap_count} swaps"
            status_idle = f"Complete {self.swap_count} swaps to restore the image"

        return f"""
        <div class="pic-puzzle-captcha" style="user-select:none;">
            <div style="text-align:center; margin-bottom: 12px; padding: 10px 12px; background: linear-gradient(135deg, #f0f9ff, #e0f2fe); border-radius: 10px; border: 1px solid #bae6fd;">
                <span style="color: #0369a1; font-weight: 600;">{instruction}</span>
            </div>

            <div id="pic-puzzle-grid" style="
                margin: 0 auto;
                width: min(100%, {max_grid_width}px);
                display: grid;
                grid-template-columns: repeat({self.cols}, minmax(0, 1fr));
                gap: {self.gap}px;
                padding: 8px;
                background: #f8fafc;
                border-radius: 12px;
                border: 1px solid #e2e8f0;
            "></div>

            <div style="text-align:center; margin-top: 10px; font-size: 13px; color:#64748b;">
                <span id="pic-puzzle-status">{status_idle}</span>
            </div>

            <input type="hidden" id="captcha-input" name="captcha" value="" />
        </div>

        <script>
        (function() {{
            const rows = {self.rows};
            const cols = {self.cols};
            const pieces = {pieces_json};
            const initialOrder = {order_json};
            const grid = document.getElementById('pic-puzzle-grid');
            const input = document.getElementById('captcha-input');
            const status = document.getElementById('pic-puzzle-status');

            let dragSource = null;
            let hoverTarget = null;
            let tapSource = null;
            const requiredSwaps = {self.swap_count};
            let completedSwaps = [];
            let suppressClickUntil = 0;

            function ensureAnimStyle() {{
                if (document.getElementById('pic-puzzle-anim-style')) return;
                const style = document.createElement('style');
                style.id = 'pic-puzzle-anim-style';
                style.textContent = `
                    @keyframes picPuzzleHoverPulse {{
                        0% {{ transform: scale(1); }}
                        50% {{ transform: scale(1.02); }}
                        100% {{ transform: scale(1); }}
                    }}
                `;
                document.head.appendChild(style);
            }}

            function pairAnswer(a, b) {{
                const x = Math.min(a, b);
                const y = Math.max(a, b);
                return `${{x}}-${{y}}`;
            }}

            function buildOrderFromSwaps(swaps) {{
                const base = initialOrder.slice();
                for (const swapPair of swaps) {{
                    const a = swapPair[0];
                    const b = swapPair[1];
                    const tmp = base[a];
                    base[a] = base[b];
                    base[b] = tmp;
                }}
                return base;
            }}

            function getCommittedOrder() {{
                return buildOrderFromSwaps(completedSwaps);
            }}

            window.__picPuzzleGetCommittedOrder = function() {{
                return getCommittedOrder().slice();
            }};

            function getRenderOrder() {{
                const committed = getCommittedOrder();
                if (dragSource === null || hoverTarget === null || dragSource === hoverTarget) {{
                    return committed;
                }}
                const preview = committed.slice();
                preview[dragSource] = committed[hoverTarget];
                return preview;
            }}

            function updateStatus() {{
                if (tapSource !== null) {{
                    status.textContent = 'Tile ' + (tapSource + 1) + ' selected. Tap another tile to swap.';
                    status.style.color = '#2563eb';
                    return;
                }}
                if (completedSwaps.length > 0) {{
                    if (completedSwaps.length >= requiredSwaps) {{
                        status.textContent = `All ${{requiredSwaps}} swaps completed. Click Verify.`;
                        status.style.color = '#059669';
                    }} else {{
                        status.textContent = `Completed ${{completedSwaps.length}}/${{requiredSwaps}} swaps. Continue restoring the image.`;
                        status.style.color = '#d97706';
                    }}
                    return;
                }}
                status.textContent = '{status_idle}';
                status.style.color = '#64748b';
            }}

            function commitSwap(a, b) {{
                if (a === null || b === null || a === b) {{
                    return;
                }}
                completedSwaps.push([a, b]);
                input.value = completedSwaps.map(([x, y]) => pairAnswer(x, y)).join(',');
            }}

            function makeTile(slotIndex, pieceIndex, isSwappedMark) {{
                const tile = document.createElement('div');
                tile.className = 'pic-puzzle-tile';
                tile.dataset.slot = String(slotIndex);
                tile.draggable = true;

                const marked = isSwappedMark ? '2px solid #10b981' : '1px solid #cbd5e1';
                tile.style.cssText = `
                    width:100%;
                    aspect-ratio:1 / 1;
                    border:${{marked}};
                    border-radius:8px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
                    background-image:url(data:image/png;base64,${{pieces[pieceIndex]}});
                    background-size:cover;
                    background-position:center;
                    cursor:grab;
                    position:relative;
                    overflow:hidden;
                    transition: transform .08s ease, border-color .15s ease;
                    touch-action: manipulation;
                `;

                const overlay = document.createElement('div');
                overlay.className = 'tile-hover-overlay';
                overlay.style.cssText = `
                    position:absolute;
                    inset:0;
                    background:rgba(255,255,255,0.35);
                    opacity:0;
                    pointer-events:none;
                    transition: opacity .18s ease;
                `;
                tile.appendChild(overlay);

                tile.addEventListener('dragstart', (e) => {{
                    dragSource = slotIndex;
                    hoverTarget = slotIndex;
                    tapSource = null;
                    suppressClickUntil = Date.now() + 400;
                    tile.style.opacity = '0.6';
                    tile.style.cursor = 'grabbing';
                    if (e.dataTransfer) {{
                        e.dataTransfer.effectAllowed = 'move';
                        e.dataTransfer.setData('text/plain', String(slotIndex));
                    }}
                }});

                tile.addEventListener('dragend', () => {{
                    dragSource = null;
                    hoverTarget = null;
                    render();
                }});

                tile.addEventListener('dragenter', (e) => {{
                    e.preventDefault();
                    if (dragSource !== null && hoverTarget !== slotIndex) {{
                        hoverTarget = slotIndex;
                        render();
                    }}
                }});

                tile.addEventListener('dragover', (e) => {{
                    e.preventDefault();
                    if (dragSource !== null && hoverTarget !== slotIndex) {{
                        hoverTarget = slotIndex;
                        render();
                    }}
                }});

                tile.addEventListener('drop', (e) => {{
                    e.preventDefault();
                    if (dragSource === null) return;
                    const target = slotIndex;

                    if (target !== dragSource) {{
                        commitSwap(dragSource, target);
                    }}

                    dragSource = null;
                    hoverTarget = null;
                    render();
                }});

                tile.addEventListener('click', () => {{
                    if (Date.now() < suppressClickUntil) return;
                    if (dragSource !== null) return;

                    if (tapSource === null) {{
                        tapSource = slotIndex;
                    }} else if (tapSource === slotIndex) {{
                        tapSource = null;
                    }} else {{
                        commitSwap(tapSource, slotIndex);
                        tapSource = null;
                    }}
                    render();
                }});

                return tile;
            }}

            function render() {{
                const renderOrder = getRenderOrder();
                grid.innerHTML = '';

                for (let i = 0; i < rows * cols; i++) {{
                    const marked = completedSwaps.some(([a, b]) => i === a || i === b);
                    const tile = makeTile(i, renderOrder[i], marked);
                    if (tapSource === i) {{
                        tile.style.borderColor = '#2563eb';
                        tile.style.boxShadow = '0 0 0 2px rgba(37,99,235,.2), 0 6px 14px rgba(0,0,0,0.14)';
                    }}
                    if (hoverTarget === i && dragSource !== null && i !== dragSource) {{
                        tile.style.borderColor = '#f59e0b';
                        tile.style.animation = 'picPuzzleHoverPulse .9s ease-in-out infinite';
                        tile.style.boxShadow = '0 0 0 2px rgba(245,158,11,.25), 0 6px 14px rgba(0,0,0,0.14)';
                        const overlay = tile.querySelector('.tile-hover-overlay');
                        if (overlay) overlay.style.opacity = '1';
                    }}
                    grid.appendChild(tile);
                }}
                updateStatus();
            }}

            ensureAnimStyle();
            render();
        }})();
        </script>
        """

    def verify(self, user_input: Any) -> CaptchaResult:
        if user_input is None:
            swap_msg = "two tiles" if self.swap_count == 1 else f"{self.swap_count} pairs of tiles"
            return CaptchaResult(
                success=False,
                message=f"Please swap {swap_msg} before verifying.",
                expected=str(self._answer),
                received="",
            )

        text = str(user_input).strip()
        if not text:
            swap_msg = "two tiles" if self.swap_count == 1 else f"{self.swap_count} pairs of tiles"
            return CaptchaResult(
                success=False,
                message=f"Please swap {swap_msg} before verifying.",
                expected=str(self._answer),
                received=text,
            )

        parsed_pairs: List[Tuple[int, int]] = []
        try:
            for part in text.split(","):
                part = part.strip()
                if "-" not in part:
                    continue
                a, b = part.split("-", 1)
                parsed_pairs.append((int(a), int(b)))
        except (TypeError, ValueError):
            parsed_pairs = []

        if not parsed_pairs:
            return CaptchaResult(
                success=False,
                message="Invalid swap index format. Expected like '2-7' or '2-7,3-9'.",
                expected=str(self._answer),
                received=text,
            )

        if len(parsed_pairs) != self.swap_count:
            swap_msg = "1 swap" if self.swap_count == 1 else f"{self.swap_count} swaps"
            return CaptchaResult(
                success=False,
                message=f"Please complete exactly {swap_msg} before verifying.",
                expected=str(self._answer),
                received=",".join(self._pair_to_answer(a, b) for a, b in parsed_pairs),
                extra={"swap_pairs": [list(pair) for pair in self._swap_pairs]},
            )

        order = self._shuffled_order[:]
        piece_count = self.rows * self.cols
        for a, b in parsed_pairs:
            if not (0 <= a < piece_count and 0 <= b < piece_count) or a == b:
                return CaptchaResult(
                    success=False,
                    message="Swap index out of range. Please try again.",
                    expected=str(self._answer),
                    received=text,
                    extra={"swap_pairs": [list(pair) for pair in self._swap_pairs]},
                )
            order[a], order[b] = order[b], order[a]

        success = order == list(range(piece_count))
        parsed = ",".join(self._pair_to_answer(a, b) for a, b in parsed_pairs)
        return CaptchaResult(
            success=success,
            message=(
                "Verification successful!"
                if success
                else "The image is not fully restored yet. Please try again."
            ),
            expected=str(self._answer),
            received=parsed,
            extra={"swap_pairs": [list(pair) for pair in self._swap_pairs]},
        )
