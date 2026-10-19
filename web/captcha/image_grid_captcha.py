import base64
import io
import json
import os
import random
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from .base import BaseCaptcha, CaptchaType, CaptchaResult


CATEGORIES: List[Dict[str, Any]] = [
    {
        "label": "cats",
        "query": "cat face portrait",
        "query_easy": "cat face close-up portrait front",
        "query_hard": "cat outdoor scene",
        "distractors": ["dog face portrait", "rabbit close-up"],
        "distractor_labels": ["dogs", None],
    },
    {
        "label": "dogs",
        "query": "dog face portrait",
        "query_easy": "dog face close-up portrait front",
        "query_hard": "dog outdoor scene",
        "distractors": ["cat face portrait", "horse head close-up"],
        "distractor_labels": ["cats", "horses"],
    },
    {
        "label": "cars",
        "query": "car automobile road",
        "query_easy": "car front view close-up",
        "query_hard": "car street scene traffic",
        "distractors": ["motorcycle road", "bus vehicle street"],
        "distractor_labels": ["motorcycles", "buses"],
    },
    {
        "label": "bicycles",
        "query": "bicycle cyclist",
        "query_easy": "bicycle close-up front view",
        "query_hard": "bicycle street scene",
        "distractors": ["motorcycle road", "car road street"],
        "distractor_labels": ["motorcycles", "cars"],
    },
    {
        "label": "buses",
        "query": "bus public transit",
        "query_easy": "bus front view close-up",
        "query_hard": "bus street scene traffic",
        "distractors": ["car road street", "train railway station"],
        "distractor_labels": ["cars", "trains"],
    },
    {
        "label": "boats",
        "query": "boat sailing sea",
        "query_easy": "boat close-up sailing",
        "query_hard": "boat harbor scene",
        "distractors": ["airplane aircraft sky", "hot air balloon sky"],
        "distractor_labels": ["airplanes", "hot air balloons"],
    },
    {
        "label": "airplanes",
        "query": "airplane aircraft sky",
        "query_easy": "airplane close-up front view",
        "query_hard": "airplane airport scene distant",
        "distractors": ["boat sailing sea", "hot air balloon sky"],
        "distractor_labels": ["boats", "hot air balloons"],
    },
    {
        "label": "mountains",
        "query": "mountain peak summit snow",
        "query_easy": "mountain peak close-up clear",
        "query_hard": "mountain landscape distant",
        "distractors": ["beach ocean waves sand", "desert sand dunes"],
        "distractor_labels": ["beaches", None],
    },
    {
        "label": "flowers",
        "query": "flower bloom macro close-up",
        "query_easy": "flower bloom macro close-up single",
        "query_hard": "flower garden scene",
        "distractors": ["grass field meadow", "cactus desert"],
        "distractor_labels": [None, None],
    },
    {
        "label": "horses",
        "query": "horse equine field",
        "query_easy": "horse head close-up portrait",
        "query_hard": "horse pasture scene distant",
        "distractors": ["cow farm pasture", "zebra safari"],
        "distractor_labels": [None, None],
    },
    {
        "label": "hot air balloons",
        "query": "hot air balloon sky colorful",
        "query_easy": "hot air balloon close-up colorful",
        "query_hard": "hot air balloon festival scene",
        "distractors": ["airplane aircraft sky", "kite sky"],
        "distractor_labels": ["airplanes", None],
    },
    {
        "label": "beaches",
        "query": "beach ocean waves sand",
        "query_easy": "beach sand waves close-up clear",
        "query_hard": "beach coastline scene",
        "distractors": ["mountain snow peak", "lake calm water"],
        "distractor_labels": ["mountains", None],
    },
]


DISTRACTOR_QUERIES: Dict[str, str] = {
    "motorcycles": "motorcycle road",
    "trains": "train station railway",
}

TILE_SIZE = 128
GRID_COLS = 3
GRID_ROWS = 3
TOTAL_TILES = GRID_COLS * GRID_ROWS

DEFAULT_UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")


class ImageGridCaptcha(BaseCaptcha):

    def __init__(
        self,
        tile_size: int = TILE_SIZE,
        grid_cols: int = GRID_COLS,
        grid_rows: int = GRID_ROWS,
        correct_count_range: Tuple[int, int] = (2, 4),
        unsplash_access_key: Optional[str] = None,
        timeout: int = 8,
        image_dir: Optional[str] = None,
        difficulty: str = "normal",
        **kwargs,
    ):
        super().__init__(CaptchaType.CLICK, **kwargs)

        if difficulty == "easy":
            grid_cols = 3
            grid_rows = 3
            correct_count_range = (1, 1)
        elif difficulty == "hard":
            grid_cols = 4
            grid_rows = 4
            correct_count_range = (3, 6)
            tile_size = 96

        self.tile_size = tile_size
        self.grid_cols = grid_cols
        self.grid_rows = grid_rows
        self.total_tiles = grid_cols * grid_rows
        self.correct_count_range = correct_count_range
        self.difficulty = difficulty
        self.unsplash_access_key = unsplash_access_key or DEFAULT_UNSPLASH_ACCESS_KEY
        self.timeout = timeout
        self.image_dir = image_dir

        self._tiles_b64: List[str] = []
        self._correct_indices: List[int] = []
        self._target_label: str = ""


    @staticmethod
    def _label_to_dir_name(label: str) -> str:
        return label.lower().replace(" ", "_").replace("-", "_")

    def _load_local_images(
        self,
        label: str,
        count: int,
        rng: random.Random,
    ) -> List[Optional[Image.Image]]:
        if not self.image_dir or count <= 0:
            return []
        dir_path = Path(self.image_dir) / self._label_to_dir_name(label)
        if not dir_path.is_dir():
            return []
        exts = {".jpg", ".jpeg", ".png", ".webp"}
        files = sorted(f for f in dir_path.iterdir() if f.suffix.lower() in exts)
        if not files:
            return []
        selected = rng.sample(files, min(count, len(files)))
        images: List[Optional[Image.Image]] = []
        for f in selected:
            try:
                images.append(Image.open(f).convert("RGB"))
            except Exception as e:
                print(f"[ImageGridCaptcha] Failed to open {f}: {e}")
                images.append(None)
        return images


    def _fetch_urls_batch(self, query: str, count: int) -> List[str]:
        if not self.unsplash_access_key or count <= 0:
            return []
        try:
            params = urllib.parse.urlencode({
                "query": query,
                "orientation": "squarish",
                "content_filter": "high",
                "count": count,
            })
            req = Request(
                f"https://api.unsplash.com/photos/random?{params}",
                headers={"Authorization": f"Client-ID {self.unsplash_access_key}"},
            )
            with urlopen(req, timeout=self.timeout) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            if isinstance(raw, dict):
                raw = [raw]
            urls = []
            for item in raw:
                url = (
                    item.get("urls", {}).get("small")
                    or item.get("urls", {}).get("regular")
                )
                if url:
                    urls.append(url)
            return urls
        except Exception as e:
            print(f"[ImageGridCaptcha] Unsplash API failed (query='{query}'): {e}")
            return []

    def _download_image(self, url: str) -> Optional[Image.Image]:
        try:
            req = Request(url, headers={"User-Agent": "HLL/1.0"})
            with urlopen(req, timeout=self.timeout) as resp:
                data = resp.read()
            return Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as e:
            print(f"[ImageGridCaptcha] Image download failed: {e}")
            return None

    def _get_images_for_category(
        self,
        label: Optional[str],
        query: str,
        count: int,
        rng: random.Random,
    ) -> List[Optional[Image.Image]]:
        if count <= 0:
            return []


        if label is not None:
            local = self._load_local_images(label, count, rng)
            if local:
                return local


        urls = self._fetch_urls_batch(query, count)
        if not urls:
            return [None] * count

        downloaded: Dict[int, Optional[Image.Image]] = {}
        with ThreadPoolExecutor(max_workers=min(len(urls), 9)) as ex:
            futures = {ex.submit(self._download_image, url): i
                       for i, url in enumerate(urls)}
            for fut in as_completed(futures):
                downloaded[futures[fut]] = fut.result()

        return [downloaded.get(i) for i in range(len(urls))]


    def _make_fallback_tile(
        self,
        label: str,
        is_correct: bool,
        rng: random.Random,
    ) -> Image.Image:
        img = Image.new("RGB", (self.tile_size, self.tile_size))
        draw = ImageDraw.Draw(img)

        for y in range(self.tile_size):
            ratio = y / max(self.tile_size - 1, 1)
            if is_correct:
                r, g, b = int(60 + ratio * 60), int(140 + ratio * 60), int(60 + ratio * 40)
            else:
                r, g, b = int(60 + ratio * 50), int(90 + ratio * 50), int(140 + ratio * 60)
            draw.line([(0, y), (self.tile_size, y)], fill=(r, g, b))

        for _ in range(6):
            x1 = rng.randint(0, self.tile_size - 20)
            y1 = rng.randint(0, self.tile_size - 20)
            r_val = rng.randint(10, 35)
            draw.ellipse(
                [x1, y1, x1 + r_val * 2, y1 + r_val * 2],
                fill=(rng.randint(80, 160), rng.randint(80, 160), rng.randint(80, 160)),
            )

        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16
            )
        except Exception:
            try:
                font = ImageFont.truetype("arial.ttf", 16)
            except Exception:
                font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx, ty = (self.tile_size - tw) // 2, (self.tile_size - th) // 2
        padding = 6
        draw.rounded_rectangle(
            [tx - padding, ty - padding, tx + tw + padding, ty + th + padding],
            radius=6, fill=(20, 20, 20),
        )
        draw.text((tx, ty), label, font=font, fill=(255, 255, 255))
        return img

    def _resize_square(self, img: Image.Image) -> Image.Image:
        w, h = img.size
        min_side = min(w, h)
        left, top = (w - min_side) // 2, (h - min_side) // 2
        img = img.crop((left, top, left + min_side, top + min_side))
        return img.resize((self.tile_size, self.tile_size), Image.Resampling.LANCZOS)

    def _img_to_b64(self, img: Image.Image) -> str:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82)
        return base64.b64encode(buf.getvalue()).decode("utf-8")


    def generate(self) -> Dict[str, Any]:
        rng = random.Random(self.config.get("_generation_seed"))
        category = rng.choice(CATEGORIES)
        self._target_label = category["label"]
        if self.difficulty == "easy":
            target_query = category.get("query_easy", category["query"])
        elif self.difficulty == "hard":
            target_query = category.get("query_hard", category["query"])
        else:
            target_query = category["query"]
        distractors = category["distractors"]
        distractor_labels = category.get("distractor_labels", [None, None])


        min_c, max_c = self.correct_count_range
        correct_count = rng.randint(
            min(min_c, self.total_tiles - 1),
            min(max_c, self.total_tiles - 1),
        )
        neg_count = self.total_tiles - correct_count
        neg_count_a = (neg_count + 1) // 2
        neg_count_b = neg_count - neg_count_a

        neg_query_a = distractors[0]
        neg_query_b = distractors[1] if len(distractors) > 1 else distractors[0]
        neg_label_a = distractor_labels[0] if len(distractor_labels) > 0 else None
        neg_label_b = distractor_labels[1] if len(distractor_labels) > 1 else None


        image_rngs = [random.Random(rng.getrandbits(64)) for _ in range(3)]
        with ThreadPoolExecutor(max_workers=3) as ex:
            f_pos = ex.submit(self._get_images_for_category,
                              self._target_label, target_query, correct_count, image_rngs[0])
            f_neg_a = ex.submit(self._get_images_for_category,
                                neg_label_a, neg_query_a, neg_count_a, image_rngs[1])
            f_neg_b = ex.submit(self._get_images_for_category,
                                neg_label_b, neg_query_b, neg_count_b, image_rngs[2])
            pos_imgs = f_pos.result()
            neg_imgs = f_neg_a.result() + f_neg_b.result()


        pos_ready: List[Image.Image] = []
        for img in pos_imgs[:correct_count]:
            if img is None:
                img = self._make_fallback_tile(self._target_label, is_correct=True, rng=rng)
            else:
                img = self._resize_square(img)
                img = img.filter(ImageFilter.GaussianBlur(radius=0.3))
            pos_ready.append(img)
        while len(pos_ready) < correct_count:
            pos_ready.append(self._make_fallback_tile(self._target_label, is_correct=True, rng=rng))

        neg_labels_fb = [neg_query_a] * neg_count_a + [neg_query_b] * neg_count_b
        neg_ready: List[Image.Image] = []
        for i, img in enumerate(neg_imgs[:neg_count]):
            if img is None:
                img = self._make_fallback_tile(neg_labels_fb[i], is_correct=False, rng=rng)
            else:
                img = self._resize_square(img)
                img = img.filter(ImageFilter.GaussianBlur(radius=0.3))
            neg_ready.append(img)
        while len(neg_ready) < neg_count:
            neg_ready.append(
                self._make_fallback_tile(neg_labels_fb[len(neg_ready)], is_correct=False, rng=rng)
            )


        combined = [(img, True) for img in pos_ready] + [(img, False) for img in neg_ready]
        rng.shuffle(combined)

        self._correct_indices = sorted(i for i, (_, is_c) in enumerate(combined) if is_c)
        self._tiles_b64 = [self._img_to_b64(img) for img, _ in combined]
        self._answer = ",".join(str(i) for i in self._correct_indices)
        self._generated = True

        return {
            "target_label": self._target_label,
            "correct_indices": self._correct_indices,
            "total_tiles": self.total_tiles,
        }


    def render_html(self) -> str:
        if not self._generated:
            self.generate()

        tiles_json = json.dumps(self._tiles_b64, ensure_ascii=False)
        cols = self.grid_cols
        max_grid_width = self.grid_cols * self.tile_size + (self.grid_cols - 1) * 6 + 16
        if self.difficulty == "easy":
            instruction = "Select the image with"
            extra_hint = '<div style="color: #059669; font-size: 12px; margin-top: 4px; font-weight: 600;">There is only 1 correct image</div>'
        else:
            instruction = "Select all images with"
            extra_hint = ""

        return f"""
        <div class="img-grid-captcha" style="user-select:none;">

            <div style="
                text-align: center;
                margin-bottom: 14px;
                padding: 12px 16px;
                background: linear-gradient(135deg, #f0f9ff, #e0f2fe);
                border-radius: 10px;
                border: 1px solid #bae6fd;
            ">
                <div style="color: #6b7280; font-size: 13px; margin-bottom: 4px;">
                    {instruction}
                </div>
                <div style="
                    color: #1e40af;
                    font-weight: 700;
                    font-size: 20px;
                    letter-spacing: 0.5px;
                    text-transform: capitalize;
                ">{self._target_label}</div>
                {extra_hint}
            </div>

            <div id="img-grid" style="
                display: grid;
                grid-template-columns: repeat({cols}, minmax(0, 1fr));
                gap: 6px;
                margin: 0 auto;
                width: min(100%, {max_grid_width}px);
                padding: 8px;
                background: #f1f5f9;
                border-radius: 12px;
                border: 1px solid #e2e8f0;
            "></div>

            <div style="text-align: center; margin-top: 10px; font-size: 13px; color: #64748b;">
                <span id="img-grid-status">Click on all matching images, then click Verify</span>
            </div>

            <input type="hidden" id="captcha-input" name="captcha" value="" />
        </div>

        <script>
        (function() {{
            const tiles = {tiles_json};
            const grid = document.getElementById('img-grid');
            const input = document.getElementById('captcha-input');
            const status = document.getElementById('img-grid-status');
            const selected = new Set();

            function updateInput() {{
                const sorted = Array.from(selected).sort((a, b) => a - b);
                input.value = sorted.join(',');
                status.textContent = selected.size === 0
                    ? 'Click on all matching images, then click Verify'
                    : selected.size + ' image(s) selected';
                status.style.color = selected.size === 0 ? '#64748b' : '#059669';
            }}

            function renderGrid() {{
                grid.innerHTML = '';
                tiles.forEach(function(b64, idx) {{
                    const isSel = selected.has(idx);
                    const cell = document.createElement('div');
                    cell.style.cssText = `
                        position:relative;width:100%;aspect-ratio:1 / 1;
                        border-radius:8px;overflow:hidden;cursor:pointer;
                        border:${{isSel ? '3px solid #10b981' : '2px solid #cbd5e1'}};
                        box-shadow:${{isSel
                            ? '0 0 0 2px rgba(16,185,129,0.3),0 4px 12px rgba(0,0,0,0.15)'
                            : '0 2px 6px rgba(0,0,0,0.08)'}};
                        transition:border-color .15s,box-shadow .15s,transform .1s;
                        box-sizing:border-box;
                        touch-action: manipulation;
                    `;

                    const img = document.createElement('img');
                    img.src = 'data:image/jpeg;base64,' + b64;
                    img.style.cssText = `
                        width:100%;height:100%;object-fit:cover;display:block;
                        pointer-events:none;
                        ${{isSel ? 'filter:brightness(0.82);' : ''}}
                    `;
                    img.draggable = false;
                    cell.appendChild(img);

                    if (isSel) {{
                        const check = document.createElement('div');
                        check.style.cssText = `
                            position:absolute;inset:0;display:flex;
                            align-items:center;justify-content:center;
                            background:rgba(16,185,129,0.22);pointer-events:none;
                        `;
                        check.innerHTML = `<svg width="36" height="36" viewBox="0 0 36 36"
                            fill="none" xmlns="http://www.w3.org/2000/svg">
                            <circle cx="18" cy="18" r="16" fill="rgba(16,185,129,0.85)"/>
                            <polyline points="10,18 16,24 26,12" stroke="white"
                                stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>`;
                        cell.appendChild(check);
                    }}

                    cell.addEventListener('mouseenter', function() {{
                        if (!selected.has(idx)) {{
                            cell.style.transform = 'scale(1.03)';
                            cell.style.borderColor = '#94a3b8';
                        }}
                    }});
                    cell.addEventListener('mouseleave', function() {{
                        cell.style.transform = '';
                        cell.style.borderColor = selected.has(idx) ? '#10b981' : '#cbd5e1';
                    }});
                    cell.addEventListener('click', function() {{
                        selected.has(idx) ? selected.delete(idx) : selected.add(idx);
                        updateInput();
                        renderGrid();
                    }});

                    grid.appendChild(cell);
                }});
            }}

            renderGrid();
            updateInput();
        }})();
        </script>
        """


    def verify(self, user_input: Any) -> CaptchaResult:
        text = str(user_input).strip() if user_input is not None else ""
        user_indices: Set[int] = set()

        if text:
            try:
                for part in text.split(","):
                    part = part.strip()
                    if part:
                        val = int(part)
                        if 0 <= val < self.total_tiles:
                            user_indices.add(val)
                        else:
                            raise ValueError(f"Index {val} out of range")
            except ValueError:
                return CaptchaResult(
                    success=False,
                    message="Invalid selection. Please try again.",
                    expected=self._answer,
                    received=text,
                )

        if not user_indices:
            return CaptchaResult(
                success=False,
                message="Please select at least one image.",
                expected=self._answer,
                received=text,
            )

        if user_indices == set(self._correct_indices):
            return CaptchaResult(
                success=True,
                message="Verification successful!",
                expected=self._answer,
                received=",".join(str(i) for i in sorted(user_indices)),
            )

        return CaptchaResult(
            success=False,
            message="Incorrect selection. Please try again.",
            expected=self._answer,
            received=",".join(str(i) for i in sorted(user_indices)),
        )
