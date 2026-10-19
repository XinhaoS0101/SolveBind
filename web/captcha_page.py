import json
import random
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from typing import Optional, Dict, Any, Type, Callable

from .captcha_feedback import safe_verification_feedback
from .captcha import (
    BaseCaptcha,
    CaptchaResult,
    TextCaptcha,
    SliderRealCaptcha,
    SliderRealDynamicCaptcha,
    ClickIconCaptcha,
    ClickIconDynamicCaptcha,
    ClickRealCaptcha,
    ClickRealDynamicCaptcha,
    PuzzleRealCaptcha,
    PuzzleRealDynamicCaptcha,
    PicPuzzleCaptcha,
    PicPuzzleDynamicCaptcha,
    ImageGridCaptcha,
    ImageGridDynamicCaptcha,
    MissingPieceCaptcha,
    MissingPieceDynamicCaptcha,
    LogicArithmeticDynamicCaptcha,
    FiveLineCaptcha,
    FiveLineDynamicCaptcha,
    create_distraction_captcha,
)


_CAPTCHA_RANDOM_LOCK = Lock()


class CaptchaSession:

    def __init__(
        self,
        captcha_factory: Callable[[], BaseCaptcha],
        seed: Optional[int] = None,
    ):
        self._factory = captcha_factory
        self._seed = int(seed) if seed is not None else None
        self._generation_index = 0
        self._captcha: Optional[BaseCaptcha] = None
        self._next_captcha: Optional[BaseCaptcha] = None
        self._lock = Lock()
        self._prefetch_lock = Lock()
        self._verification_count = 0
        self._success_count = 0
        self._page_view_count = 0
        self._last_verification: Dict[str, Any] = {}

    def _do_prefetch(self) -> None:
        try:
            cap = self._build_generated()
            with self._lock:
                self._next_captcha = cap
        except Exception as e:
            print(f"[CaptchaSession] Prefetch failed: {e}")
        finally:
            try:
                self._prefetch_lock.release()
            except RuntimeError:
                pass

    def prefetch(self) -> None:
        if self._prefetch_lock.acquire(blocking=False):
            Thread(target=self._do_prefetch, daemon=True).start()

    def get_or_create(self) -> BaseCaptcha:
        with self._lock:
            if self._captcha is not None:
                return self._captcha

        cap = self._build_generated()
        with self._lock:
            if self._captcha is None:
                self._captcha = cap
            result = self._captcha
        self.prefetch()
        return result

    def refresh(self) -> BaseCaptcha:
        with self._lock:
            next_cap = self._next_captcha
            if next_cap is not None:
                self._next_captcha = None
                self._captcha = next_cap
            self._last_verification = {}
        if next_cap is None:
            next_cap = self._build_generated()
            with self._lock:
                self._captcha = next_cap
        self.prefetch()
        return next_cap

    def _build_generated(self) -> BaseCaptcha:
        if self._seed is None:
            cap = self._factory()
            cap.generate()
            return cap

        with _CAPTCHA_RANDOM_LOCK:
            previous_state = random.getstate()
            challenge_seed = self._seed + self._generation_index
            self._generation_index += 1
            random.seed(challenge_seed)
            try:
                cap = self._factory()
                cap.config["_generation_seed"] = challenge_seed
                cap.generate()
                return cap
            finally:
                random.setstate(previous_state)

    def verify(self, user_input: Any, trap_input: Optional[str] = None) -> CaptchaResult:
        with self._lock:
            self._verification_count += 1
            if self._captcha is None:
                result = CaptchaResult(
                    success=False,
                    message="No captcha generated. Please refresh.",
                )
            elif trap_input and hasattr(self._captcha, 'distraction_level') and self._captcha.distraction_level > 0:
                result = self._captcha.verify(user_input, trap_input=trap_input)
            else:
                result = self._captcha.verify(user_input)
            if result.success:
                self._success_count += 1
            self._last_verification = safe_verification_feedback(
                result,
                attempt=self._verification_count,
            )
            return result

    def get_answer(self) -> Optional[str]:
        with self._lock:
            if self._captcha:
                return self._captcha.get_answer()
            return None

    def get_stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "page_views": self._page_view_count,
                "total_verifications": self._verification_count,
                "successful_verifications": self._success_count,
            }

    def get_verification_feedback(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._last_verification)

    def record_page_view(self) -> None:
        with self._lock:
            self._page_view_count += 1


def create_captcha_handler(session: CaptchaSession, debug: bool = False):

    class CaptchaHandler(BaseHTTPRequestHandler):

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

            if path in ("/", "/index.html"):
                self._serve_captcha_page()
            elif path == "/refresh":
                self._serve_captcha_page(refresh=True)
            elif path == "/api/answer" and debug:
                self._serve_answer()
            elif path == "/api/stats":
                self._serve_stats()
            else:
                self._send_404()

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

            if path == "/verify":
                self._handle_verify()
            else:
                self._send_404()

        def _serve_captcha_page(self, refresh: bool = False):
            if refresh:
                captcha = session.refresh()
            else:
                captcha = session.get_or_create()
            session.record_page_view()

            html = captcha.render_full_page()

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))

        def _handle_verify(self):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")


            form_data = urllib.parse.parse_qs(body)
            user_input = form_data.get("captcha", [""])[0]
            trap_input = form_data.get("captcha_trap", [""])[0]


            result = session.verify(user_input, trap_input=trap_input)


            response = {
                "success": result.success,
                "message": result.message,
            }
            if debug:
                response["expected"] = result.expected
                response["received"] = result.received

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode("utf-8"))


            session.prefetch()

        def _serve_answer(self):
            answer = session.get_answer()
            response = {"answer": answer}

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode("utf-8"))

        def _serve_stats(self):
            stats = session.get_stats()

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(stats).encode("utf-8"))

        def _send_404(self):
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"404 Not Found")

        def log_message(self, fmt, *args):
            print(f"[CaptchaServer] {self.address_string()} - {fmt % args}")

    return CaptchaHandler


def start_captcha_server(
    captcha_type: str = "text",
    captcha_config: Optional[Dict[str, Any]] = None,
    host: str = "0.0.0.0",
    port: int = 8000,
    debug: bool = True,
) -> None:
    config = captcha_config or {}


    factory = _create_captcha_factory(captcha_type, config)
    session = CaptchaSession(factory, seed=config.get("seed"))
    handler = create_captcha_handler(session, debug=debug)

    httpd = ThreadingHTTPServer((host, port), handler)
    print(
        f"[CaptchaServer] Starting {captcha_type} captcha server at http://{host}:{port}"
    )
    if debug:
        print(f"[CaptchaServer] Debug mode enabled - answer available at /api/answer")
    print(f"[CaptchaServer] Press Ctrl+C to stop")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        print("\n[CaptchaServer] Stopped.")


def start_captcha_server_in_thread(
    captcha_type: str = "text",
    captcha_config: Optional[Dict[str, Any]] = None,
    host: str = "0.0.0.0",
    port: int = 8000,
    debug: bool = True,
) -> tuple:
    config = captcha_config or {}

    factory = _create_captcha_factory(captcha_type, config)
    session = CaptchaSession(factory, seed=config.get("seed"))
    handler = create_captcha_handler(session, debug=debug)

    httpd = ThreadingHTTPServer((host, port), handler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    print(
        f"[CaptchaServer] Started {captcha_type} captcha server at http://{host}:{port}"
    )
    if debug:
        print(f"[CaptchaServer] Debug mode - answer at /api/answer")

    return httpd, thread, session


def _create_captcha_factory(
    captcha_type: str, config: Dict[str, Any]
) -> Callable[[], BaseCaptcha]:

    captcha_classes: Dict[str, Type[BaseCaptcha]] = {
        "text": TextCaptcha,
        "slider_real": SliderRealCaptcha,
        "slider_real_dynamic": SliderRealDynamicCaptcha,
        "click_icon": ClickIconCaptcha,
        "click_icon_dynamic": ClickIconDynamicCaptcha,
        "click_real": ClickRealCaptcha,
        "click_real_dynamic": ClickRealDynamicCaptcha,
        "puzzle_real": PuzzleRealCaptcha,
        "puzzle_real_dynamic": PuzzleRealDynamicCaptcha,
        "pic_puzzle": PicPuzzleCaptcha,
        "pic_puzzle_dynamic": PicPuzzleDynamicCaptcha,
        "image_grid": ImageGridCaptcha,
        "image_grid_dynamic": ImageGridDynamicCaptcha,
        "missing_piece": MissingPieceCaptcha,
        "missing_piece_dynamic": MissingPieceDynamicCaptcha,
        "logic_arithmetic_dynamic": LogicArithmeticDynamicCaptcha,
        "five_line": FiveLineCaptcha,
        "five_line_dynamic": FiveLineDynamicCaptcha,
    }

    distraction_level = config.get("distraction_level", 0)
    config = {k: v for k, v in config.items() if k != "distraction_level"}

    if captcha_type in {"logic_arithmetic", "logic_arithmetic_dynamic"}:
        from .captcha.logic_arithmetic_extended import ExtendedLogicArithmeticCaptcha

        logic_class: Type[BaseCaptcha]
        if captcha_type == "logic_arithmetic_dynamic":
            class ExtendedLogicArithmeticDynamicCaptcha(
                LogicArithmeticDynamicCaptcha, ExtendedLogicArithmeticCaptcha
            ):
                pass

            logic_class = ExtendedLogicArithmeticDynamicCaptcha
        else:
            logic_class = ExtendedLogicArithmeticCaptcha

        def logic_factory() -> BaseCaptcha:
            if distraction_level > 0:
                return create_distraction_captcha(
                    logic_class,
                    distraction_level=distraction_level,
                    **config
                )
            return logic_class(**config)

        return logic_factory

    captcha_class = captcha_classes.get(captcha_type)
    if captcha_class is None:
        raise ValueError(
            f"Unknown captcha type: {captcha_type}. Available: {list(captcha_classes.keys())}"
        )

    def factory() -> BaseCaptcha:
        if distraction_level > 0:
            return create_distraction_captcha(
                captcha_class,
                distraction_level=distraction_level,
                **config
            )
        return captcha_class(**config)

    return factory


def main() -> None:

    import argparse
    from pathlib import Path
    from hll.cli import CAPTCHA_TYPES
    from hll.captcha.task_config import build_task_config, default_asset_root

    parser = argparse.ArgumentParser(description="SolveBind local verification server")
    parser.add_argument("--type", choices=CAPTCHA_TYPES, default="text")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--length", type=int, default=4)
    parser.add_argument("--difficulty", choices=("easy", "normal", "hard"), default="normal")
    parser.add_argument("--distraction-level", type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument("--asset-root", type=Path, default=default_asset_root())
    args = parser.parse_args()
    config = build_task_config(
        args.type, difficulty=args.difficulty, distraction_level=args.distraction_level,
        text_length=args.length, seed=args.seed, asset_root=args.asset_root,
    )
    start_captcha_server(captcha_type=args.type, captcha_config=config, host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
