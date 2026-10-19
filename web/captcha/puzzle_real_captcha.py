import random
import base64
import io
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageStat

from .base import BaseCaptcha, CaptchaType, CaptchaResult


class PuzzleRealCaptcha(BaseCaptcha):

    SUPPORTED_FORMATS = {'.jpg', '.jpeg', '.png', '.webp'}

    def __init__(
        self,
        image_dir: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        width: int = 300,
        height: int = 180,
        piece_size: int = 50,
        tolerance: int = 8,
        difficulty: Optional[str] = None,
        **kwargs
    ):
        super().__init__(CaptchaType.PUZZLE, **kwargs)
        self.width = width
        self.height = height
        self.piece_size = piece_size
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

        self._target_x: int = 0
        self._target_y: int = 0
        self._bg_image: str = ""
        self._piece_image: str = ""
        self._current_image_path: Optional[Path] = None
        self._contrast_score: float = 0.0
        self._difficulty_level: str = "normal"
        self._effective_tolerance: int = self.tolerance
        self._manual_difficulty: Optional[str] = None
        if difficulty is not None:
            d = str(difficulty).strip().lower()
            if d == "medium":
                d = "normal"
            if d not in {"easy", "normal", "hard"}:
                raise ValueError("difficulty must be one of: easy, normal, hard")
            self._manual_difficulty = d

    def _estimate_local_contrast(self, image: Image.Image, center_x: int, center_y: int) -> float:
        gray = image.convert('L')
        half = max(self.piece_size, 24)
        left = max(0, center_x - half)
        top = max(0, center_y - half)
        right = min(self.width, center_x + half)
        bottom = min(self.height, center_y + half)
        crop = gray.crop((left, top, right, bottom))
        std = ImageStat.Stat(crop).stddev[0]
        return float(std / 64.0)

    def _grade_difficulty_by_contrast(self, contrast_score: float) -> Tuple[str, int]:
        base = self.tolerance
        if contrast_score < 0.28:
            return "hard", min(base + 3, 16)
        if contrast_score < 0.42:
            return "normal", base
        return "easy", max(base - 2, 4)

    def _grade_difficulty_by_manual(self, difficulty: str) -> Tuple[str, int]:
        base = self.tolerance
        if difficulty == "hard":
            return "hard", max(base - 2, 4)
        if difficulty == "easy":
            return "easy", min(base + 3, 16)
        return "normal", base

    def _pick_target_position(self, image: Image.Image, difficulty_hint: Optional[str]) -> Tuple[int, int, float]:
        margin = 60
        min_x = margin
        max_x = self.width - self.piece_size - margin - 20
        min_y = margin
        max_y = self.height - self.piece_size - margin

        if max_x < min_x:
            min_x, max_x = 0, max(0, self.width - self.piece_size - 20)
        if max_y < min_y:
            min_y, max_y = 0, max(0, self.height - self.piece_size)

        gray = image.convert('L')
        grid_cols = 5
        grid_rows = 3
        cell_w = max(self.width // grid_cols, self.piece_size + 8)
        cell_h = max(self.height // grid_rows, self.piece_size + 8)

        blocks: List[Tuple[int, int, int, int, float]] = []
        for r in range(grid_rows):
            for c in range(grid_cols):
                left = c * (self.width // grid_cols)
                top = r * (self.height // grid_rows)
                right = self.width if c == grid_cols - 1 else min(self.width, left + cell_w)
                bottom = self.height if r == grid_rows - 1 else min(self.height, top + cell_h)
                if right - left < self.piece_size + 4 or bottom - top < self.piece_size + 4:
                    continue
                crop = gray.crop((left, top, right, bottom))
                score = float(ImageStat.Stat(crop).stddev[0])
                blocks.append((left, top, right, bottom, score))

        if not blocks:
            x = random.randint(min_x, max_x)
            y = random.randint(min_y, max_y)
            score = self._estimate_local_contrast(
                image,
                x + self.piece_size // 2,
                y + self.piece_size // 2,
            )
            return x, y, score

        blocks.sort(key=lambda b: b[4])
        n = len(blocks)
        if difficulty_hint is None:
            candidate_blocks = blocks
        elif difficulty_hint == "hard":
            candidate_blocks = blocks[:max(1, int(n * 0.15))]
        elif difficulty_hint == "easy":
            candidate_blocks = blocks[-max(1, int(n * 0.15)):]
        else:
            lo = max(0, int(n * 0.40))
            hi = min(n, max(lo + 1, int(n * 0.60)))
            candidate_blocks = blocks[lo:hi]

        block_scores = [b[4] for b in candidate_blocks]
        score_min = min(block_scores)
        score_max = max(block_scores)

        def _sample_once() -> Tuple[int, int, float]:
            b_left, b_top, b_right, b_bottom, _ = random.choice(candidate_blocks)
            local_min_x = max(min_x, b_left)
            local_max_x = min(max_x, b_right - self.piece_size)
            local_min_y = max(min_y, b_top)
            local_max_y = min(max_y, b_bottom - self.piece_size)
            if local_max_x < local_min_x or local_max_y < local_min_y:
                x = random.randint(min_x, max_x)
                y = random.randint(min_y, max_y)
            else:
                x = random.randint(local_min_x, local_max_x)
                y = random.randint(local_min_y, local_max_y)
            s = self._estimate_local_contrast(
                image,
                x + self.piece_size // 2,
                y + self.piece_size // 2,
            )
            return x, y, s

        best: Optional[Tuple[int, int, float]] = None
        for _ in range(20):
            x, y, s = _sample_once()
            best = (x, y, s)
            if difficulty_hint == "hard":
                upper = score_min + 0.60 * (score_max - score_min + 1e-6)
                if s <= upper:
                    return x, y, s
            elif difficulty_hint == "easy":
                lower = score_min + 0.40 * (score_max - score_min + 1e-6)
                if s >= lower:
                    return x, y, s
            else:
                lower = score_min + 0.25 * (score_max - score_min + 1e-6)
                upper = score_min + 0.75 * (score_max - score_min + 1e-6)
                if lower <= s <= upper:
                    return x, y, s

        if best is not None:
            return best
        return _sample_once()

    def _scan_image_dir(self, image_dir: str) -> None:
        dir_path = Path(image_dir)
        if not dir_path.exists():
            print(f"[Warning] Image directory not found: {image_dir}")
            return

        for file_path in dir_path.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_FORMATS:
                self._image_paths.append(file_path)

        print(f"[PuzzleRealCaptcha] Found {len(self._image_paths)} images in {image_dir}")

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

    def _create_puzzle_mask(self, size: int) -> Image.Image:
        mask = Image.new('L', (size + 20, size + 20), 0)
        draw = ImageDraw.Draw(mask)

        offset = 10

        draw.rectangle([offset, offset, offset + size, offset + size], fill=255)


        bump_radius = size // 5
        bump_center_x = offset + size
        bump_center_y = offset + size // 2
        draw.ellipse([
            bump_center_x - bump_radius,
            bump_center_y - bump_radius,
            bump_center_x + bump_radius,
            bump_center_y + bump_radius
        ], fill=255)


        notch_center_x = offset + size // 2
        notch_center_y = offset
        draw.ellipse([
            notch_center_x - bump_radius,
            notch_center_y - bump_radius,
            notch_center_x + bump_radius,
            notch_center_y + bump_radius
        ], fill=0)

        return mask

    def generate(self) -> Dict[str, Any]:

        self._current_image_path = random.choice(self._image_paths)
        bg_img = self._load_and_resize_image(self._current_image_path)


        self._target_x, self._target_y, self._contrast_score = self._pick_target_position(
            bg_img, self._manual_difficulty
        )
        if self._manual_difficulty is not None:
            self._difficulty_level, self._effective_tolerance = self._grade_difficulty_by_manual(
                self._manual_difficulty
            )
        else:
            self._difficulty_level, self._effective_tolerance = self._grade_difficulty_by_contrast(
                self._contrast_score
            )


        mask = self._create_puzzle_mask(self.piece_size)
        mask_offset = 10


        piece_img = Image.new('RGBA', (self.piece_size + 20, self.piece_size + 20), (0, 0, 0, 0))


        for y in range(self.piece_size + 20):
            for x in range(self.piece_size + 20):
                src_x = self._target_x - mask_offset + x
                src_y = self._target_y - mask_offset + y
                if 0 <= src_x < self.width and 0 <= src_y < self.height:
                    if mask.getpixel((x, y)) > 128:
                        pixel = bg_img.getpixel((src_x, src_y))
                        piece_img.putpixel((x, y), pixel + (255,))


        for y in range(self.piece_size + 20):
            for x in range(self.piece_size + 20):
                if mask.getpixel((x, y)) > 128:
                    is_edge = False
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < self.piece_size + 20 and 0 <= ny < self.piece_size + 20:
                            if mask.getpixel((nx, ny)) <= 128:
                                is_edge = True
                                break
                        else:
                            is_edge = True
                            break
                    if is_edge:
                        piece_img.putpixel((x, y), (255, 255, 255, 255))


        bg_rgba = bg_img.convert('RGBA')
        for y in range(self.piece_size + 20):
            for x in range(self.piece_size + 20):
                src_x = self._target_x - mask_offset + x
                src_y = self._target_y - mask_offset + y
                if 0 <= src_x < self.width and 0 <= src_y < self.height:
                    if mask.getpixel((x, y)) > 128:
                        bg_rgba.putpixel((src_x, src_y), (50, 50, 50, 180))


        bg_final = Image.new('RGB', (self.width, self.height), (255, 255, 255))
        bg_final.paste(bg_rgba, (0, 0), bg_rgba)


        bg_buffer = io.BytesIO()
        bg_final.save(bg_buffer, format='PNG')
        self._bg_image = base64.b64encode(bg_buffer.getvalue()).decode()

        piece_buffer = io.BytesIO()
        piece_img.save(piece_buffer, format='PNG')
        self._piece_image = base64.b64encode(piece_buffer.getvalue()).decode()

        self._answer = f"{self._target_x},{self._target_y}"
        self._generated = True

        return {
            "bg_image": self._bg_image,
            "piece_image": self._piece_image,
            "target_x": self._target_x,
            "target_y": self._target_y,
            "width": self.width,
            "height": self.height,
            "piece_size": self.piece_size,
            "source_image": str(self._current_image_path) if self._current_image_path else None,
            "difficulty": self._difficulty_level,
            "contrast_score": round(self._contrast_score, 4),
            "effective_tolerance": self._effective_tolerance,
        }

    def render_html(self) -> str:
        if not self._generated:
            self.generate()

        piece_width = self.piece_size + 20
        piece_height = self.piece_size + 20

        aspect_ratio = round(self.width / self.height, 4)
        piece_w_pct = round(piece_width / self.width * 100, 2)
        piece_h_pct = round(piece_height / self.height * 100, 2)
        init_left_pct = round(10 / self.width * 100, 2)
        init_top_pct = round((self.height - piece_height) / 2 / self.height * 100, 2)
        return f'''
        <div class="puzzle-captcha" style="user-select: none; width: min(100%, {self.width}px); margin: 0 auto;">
            <div class="puzzle-image-container" id="puzzle-container" style="position: relative; width: 100%; aspect-ratio: {aspect_ratio}; margin: 0 auto; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.2);">
                <img src="data:image/png;base64,{self._bg_image}" style="width: 100%; height: 100%; display: block;" draggable="false" />
                <div id="puzzle-piece" style="position: absolute; left: {init_left_pct}%; top: {init_top_pct}%; width: {piece_w_pct}%; height: {piece_h_pct}%; cursor: grab; filter: drop-shadow(2px 2px 4px rgba(0,0,0,0.4));">
                    <img src="data:image/png;base64,{self._piece_image}" style="width: 100%; height: 100%;" draggable="false" />
                </div>
            </div>
            <div style="text-align: center; margin-top: 12px; color: #6b7280; font-size: 13px;">
                <span id="puzzle-hint">Drag the puzzle piece to complete the image</span>
            </div>
            <input type="hidden" id="captcha-input" name="captcha" value="10,{(self.height - piece_height) // 2}" />
        </div>
        <script>
        (function() {{
            const piece = document.getElementById('puzzle-piece');
            const input = document.getElementById('captcha-input');
            const container = document.getElementById('puzzle-container');
            const nominalWidth = {self.width};
            const nominalHeight = {self.height};
            const nominalPieceWidth = {piece_width};
            const nominalPieceHeight = {piece_height};
            
            let isDragging = false;
            let startMouseX = 0, startMouseY = 0;
            let startPieceX = 10, startPieceY = {(self.height - piece_height) // 2};
            let currentX = startPieceX, currentY = startPieceY;

            function getScale() {{
                return container.offsetWidth / nominalWidth;
            }}

            function updatePosition(x, y) {{
                const scale = getScale();
                const maxX = nominalWidth - nominalPieceWidth;
                const maxY = nominalHeight - nominalPieceHeight;
                x = Math.max(0, Math.min(x, maxX));
                y = Math.max(0, Math.min(y, maxY));
                piece.style.left = (x / nominalWidth * 100) + '%';
                piece.style.top = (y / nominalHeight * 100) + '%';
                currentX = x;
                currentY = y;
                const actualX = Math.round(x + 10);
                const actualY = Math.round(y + 10);
                input.value = actualX + ',' + actualY;
            }}

            piece.addEventListener('mousedown', function(e) {{
                isDragging = true;
                startMouseX = e.clientX;
                startMouseY = e.clientY;
                startPieceX = currentX;
                startPieceY = currentY;
                piece.style.cursor = 'grabbing';
                e.preventDefault();
            }});

            document.addEventListener('mousemove', function(e) {{
                if (!isDragging) return;
                const scale = getScale();
                const dx = (e.clientX - startMouseX) / scale;
                const dy = (e.clientY - startMouseY) / scale;
                updatePosition(startPieceX + dx, startPieceY + dy);
            }});

            document.addEventListener('mouseup', function() {{
                if (isDragging) {{
                    isDragging = false;
                    piece.style.cursor = 'grab';
                }}
            }});

            piece.addEventListener('touchstart', function(e) {{
                isDragging = true;
                startMouseX = e.touches[0].clientX;
                startMouseY = e.touches[0].clientY;
                startPieceX = currentX;
                startPieceY = currentY;
                e.preventDefault();
            }}, {{ passive: false }});

            document.addEventListener('touchmove', function(e) {{
                if (!isDragging) return;
                e.preventDefault();
                const scale = getScale();
                const dx = (e.touches[0].clientX - startMouseX) / scale;
                const dy = (e.touches[0].clientY - startMouseY) / scale;
                updatePosition(startPieceX + dx, startPieceY + dy);
            }}, {{ passive: false }});

            document.addEventListener('touchend', function() {{
                isDragging = false;
            }});
        }})();
        </script>
        '''

    def verify(self, user_input: Any) -> CaptchaResult:
        try:
            parts = str(user_input).split(',')
            user_x = int(parts[0])
            user_y = int(parts[1])
        except (ValueError, TypeError, IndexError):
            return CaptchaResult(
                success=False,
                message="Invalid input format",
                expected=self._answer,
                received=str(user_input)
            )

        diff_x = abs(user_x - self._target_x)
        diff_y = abs(user_y - self._target_y)

        tol = self._effective_tolerance
        if diff_x <= tol and diff_y <= tol:
            return CaptchaResult(
                success=True,
                message="Verification successful! Puzzle completed.",
                expected=self._answer,
                received=str(user_input),
                extra={
                    "diff_x": diff_x,
                    "diff_y": diff_y,
                    "difficulty": self._difficulty_level,
                    "contrast_score": round(self._contrast_score, 4),
                    "tolerance": tol,
                }
            )
        else:
            return CaptchaResult(
                success=False,
                message="Puzzle piece not in the correct position. Please try again.",
                expected=self._answer,
                received=str(user_input),
                extra={
                    "diff_x": diff_x,
                    "diff_y": diff_y,
                    "difficulty": self._difficulty_level,
                    "contrast_score": round(self._contrast_score, 4),
                    "tolerance": tol,
                }
            )

    def get_available_images(self) -> List[str]:
        return [str(p) for p in self._image_paths]

    def get_current_image(self) -> Optional[str]:
        return str(self._current_image_path) if self._current_image_path else None
