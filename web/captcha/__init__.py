from .base import BaseCaptcha, CaptchaResult, CaptchaType
from .text_captcha import TextCaptcha
from .slider_real_captcha import SliderRealCaptcha
from .slider_real_dynamic_captcha import SliderRealDynamicCaptcha
from .click_icon_captcha import ClickIconCaptcha
from .click_icon_dynamic_captcha import ClickIconDynamicCaptcha
from .click_real_captcha import ClickRealCaptcha
from .click_real_dynamic_captcha import ClickRealDynamicCaptcha
from .puzzle_real_captcha import PuzzleRealCaptcha
from .puzzle_real_dynamic_captcha import PuzzleRealDynamicCaptcha
from .pic_puzzle_captcha import PicPuzzleCaptcha
from .pic_puzzle_dynamic_captcha import PicPuzzleDynamicCaptcha
from .image_grid_captcha import ImageGridCaptcha
from .image_grid_dynamic_captcha import ImageGridDynamicCaptcha
from .missing_piece_captcha import MissingPieceCaptcha
from .missing_piece_dynamic_captcha import MissingPieceDynamicCaptcha
from .logic_arithmetic_captcha import LogicArithmeticCaptcha
from .logic_arithmetic_dynamic_captcha import LogicArithmeticDynamicCaptcha
from .five_line_captcha import FiveLineCaptcha
from .five_line_dynamic_captcha import FiveLineDynamicCaptcha
from .distraction_layer import DistractionMixin


def create_distraction_captcha(base_class, distraction_level: int = 1, **kwargs):
    if distraction_level == 0:
        return base_class(**kwargs)

    class DistractionCaptcha(DistractionMixin, base_class):
        pass

    return DistractionCaptcha(distraction_level=distraction_level, **kwargs)
