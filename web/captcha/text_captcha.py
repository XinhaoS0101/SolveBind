import random
import string
import base64
import io
from typing import Any, Dict, Optional
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import html as html_escape

from .base import BaseCaptcha, CaptchaType, CaptchaResult


class TextCaptcha(BaseCaptcha):


    DEFAULT_CHARS = "3479ACDEFGHJKLMNPQRTUVWXY"

    def __init__(self, **kwargs):
        super().__init__(CaptchaType.TEXT, **kwargs)

        self.length = kwargs.get("length", 4)
        self.width = kwargs.get("width", 180)
        self.height = kwargs.get("height", 70)
        self.font_size = kwargs.get("font_size", 40)
        self.chars = kwargs.get("chars", self.DEFAULT_CHARS)
        self.noise_dots = kwargs.get("noise_dots", 150)
        self.noise_lines = kwargs.get("noise_lines", 6)
        self.case_sensitive = kwargs.get("case_sensitive", False)

        self._image_base64: Optional[str] = None

    def generate(self) -> Dict[str, Any]:

        self._answer = "".join(random.choices(self.chars, k=self.length))


        image = self._create_image()


        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        self._image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        self._generated = True

        return {
            "type": "text",
            "image_base64": self._image_base64,
            "length": self.length,
        }

    def _create_image(self) -> Image.Image:

        bg_color = self._random_light_color()
        image = Image.new("RGB", (self.width, self.height), bg_color)
        draw = ImageDraw.Draw(image)


        font = self._get_font()


        self._draw_noise_lines(draw)


        self._draw_text(draw, font)


        self._draw_noise_dots(draw)


        image = image.filter(ImageFilter.SMOOTH)

        return image

    def _get_font(self) -> ImageFont.FreeTypeFont:
        font_paths = [
            "/System/Library/Fonts/Helvetica.ttc",  
            "/System/Library/Fonts/Arial.ttf",       
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",  
            "C:\\Windows\\Fonts\\arial.ttf",         
            "C:\\Windows\\Fonts\\Arial.ttf",         
        ]

        for path in font_paths:
            try:
                return ImageFont.truetype(path, self.font_size)
            except (IOError, OSError):
                continue


        return ImageFont.load_default()

    def _random_light_color(self) -> tuple:
        return (
            random.randint(220, 255),
            random.randint(220, 255),
            random.randint(220, 255),
        )

    def _random_dark_color(self) -> tuple:
        return (
            random.randint(0, 100),
            random.randint(0, 100),
            random.randint(0, 100),
        )

    def _random_color(self) -> tuple:
        return (
            random.randint(50, 200),
            random.randint(50, 200),
            random.randint(50, 200),
        )

    def _draw_text(self, draw: ImageDraw.Draw, font: ImageFont.FreeTypeFont) -> None:

        char_width = self.width // (self.length + 1)

        for i, char in enumerate(self._answer):

            x = char_width * (i + 0.5) + random.randint(-5, 5)
            y = (self.height - self.font_size) // 2 + random.randint(-8, 8)


            color = self._random_dark_color()


            draw.text((x, y), char, font=font, fill=color)

    def _draw_noise_lines(self, draw: ImageDraw.Draw) -> None:
        for _ in range(self.noise_lines):
            x1 = random.randint(0, self.width)
            y1 = random.randint(0, self.height)
            x2 = random.randint(0, self.width)
            y2 = random.randint(0, self.height)
            color = self._random_color()
            draw.line([(x1, y1), (x2, y2)], fill=color, width=random.randint(1, 2))

    def _draw_noise_dots(self, draw: ImageDraw.Draw) -> None:
        for _ in range(self.noise_dots):
            x = random.randint(0, self.width - 1)
            y = random.randint(0, self.height - 1)
            color = self._random_color()
            draw.point((x, y), fill=color)

    def render_html(self) -> str:
        if not self._generated:
            self.generate()

        return f"""
        <div class="captcha-image-container" style="text-align: center; margin-bottom: 16px;">
          <img 
            src="data:image/png;base64,{self._image_base64}" 
            alt="Captcha Image" 
            style="border-radius: 8px; border: 2px solid #e5e7eb; max-width: 100%;"
            id="captcha-image"
          />
        </div>
        <div class="field">
          <label for="captcha-input">Enter the characters shown above</label>
          <input 
            type="text" 
            id="captcha-input" 
            name="captcha" 
            placeholder="Enter {self.length} characters"
            maxlength="{self.length + 2}"
            autocomplete="off"
            autocapitalize="characters"
            style="text-transform: uppercase; letter-spacing: 4px; text-align: center; font-size: 20px;"
          />
        </div>
        """

    def verify(self, user_input: Any) -> CaptchaResult:
        if not self._generated or self._answer is None:
            return CaptchaResult(
                success=False,
                message="Captcha not generated. Please refresh the page.",
            )

        user_str = str(user_input).strip()
        expected = self._answer

        if not self.case_sensitive:
            user_str = user_str.upper()
            expected = expected.upper()

        if user_str == expected:
            return CaptchaResult(
                success=True,
                message="Verification successful!",
                expected=self._answer,
                received=str(user_input).strip(),
            )
        else:
            return CaptchaResult(
                success=False,
                message="Incorrect captcha. Please try again.",
                expected=self._answer,
                received=str(user_input).strip(),
            )
