import random
import base64
import io
from pathlib import Path
from typing import Any, Dict, List, Optional
from PIL import Image, ImageDraw

from .base import BaseCaptcha, CaptchaType, CaptchaResult


class SliderRealCaptcha(BaseCaptcha):

    SUPPORTED_FORMATS = {'.jpg', '.jpeg', '.png', '.webp'}

    def __init__(
        self,
        image_dir: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        width: int = 300,
        height: int = 150,
        slider_size: int = 40,
        tolerance: int = 10,
        difficulty: str = "normal",
        **kwargs
    ):
        super().__init__(CaptchaType.SLIDER, **kwargs)
        if difficulty not in {"easy", "normal", "hard"}:
            raise ValueError("difficulty must be one of: easy, normal, hard")
        self.width = width
        self.height = height
        self.difficulty = difficulty
        if difficulty == "easy":
            self.slider_size = max(slider_size, 46)
            self.tolerance = max(tolerance, 14)
            self._verify_on_release = False
        elif difficulty == "hard":
            self.slider_size = min(slider_size, 36)
            self.tolerance = max(6, tolerance - 2)
            self._verify_on_release = True
        else:
            self.slider_size = slider_size
            self.tolerance = tolerance
            self._verify_on_release = True


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

        self._target_x: int = 0
        self._bg_image: str = ""
        self._slider_image: str = ""
        self._current_image_path: Optional[Path] = None

    def _scan_image_dir(self, image_dir: str) -> None:
        dir_path = Path(image_dir)
        if not dir_path.exists():
            print(f"[Warning] Image directory not found: {image_dir}")
            return

        for file_path in dir_path.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_FORMATS:
                self._image_paths.append(file_path)

        print(f"[SliderRealCaptcha] Found {len(self._image_paths)} images in {image_dir}")

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

    def generate(self) -> Dict[str, Any]:

        self._current_image_path = random.choice(self._image_paths)
        bg_img = self._load_and_resize_image(self._current_image_path)


        min_x = self.slider_size + 20
        max_x = self.width - self.slider_size - 20
        self._target_x = random.randint(min_x, max_x)
        target_y = (self.height - self.slider_size) // 2


        slider_region = bg_img.crop((
            self._target_x,
            target_y,
            self._target_x + self.slider_size,
            target_y + self.slider_size
        ))


        slider_img = Image.new('RGBA', (self.slider_size, self.slider_size), (0, 0, 0, 0))
        slider_img.paste(slider_region, (0, 0))


        slider_draw = ImageDraw.Draw(slider_img)
        slider_draw.rectangle(
            [0, 0, self.slider_size - 1, self.slider_size - 1],
            outline=(255, 255, 255, 255),
            width=2
        )


        bg_rgba = bg_img.convert('RGBA')
        overlay = Image.new('RGBA', (self.width, self.height), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle(
            [self._target_x, target_y, self._target_x + self.slider_size, target_y + self.slider_size],
            fill=(60, 60, 60, 180)
        )
        bg_rgba = Image.alpha_composite(bg_rgba, overlay)
        bg_img = bg_rgba.convert('RGB')


        bg_buffer = io.BytesIO()
        bg_img.save(bg_buffer, format='PNG')
        self._bg_image = base64.b64encode(bg_buffer.getvalue()).decode()

        slider_buffer = io.BytesIO()
        slider_img.save(slider_buffer, format='PNG')
        self._slider_image = base64.b64encode(slider_buffer.getvalue()).decode()

        self._answer = str(self._target_x)
        self._generated = True

        return {
            "bg_image": self._bg_image,
            "slider_image": self._slider_image,
            "target_x": self._target_x,
            "width": self.width,
            "height": self.height,
            "slider_size": self.slider_size,
            "source_image": str(self._current_image_path) if self._current_image_path else None,
            "difficulty": self.difficulty,
        }

    def render_html(self) -> str:
        if not self._generated:
            self.generate()

        aspect_ratio = round(self.width / self.height, 4)
        hint_text = "Release after dragging to verify" if self._verify_on_release else "Drag the slider to the gap, then click Verify"
        return f'''
        <div class="slider-captcha" style="user-select: none; width: min(100%, {self.width}px); margin: 0 auto; overflow-x: visible;">
            <div class="slider-image-container" id="slider-image-container" style="position: relative; width: 100%; aspect-ratio: {aspect_ratio}; margin: 0 auto; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.2);">
                <img src="data:image/png;base64,{self._bg_image}" style="width: 100%; height: 100%; display: block;" draggable="false" />
                <div id="slider-piece" style="position: absolute; left: 0; top: 50%; transform: translateY(-50%); width: {round(self.slider_size / self.width * 100, 2)}%; aspect-ratio: 1; cursor: grab; filter: drop-shadow(2px 2px 4px rgba(0,0,0,0.4));">
                    <img src="data:image/png;base64,{self._slider_image}" style="width: 100%; height: 100%;" draggable="false" />
                </div>
            </div>
            <div class="slider-track" id="slider-track" style="position: relative; width: 100%; height: 44px; margin: 16px auto 0; background: #f3f4f6; border-radius: 22px; box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);">
                <div id="slider-progress" style="position: absolute; left: 0; top: 0; height: 100%; background: linear-gradient(90deg, #4f46e5, #7c3aed); border-radius: 22px; width: 44px; transition: none;"></div>
                <div id="slider-handle" style="position: absolute; left: 0; top: 0; width: 44px; height: 44px; background: #fff; border-radius: 50%; box-shadow: 0 2px 8px rgba(0,0,0,0.2); cursor: grab; display: flex; align-items: center; justify-content: center; font-size: 18px; color: #4f46e5; transition: none;">
                    ⇄
                </div>
                <span id="slider-track-hint" style="position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); color: #9ca3af; font-size: 13px; pointer-events: none;">{hint_text}</span>
            </div>
            <div class="slider-status-wrap" style="display: flex; justify-content: center; width: 100%; margin-top: 10px; overflow: visible;">
                <p id="slider-status" style="min-height: 22px; margin: 0; width: 100%; font-size: 13px; text-align: center; color: #6b7280; box-sizing: border-box;"></p>
            </div>
            <input type="hidden" id="captcha-input" name="captcha" value="0" />
        </div>
        <script>
        (function() {{
            const handle = document.getElementById('slider-handle');
            const progress = document.getElementById('slider-progress');
            const piece = document.getElementById('slider-piece');
            const input = document.getElementById('captcha-input');
            const trapInput = document.getElementById('captcha-trap-input');
            const track = document.getElementById('slider-track');
            const container = document.getElementById('slider-image-container');
            const statusEl = document.getElementById('slider-status');
            const hintEl = document.getElementById('slider-track-hint');
            const nominalWidth = {self.width};
            const nominalSliderSize = {self.slider_size};
            const verifyOnRelease = {str(self._verify_on_release).lower()};
            let isDragging = false;
            let startX = 0;
            let currentX = 0;
            let verified = false;
            let verifying = false;

            function getTrackWidth() {{
                return Math.max(0, track.offsetWidth - 44);
            }}

            function updatePosition(x) {{
                const trackWidth = Math.max(1, getTrackWidth());
                x = Math.max(0, Math.min(x, getTrackWidth()));
                handle.style.left = x + 'px';
                progress.style.width = (x + 44) + 'px';
                const maxPieceX = nominalWidth - nominalSliderSize;
                const pieceX = Math.round((x / trackWidth) * maxPieceX);
                const piecePercent = (pieceX / nominalWidth) * 100;
                piece.style.left = piecePercent + '%';
                input.value = pieceX;
                currentX = x;
            }}

            function clearSlideTransitions() {{
                handle.style.transition = 'none';
                progress.style.transition = 'none';
                piece.style.transition = 'none';
            }}

            function resetToInitial() {{
                clearSlideTransitions();
                handle.style.transition = 'left 0.25s ease-out';
                progress.style.transition = 'width 0.25s ease-out';
                piece.style.transition = 'left 0.25s ease-out';
                requestAnimationFrame(function() {{ updatePosition(0); }});
                setTimeout(clearSlideTransitions, 280);
            }}

            function openResultModal(success, title, message) {{
                const modal = document.getElementById('result-modal');
                const modalIcon = document.getElementById('modal-icon');
                const modalTitle = document.getElementById('modal-title');
                const modalMessage = document.getElementById('modal-message');
                const modalRetry = document.getElementById('modal-retry');
                if (!modal || !modalIcon || !modalTitle || !modalMessage) return;
                modalIcon.className = 'modal-icon ' + (success ? 'success' : 'error');
                modalIcon.textContent = success ? '✓' : '✗';
                modalTitle.textContent = title;
                modalMessage.textContent = message;
                if (modalRetry) modalRetry.style.display = success ? 'none' : 'inline-block';
                modal.classList.add('show');
            }}

            function styleStatusIdle() {{
                if (!statusEl) return;
                statusEl.textContent = '';
                statusEl.style.cssText = 'min-height: 22px; margin: 0; width: 100%; font-size: 13px; text-align: center; color: #6b7280; box-sizing: border-box; flex-shrink: 0;';
            }}

            function styleStatusError(text) {{
                if (!statusEl) return;
                statusEl.textContent = text;
                statusEl.style.cssText = 'min-height: auto; margin: 0; padding: 14px 22px; width: max-content; max-width: min(560px, calc(100vw - 48px)); flex-shrink: 0; font-size: 17px; font-weight: 700; line-height: 1.45; text-align: center; color: #991b1b; background: linear-gradient(180deg, #fef2f2 0%, #fee2e2 100%); border-radius: 12px; border: 2px solid #f87171; box-shadow: 0 2px 8px rgba(220,38,38,0.18); box-sizing: border-box; white-space: nowrap; overflow-x: visible;';
            }}

            function applyVerifiedDisabledState() {{
                verified = true;
                handle.style.cursor = 'default';
                handle.style.pointerEvents = 'none';
                piece.style.pointerEvents = 'none';
                progress.style.pointerEvents = 'none';
                if (hintEl) hintEl.textContent = 'Verified';
                styleStatusIdle();
                const submitBtn = document.querySelector('#captcha-form button[type="submit"]');
                if (submitBtn && verifyOnRelease) submitBtn.disabled = true;
            }}

            function attemptVerifyOnRelease() {{
                if (verified || verifying) return;
                verifying = true;
                const body = new URLSearchParams();
                const rawAnswer = String(input.value);
                const payloadAnswer = typeof window.__captchaBuildDynamicPayload === 'function'
                    ? window.__captchaBuildDynamicPayload(rawAnswer)
                    : rawAnswer;
                body.set('captcha', payloadAnswer);
                if (trapInput) {{
                    body.set('captcha_trap', String(trapInput.value || ''));
                }}
                fetch('/verify', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
                    body: body.toString()
                }})
                .then(function(r) {{ return r.json(); }})
                .then(function(data) {{
                    if (data.success) {{
                        openResultModal(true, 'Success!', data.message || 'Verification succeeded.');
                        applyVerifiedDisabledState();
                    }} else {{
                        resetToInitial();
                        styleStatusError(data.message || 'Slider position incorrect. Please try again.');
                        window.setTimeout(function() {{
                            if (!verified && statusEl) styleStatusIdle();
                        }}, 4200);
                    }}
                }})
                .catch(function() {{
                    resetToInitial();
                    styleStatusError('Network error. Please try again.');
                }})
                .finally(function() {{ verifying = false; }});
            }}

            function onPointerUp() {{
                if (!isDragging) return;
                isDragging = false;
                handle.style.cursor = verified ? 'default' : 'grab';
                if (!verified && verifyOnRelease) attemptVerifyOnRelease();
            }}

            handle.addEventListener('mousedown', function(e) {{
                if (verified || verifying) return;
                clearSlideTransitions();
                isDragging = true;
                startX = e.clientX - currentX;
                handle.style.cursor = 'grabbing';
                e.preventDefault();
            }});

            document.addEventListener('mousemove', function(e) {{
                if (!isDragging || verified) return;
                updatePosition(e.clientX - startX);
            }});

            document.addEventListener('mouseup', onPointerUp);

            handle.addEventListener('touchstart', function(e) {{
                if (verified || verifying) return;
                clearSlideTransitions();
                isDragging = true;
                startX = e.touches[0].clientX - currentX;
                e.preventDefault();
            }}, {{ passive: false }});

            document.addEventListener('touchmove', function(e) {{
                if (!isDragging || verified) return;
                e.preventDefault();
                updatePosition(e.touches[0].clientX - startX);
            }}, {{ passive: false }});

            document.addEventListener('touchend', onPointerUp);
            document.addEventListener('touchcancel', onPointerUp);
        }})();
        </script>
        '''

    def verify(self, user_input: Any) -> CaptchaResult:
        try:
            user_x = int(user_input)
        except (ValueError, TypeError):
            return CaptchaResult(
                success=False,
                message="Invalid input format",
                expected=str(self._target_x),
                received=str(user_input)
            )

        diff = abs(user_x - self._target_x)

        if diff <= self.tolerance:
            return CaptchaResult(
                success=True,
                message="Verification succeeded.",
                expected=str(self._target_x),
                received=str(user_x),
                extra={"diff": diff, "tolerance": self.tolerance}
            )
        else:
            return CaptchaResult(
                success=False,
                message="Slider position incorrect. Please try again.",
                expected=str(self._target_x),
                received=str(user_x),
                extra={"diff": diff, "tolerance": self.tolerance}
            )

    def get_available_images(self) -> List[str]:
        return [str(p) for p in self._image_paths]

    def get_current_image(self) -> Optional[str]:
        return str(self._current_image_path) if self._current_image_path else None
