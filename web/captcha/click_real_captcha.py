import random
import base64
import io
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from .base import BaseCaptcha, CaptchaType, CaptchaResult


class ClickRealCaptcha(BaseCaptcha):

    SUPPORTED_FORMATS = {'.jpg', '.jpeg', '.png', '.webp'}
    CHARACTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    def __init__(
        self,
        image_dir: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        width: int = 300,
        height: int = 200,
        char_count: int = 6,
        click_count: int = 3,
        tolerance: int = 25,
        **kwargs
    ):
        super().__init__(CaptchaType.CLICK, **kwargs)
        self.width = width
        self.height = height
        self.char_count = char_count
        self.click_count = click_count
        self.tolerance = tolerance


        self._image_paths: List[Path] = []

        if image_dir:
            self._scan_image_dir(image_dir)

        if image_paths:
            for p in image_paths:
                path = Path(p)
                if path.exists() and path.suffix.lower() in self.SUPPORTED_FORMATS:
                    self._image_paths.append(path)

        if not self._image_paths:
            raise ValueError(
                f"No valid images found. Please provide images via image_dir or image_paths. "
                f"Supported formats: {self.SUPPORTED_FORMATS}"
            )

        self._image: str = ""
        self._all_chars: List[Dict] = []
        self._target_chars: List[Dict] = []
        self._target_sequence: str = ""
        self._current_image_path: Optional[Path] = None

    def _scan_image_dir(self, image_dir: str) -> None:
        dir_path = Path(image_dir)
        if not dir_path.exists():
            print(f"[Warning] Image directory not found: {image_dir}")
            return

        for file_path in dir_path.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_FORMATS:
                self._image_paths.append(file_path)

        print(f"[ClickRealCaptcha] Found {len(self._image_paths)} images in {image_dir}")

    def _load_and_resize_image(self, image_path: Path) -> Image.Image:
        img = Image.open(image_path)


        if img.mode != 'RGB':
            img = img.convert('RGB')


        img_ratio = img.width / img.height
        target_ratio = self.width / self.height

        if img_ratio > target_ratio:
            new_height = self.height
            new_width = int(new_height * img_ratio)
        else:
            new_width = self.width
            new_height = int(new_width / img_ratio)

        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)


        left = (new_width - self.width) // 2
        top = (new_height - self.height) // 2
        img = img.crop((left, top, left + self.width, top + self.height))

        return img

    def _get_contrasting_color(self, img: Image.Image, x: int, y: int, size: int = 40) -> Tuple[int, int, int]:

        region = img.crop((
            max(0, x - size // 2),
            max(0, y - size // 2),
            min(self.width, x + size // 2),
            min(self.height, y + size // 2)
        ))


        pixel_reader = getattr(region, "get_flattened_data", region.getdata)
        pixels = list(pixel_reader())
        if not pixels:
            return (255, 255, 255)

        avg_r = sum(p[0] for p in pixels) // len(pixels)
        avg_g = sum(p[1] for p in pixels) // len(pixels)
        avg_b = sum(p[2] for p in pixels) // len(pixels)

        brightness = (avg_r * 299 + avg_g * 587 + avg_b * 114) // 1000


        if brightness > 128:

            return (
                random.randint(20, 80),
                random.randint(20, 80),
                random.randint(20, 80)
            )
        else:

            return (
                random.randint(200, 255),
                random.randint(200, 255),
                random.randint(200, 255)
            )

    def generate(self) -> Dict[str, Any]:

        self._current_image_path = random.choice(self._image_paths)
        img = self._load_and_resize_image(self._current_image_path)


        img_blurred = img.filter(ImageFilter.GaussianBlur(radius=0.5))


        chars = random.sample(self.CHARACTERS, self.char_count)

        self._all_chars = []
        positions_used = []


        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
        except:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
            except:
                font = ImageFont.load_default()


        for char in chars:

            for _ in range(50):
                x = random.randint(40, self.width - 40)
                y = random.randint(40, self.height - 40)

                valid = True
                for px, py in positions_used:
                    if abs(x - px) < 55 and abs(y - py) < 55:
                        valid = False
                        break

                if valid:
                    positions_used.append((x, y))
                    break


            color = self._get_contrasting_color(img, x, y)


            char_size = 50
            char_img = Image.new('RGBA', (char_size, char_size), (0, 0, 0, 0))
            char_draw = ImageDraw.Draw(char_img)


            bg_color = (255, 255, 255, 180) if sum(color) < 400 else (0, 0, 0, 120)
            char_draw.ellipse([5, 5, char_size - 5, char_size - 5], fill=bg_color)


            char_draw.text((char_size // 2, char_size // 2), char, font=font, fill=color + (255,), anchor="mm")


            angle = random.randint(-20, 20)
            char_img = char_img.rotate(angle, expand=False, center=(char_size // 2, char_size // 2))


            img_blurred.paste(char_img, (x - char_size // 2, y - char_size // 2), char_img)

            self._all_chars.append({
                "char": char,
                "x": x,
                "y": y,
                "color": color
            })


        self._target_chars = random.sample(self._all_chars, self.click_count)
        self._target_sequence = "".join([c["char"] for c in self._target_chars])


        buffer = io.BytesIO()
        img_blurred.save(buffer, format='PNG')
        self._image = base64.b64encode(buffer.getvalue()).decode()

        self._answer = self._target_sequence
        self._generated = True

        return {
            "image": self._image,
            "target_sequence": self._target_sequence,
            "click_count": self.click_count,
            "width": self.width,
            "height": self.height,
            "source_image": str(self._current_image_path) if self._current_image_path else None
        }

    def render_html(self) -> str:
        if not self._generated:
            self.generate()

        target_display = " → ".join(list(self._target_sequence))

        aspect_ratio = round(self.width / self.height, 4)
        return f'''
        <div class="click-captcha" style="width: min(100%, {self.width}px); margin: 0 auto;">
            <div class="click-instruction" style="text-align: center; margin-bottom: 12px; padding: 12px; background: linear-gradient(135deg, #f0f9ff, #e0f2fe); border-radius: 8px; border: 1px solid #bae6fd;">
                <span style="color: #0369a1; font-weight: 600;">Click in order:</span>
                <span style="color: #1e40af; font-weight: 700; font-size: 18px; margin-left: 8px; letter-spacing: 2px;">{target_display}</span>
            </div>
            <div class="click-image-container" id="click-container" data-nominal-width="{self.width}" data-nominal-height="{self.height}" style="position: relative; width: 100%; aspect-ratio: {aspect_ratio}; margin: 0 auto; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.2); cursor: crosshair;">
                <img src="data:image/png;base64,{self._image}" style="width: 100%; height: 100%; display: block;" draggable="false" />
                <div id="click-markers" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none;"></div>
            </div>
            <div style="text-align: center; margin-top: 12px;">
                <span id="click-status" style="color: #6b7280; font-size: 13px;">Click {self.click_count} characters in the correct order</span>
                <button type="button" id="clear-clicks" style="margin-left: 12px; padding: 6px 12px; background: #f3f4f6; border: none; border-radius: 6px; cursor: pointer; font-size: 12px; color: #4b5563;">Clear</button>
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
                        position: absolute;
                        left: ${{dispX - markerSize/2}}px;
                        top: ${{dispY - markerSize/2}}px;
                        width: ${{markerSize}}px;
                        height: ${{markerSize}}px;
                        background: rgba(79, 70, 229, 0.9);
                        border: 2px solid white;
                        border-radius: 50%;
                        color: white;
                        font-size: ${{Math.max(11, Math.round(14 * scale))}}px;
                        font-weight: bold;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        box-shadow: 0 2px 6px rgba(0,0,0,0.3);
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
                
                clicks.push({{ x, y }});
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
                message="Please click on the characters",
                expected=self._target_sequence,
                received=""
            )

        try:
            click_strs = str(user_input).split(';')
            clicks = []
            for cs in click_strs:
                if ',' in cs:
                    x, y = cs.split(',')
                    clicks.append((int(x), int(y)))
        except (ValueError, TypeError):
            return CaptchaResult(
                success=False,
                message="Invalid click data format",
                expected=self._target_sequence,
                received=str(user_input)
            )

        if len(clicks) != self.click_count:
            return CaptchaResult(
                success=False,
                message=f"Expected {self.click_count} clicks, got {len(clicks)}",
                expected=self._target_sequence,
                received=str(user_input)
            )

        for i, (click_x, click_y) in enumerate(clicks):
            target = self._target_chars[i]
            target_x, target_y = target["x"], target["y"]

            dist = ((click_x - target_x) ** 2 + (click_y - target_y) ** 2) ** 0.5

            if dist > self.tolerance:
                return CaptchaResult(
                    success=False,
                    message=f"Click {i+1} was not on the correct character",
                    expected=self._target_sequence,
                    received=str(user_input),
                    extra={"failed_at": i + 1, "distance": dist}
                )

        return CaptchaResult(
            success=True,
            message="Verification successful!",
            expected=self._target_sequence,
            received=str(user_input)
        )

    def get_available_images(self) -> List[str]:
        return [str(p) for p in self._image_paths]

    def get_current_image(self) -> Optional[str]:
        return str(self._current_image_path) if self._current_image_path else None
