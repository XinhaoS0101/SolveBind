import base64
import io
import json
import os
import random
import urllib.parse
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFilter

from .base import BaseCaptcha, CaptchaType, CaptchaResult


class MissingPieceCaptcha(BaseCaptcha):

    def __init__(
        self,
        image_width: int = 400,
        image_height: int = 300,
        piece_width: int = 80,
        piece_height: int = 80,
        candidate_count: int = 4,
        pexels_api_key: Optional[str] = None,
        pexels_query: str = "nature landscape",
        difficulty: str = "normal",
        **kwargs,
    ):
        super().__init__(CaptchaType.CLICK, **kwargs)

        if difficulty == "easy":
            self.candidate_count = 3
            self.blur_distractor = False
        elif difficulty == "hard":
            self.candidate_count = 6
            self.blur_distractor = True
        else:
            self.candidate_count = candidate_count
            self.blur_distractor = False

        self.difficulty = difficulty
        self.image_width = image_width
        self.image_height = image_height
        self.piece_width = piece_width
        self.piece_height = piece_height
        self.pexels_api_key = pexels_api_key or os.getenv("PEXELS_API_KEY")
        self.pexels_query = pexels_query

        self._main_image_b64: str = ""
        self._candidates_b64: List[str] = []
        self._correct_index: int = 0

    def _fetch_pexels_image(self) -> Image.Image:
        if not self.pexels_api_key:
            return self._build_fallback_image()

        try:
            params = urllib.parse.urlencode(
                {
                    "query": self.pexels_query,
                    "per_page": 1,
                    "page": random.randint(1, 100),
                    "orientation": "landscape",
                }
            )
            url = f"https://api.pexels.com/v1/search?{params}"
            req = Request(
                url,
                headers={
                    "Authorization": self.pexels_api_key,
                    "User-Agent": "HLL/1.0",
                },
            )

            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if not data.get("photos"):
                return self._build_fallback_image()

            image_url = data["photos"][0]["src"]["large"]
            img_req = Request(image_url, headers={"User-Agent": "HLL/1.0"})

            with urlopen(img_req, timeout=10) as img_resp:
                img_data = img_resp.read()

            return Image.open(io.BytesIO(img_data)).convert("RGB")
        except Exception as e:
            print(f"[MissingPieceCaptcha] Pexels fetch failed: {e}")
            return self._build_fallback_image()

    def _build_fallback_image(self) -> Image.Image:
        img = Image.new("RGB", (self.image_width, self.image_height))
        draw = ImageDraw.Draw(img)
        for y in range(self.image_height):
            ratio = y / max(self.image_height - 1, 1)
            r = int(70 + ratio * 110)
            g = int(120 + ratio * 70)
            b = int(180 - ratio * 80)
            draw.line([(0, y), (self.image_width, y)], fill=(r, g, b))
        for _ in range(15):
            x1 = random.randint(0, self.image_width - 10)
            y1 = random.randint(0, self.image_height - 10)
            x2 = min(self.image_width, x1 + random.randint(30, 100))
            y2 = min(self.image_height, y1 + random.randint(20, 80))
            color = (
                random.randint(120, 245),
                random.randint(120, 245),
                random.randint(120, 245),
            )
            draw.ellipse([x1, y1, x2, y2], fill=color)
        return img

    def generate(self) -> Dict[str, Any]:
        image = self._fetch_pexels_image()
        image = image.resize(
            (self.image_width, self.image_height), Image.Resampling.LANCZOS
        )

        max_x = self.image_width - self.piece_width
        max_y = self.image_height - self.piece_height
        piece_x = random.randint(0, max_x)
        piece_y = random.randint(0, max_y)

        correct_piece = image.crop(
            (piece_x, piece_y, piece_x + self.piece_width, piece_y + self.piece_height)
        )

        main_image = image.copy()
        draw = ImageDraw.Draw(main_image)
        draw.rectangle(
            [piece_x, piece_y, piece_x + self.piece_width, piece_y + self.piece_height],
            fill=(200, 200, 200),
        )
        draw.rectangle(
            [piece_x, piece_y, piece_x + self.piece_width, piece_y + self.piece_height],
            outline=(100, 100, 100),
            width=2,
        )

        candidates = [correct_piece]
        for _ in range(self.candidate_count - 1):
            distractor = self._generate_distractor(image, piece_x, piece_y)
            candidates.append(distractor)

        self._correct_index = random.randint(0, self.candidate_count - 1)
        candidates.insert(self._correct_index, candidates.pop(0))

        self._main_image_b64 = self._image_to_base64(main_image)
        self._candidates_b64 = [self._image_to_base64(c) for c in candidates]
        self._answer = str(self._correct_index)
        self._generated = True

        return {
            "type": "missing_piece",
            "main_image": self._main_image_b64,
            "candidates": self._candidates_b64,
            "piece_width": self.piece_width,
            "piece_height": self.piece_height,
        }

    def _generate_distractor(
        self, image: Image.Image, avoid_x: int, avoid_y: int
    ) -> Image.Image:
        max_x = self.image_width - self.piece_width
        max_y = self.image_height - self.piece_height

        for _ in range(20):
            x = random.randint(0, max_x)
            y = random.randint(0, max_y)
            if abs(x - avoid_x) > self.piece_width or abs(y - avoid_y) > self.piece_height:
                break

        piece = image.crop((x, y, x + self.piece_width, y + self.piece_height))

        if self.blur_distractor:
            piece = piece.filter(ImageFilter.GaussianBlur(radius=1))

        return piece

    def _image_to_base64(self, image: Image.Image) -> str:
        buff = io.BytesIO()
        image.save(buff, format="PNG")
        return base64.b64encode(buff.getvalue()).decode("utf-8")

    def render_html(self) -> str:
        if not self._generated:
            self.generate()

        candidates_json = json.dumps(self._candidates_b64, ensure_ascii=False)
        grid_columns = 2 if self.candidate_count <= 4 else 3

        return f"""
        <script>
        document.body.classList.add('missing-piece-page');
        </script>
        <style>
        @media (max-width: 520px) {{
            body.missing-piece-page {{
                padding: 12px;
                place-items: start center;
            }}
            body.missing-piece-page .card {{
                padding: 22px 24px;
            }}
            body.missing-piece-page h1 {{
                font-size: 22px;
                margin-bottom: 6px;
            }}
            body.missing-piece-page p.desc {{
                margin-bottom: 14px;
            }}
            body.missing-piece-page .captcha-container {{
                margin-bottom: 12px;
            }}
            body.missing-piece-page .actions {{
                margin-top: 14px;
            }}
            body.missing-piece-page footer {{
                margin-top: 14px;
            }}
            .missing-piece-captcha .missing-piece-instruction {{
                margin-bottom: 8px !important;
                padding: 8px 10px !important;
                font-size: 14px;
                line-height: 1.35;
            }}
            .missing-piece-captcha .missing-piece-main {{
                margin-bottom: 10px !important;
            }}
            .missing-piece-captcha .missing-piece-main img {{
                width: min(100%, 300px) !important;
            }}
            .missing-piece-captcha #candidates-grid {{
                max-width: 300px !important;
                gap: 8px !important;
            }}
        }}
        </style>
        <div class="missing-piece-captcha" style="user-select:none; width: 100%;">
            <div class="missing-piece-instruction" style="text-align:center; margin-bottom: 12px; padding: 10px 12px;
                        background: linear-gradient(135deg, #f0f9ff, #e0f2fe);
                        border-radius: 10px; border: 1px solid #bae6fd;">
                <span style="color: #0369a1; font-weight: 600;">
                    Select the correct piece to complete the image
                </span>
            </div>

            <div class="missing-piece-main" style="text-align:center; margin-bottom: 16px;">
                <img src="data:image/png;base64,{self._main_image_b64}"
                     style="display: block; width: min(100%, {self.image_width}px); height: auto; margin: 0 auto; border: 2px solid #cbd5e1; border-radius: 8px;" />
            </div>

            <div id="candidates-grid" style="
                display: grid;
                grid-template-columns: repeat({grid_columns}, minmax(0, 1fr));
                gap: 12px;
                width: 100%;
                max-width: {self.image_width}px;
                margin: 0 auto;
                align-items: stretch;
            "></div>

            <input type="hidden" id="captcha-input" name="captcha" value="" />
        </div>

        <script>
        (function() {{
            const candidates = {candidates_json};
            const grid = document.getElementById('candidates-grid');
            const input = document.getElementById('captcha-input');
            let selected = null;

            candidates.forEach((imgB64, idx) => {{
                const item = document.createElement('div');
                item.dataset.candidateIndex = String(idx);
                item.className = 'missing-piece-candidate';
                item.style.cssText = `
                    cursor: pointer;
                    border: 2px solid #cbd5e1;
                    border-radius: 8px;
                    overflow: hidden;
                    background: #fff;
                    aspect-ratio: ${self.piece_width} / ${self.piece_height};
                    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
                    transition: border-color .2s ease, box-shadow .2s ease;
                    touch-action: manipulation;
                `;

                const img = document.createElement('img');
                img.src = 'data:image/png;base64,' + imgB64;
                img.style.cssText = 'width: 100%; height: 100%; display: block; object-fit: cover;';
                item.appendChild(img);

                item.addEventListener('click', () => {{
                    if (selected !== null) {{
                        grid.children[selected].style.border = '2px solid #cbd5e1';
                        grid.children[selected].style.boxShadow = '0 1px 3px rgba(15, 23, 42, 0.08)';
                    }}
                    selected = idx;
                    item.style.border = '2px solid #3b82f6';
                    item.style.boxShadow = '0 0 0 3px rgba(59, 130, 246, 0.18)';
                    input.value = String(idx);
                }});

                item.addEventListener('mouseenter', () => {{
                    if (selected !== idx) {{
                        item.style.border = '2px solid #3b82f6';
                    }}
                }});

                item.addEventListener('mouseleave', () => {{
                    if (selected !== idx) {{
                        item.style.border = '2px solid #cbd5e1';
                    }}
                }});

                grid.appendChild(item);
            }});
        }})();
        </script>
        """

    def verify(self, user_input: Any) -> CaptchaResult:
        if user_input is None or str(user_input).strip() == "":
            return CaptchaResult(
                success=False,
                message="Please select a piece.",
                expected=self._answer,
                received="",
            )

        user_choice = str(user_input).strip()
        success = user_choice == self._answer

        return CaptchaResult(
            success=success,
            message="Verification successful!" if success else "Incorrect piece, please try again.",
            expected=self._answer,
            received=user_choice,
        )
