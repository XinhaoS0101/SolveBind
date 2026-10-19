import base64
import io
import random
from typing import Any, Dict, List

from PIL import Image, ImageDraw, ImageFont

from .base import BaseCaptcha, CaptchaType, CaptchaResult


class ClickIconCaptcha(BaseCaptcha):

    ICONS = [
        # Restrict symbols to glyphs that render reliably across supported fonts.

        "★", "☆", "☀", "☁", "☂", "☃", "☕", "☘", "☯", "☮",
        "☢", "☣", "☑", "☎", "⌛", "⌚", "⏰", "⌘", "♠", "♣",
        "♥", "♦", "♪", "♫", "⚙", "⚡", "⚑", "⚐", "✁", "✂",
        "✆", "✈", "✉", "✌", "✎", "✓", "✔", "✕", "✖", "✿",
    ]

    def __init__(
        self,
        width: int = 300,
        height: int = 200,
        icon_count: int = 6,
        click_count: int = 3,
        tolerance: int = 25,
        alpha: int = 180,
        **kwargs,
    ):
        super().__init__(CaptchaType.CLICK, **kwargs)
        self.width = width
        self.height = height
        self.icon_count = max(4, min(icon_count, len(self.ICONS)))
        self.click_count = max(1, min(click_count, self.icon_count))
        self.tolerance = tolerance
        self.alpha = max(80, min(alpha, 255))

        self._image: str = ""
        self._all_icons: List[Dict] = []
        self._target_icons: List[Dict] = []
        self._target_sequence: str = ""

    def _load_font(self) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        candidates = [
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/System/Library/Fonts/Apple Symbols.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "C:/Windows/Fonts/seguisym.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        best_font = None
        best_count = -1
        for fp in candidates:
            try:
                font = ImageFont.truetype(fp, 38)
            except Exception:
                continue
            count = len(self._renderable_icons(font))
            if count > best_count:
                best_font = font
                best_count = count
        return best_font or ImageFont.load_default()

    @staticmethod
    def _glyph_signature(font, icon: str):
        mask = font.getmask(icon)
        return font.getbbox(icon), bytes(mask)

    def _renderable_icons(self, font) -> List[str]:
        signatures: Dict[Any, List[str]] = {}
        for icon in self.ICONS:
            signature = self._glyph_signature(font, icon)
            signatures.setdefault(signature, []).append(icon)
        return [
            icons[0]
            for icons in signatures.values()
            if len(icons) == 1 and any(self._glyph_signature(font, icons[0])[1])
        ]

    def generate(self) -> Dict[str, Any]:
        img = Image.new("RGB", (self.width, self.height))
        draw = ImageDraw.Draw(img)

        for y in range(self.height):
            r = int(241 - (y / self.height) * 28)
            g = int(246 - (y / self.height) * 24)
            b = int(251 - (y / self.height) * 20)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))

        for _ in range(14):
            x1 = random.randint(0, self.width)
            y1 = random.randint(0, self.height)
            x2 = x1 + random.randint(28, 78)
            y2 = y1 + random.randint(28, 58)
            draw.ellipse(
                [x1, y1, x2, y2],
                fill=(
                    random.randint(202, 240),
                    random.randint(210, 246),
                    random.randint(220, 250),
                ),
            )

        font = self._load_font()
        icon_pool = self._renderable_icons(font)
        if len(icon_pool) < self.icon_count:
            icon_pool = list("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
        icons = random.sample(icon_pool, self.icon_count)
        self._all_icons = []
        positions_used = []

        for icon in icons:
            for _ in range(60):
                x = random.randint(30, self.width - 50)
                y = random.randint(30, self.height - 50)
                valid = True
                for px, py in positions_used:
                    if abs(x - px) < 52 and abs(y - py) < 52:
                        valid = False
                        break
                if valid:
                    positions_used.append((x, y))
                    break

            mono = random.randint(40, 120)
            color = (mono, mono, mono)

            angle = random.randint(-20, 20)
            icon_img = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
            icon_draw = ImageDraw.Draw(icon_img)
            icon_draw.text((30, 30), icon, font=font, fill=color + (self.alpha,), anchor="mm")
            icon_img = icon_img.rotate(angle, expand=False, center=(30, 30))
            img.paste(icon_img, (x - 30, y - 30), icon_img)

            self._all_icons.append({"icon": icon, "x": x, "y": y})

        self._target_icons = random.sample(self._all_icons, self.click_count)
        self._target_sequence = "".join([c["icon"] for c in self._target_icons])

        for _ in range(90):
            x1 = random.randint(0, self.width)
            y1 = random.randint(0, self.height)
            x2 = x1 + random.randint(20, 58)
            y2 = y1 + random.randint(0, 3)
            draw.line([x1, y1, x2, y2], fill=(185, 190, 205), width=1)

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        self._image = base64.b64encode(buffer.getvalue()).decode()

        self._answer = self._target_sequence
        self._generated = True

        return {
            "image": self._image,
            "target_sequence": self._target_sequence,
            "click_count": self.click_count,
            "width": self.width,
            "height": self.height,
        }

    def render_html(self) -> str:
        if not self._generated:
            self.generate()

        target_display = " -> ".join(list(self._target_sequence))
        aspect_ratio = round(self.width / self.height, 4)
        return f'''
        <div class="click-captcha" style="width:min(100%, {self.width}px); margin:0 auto;">
            <div class="click-instruction" style="text-align:center; margin-bottom:12px; padding:12px; background:linear-gradient(135deg,#f0f9ff,#e0f2fe); border-radius:8px; border:1px solid #bae6fd;">
                <span style="color:#0369a1; font-weight:600;">Click icons in order:</span>
                <span style="color:#1e40af; font-weight:700; font-size:20px; margin-left:8px; letter-spacing:2px;">{target_display}</span>
            </div>
            <div class="click-image-container" id="click-container" data-nominal-width="{self.width}" data-nominal-height="{self.height}" style="position:relative; width:100%; aspect-ratio:{aspect_ratio}; margin:0 auto; border-radius:8px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.1); cursor:crosshair;">
                <img src="data:image/png;base64,{self._image}" style="width:100%; height:100%; display:block;" draggable="false" />
                <div id="click-markers" style="position:absolute; top:0; left:0; width:100%; height:100%; pointer-events:none;"></div>
            </div>
            <div style="text-align:center; margin-top:12px;">
                <span id="click-status" style="color:#6b7280; font-size:13px;">Click {self.click_count} icons in the correct order</span>
                <button type="button" id="clear-clicks" style="margin-left:12px; padding:6px 12px; background:#f3f4f6; border:none; border-radius:6px; cursor:pointer; font-size:12px; color:#4b5563;">Clear</button>
            </div>
            <input type="hidden" id="captcha-input" name="captcha" value="" />
        </div>
        <script>
        (function() {{
            const container = document.getElementById('click-container');
            const markers = document.getElementById('click-markers');
            const input = document.getElementById('captcha-input');
            const status = document.getElementById('click-status');
            const clearBtn = document.getElementById('clear-clicks');
            const maxClicks = {self.click_count};
            const nominalWidth = {self.width};
            let clicks = [];

            function getScale() {{
                return container.offsetWidth / nominalWidth;
            }}

            function updateDisplay() {{
                const scale = getScale();
                markers.innerHTML = '';
                clicks.forEach((click, idx) => {{
                    const marker = document.createElement('div');
                    const dispX = click.x * scale;
                    const dispY = click.y * scale;
                    const markerSize = Math.max(24, Math.round(30 * scale));
                    marker.style.cssText = `
                        position:absolute; left:${{dispX - markerSize/2}}px; top:${{dispY - markerSize/2}}px;
                        width:${{markerSize}}px; height:${{markerSize}}px; background:rgba(79,70,229,0.9);
                        border:2px solid white; border-radius:50%; color:white;
                        font-size:${{Math.max(11, Math.round(14 * scale))}}px; font-weight:bold; display:flex; align-items:center; justify-content:center;
                        box-shadow:0 2px 6px rgba(0,0,0,0.3);
                    `;
                    marker.textContent = idx + 1;
                    markers.appendChild(marker);
                }});

                input.value = clicks.map(c => `${{c.x}},${{c.y}}`).join(';');
                if (clicks.length < maxClicks) {{
                    status.textContent = `Clicked ${{clicks.length}}/${{maxClicks}}`;
                    status.style.color = '#6b7280';
                }} else {{
                    status.textContent = 'Ready to verify!';
                    status.style.color = '#059669';
                }}
            }}

            container.addEventListener('click', function(e) {{
                if (clicks.length >= maxClicks) return;
                const rect = container.getBoundingClientRect();
                const scale = getScale();
                const x = Math.round((e.clientX - rect.left) / scale);
                const y = Math.round((e.clientY - rect.top) / scale);
                clicks.push({{x, y}});
                updateDisplay();
            }});

            clearBtn.addEventListener('click', function() {{
                clicks = [];
                updateDisplay();
            }});

            window.addEventListener('resize', function() {{
                updateDisplay();
            }});
        }})();
        </script>
        '''

    def verify(self, user_input: Any) -> CaptchaResult:
        if not user_input or user_input == "":
            return CaptchaResult(
                success=False,
                message="Please click on the icons",
                expected=self._target_sequence,
                received="",
            )

        try:
            click_strs = str(user_input).split(";")
            clicks = []
            for cs in click_strs:
                if "," in cs:
                    x, y = cs.split(",")
                    clicks.append((int(x), int(y)))
        except (ValueError, TypeError):
            return CaptchaResult(
                success=False,
                message="Invalid click data format",
                expected=self._target_sequence,
                received=str(user_input),
            )

        if len(clicks) != self.click_count:
            return CaptchaResult(
                success=False,
                message=f"Expected {self.click_count} clicks, got {len(clicks)}",
                expected=self._target_sequence,
                received=str(user_input),
            )

        for i, (click_x, click_y) in enumerate(clicks):
            target = self._target_icons[i]
            dist = ((click_x - target["x"]) ** 2 + (click_y - target["y"]) ** 2) ** 0.5
            if dist > self.tolerance:
                return CaptchaResult(
                    success=False,
                    message=f"Click {i+1} was not on the correct icon",
                    expected=self._target_sequence,
                    received=str(user_input),
                    extra={"failed_at": i + 1, "distance": dist},
                )

        return CaptchaResult(
            success=True,
            message="Verification successful!",
            expected=self._target_sequence,
            received=str(user_input),
        )
