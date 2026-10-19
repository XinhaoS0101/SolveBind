from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional
from enum import Enum


class CaptchaType(Enum):
    TEXT = "text"                  
    TEXT_TRACE = "text_trace"                 
    MATH = "math"                    
    SLIDER = "slider"              
    CLICK = "click"                
    CLICK_ANYWHERE = "click_anywhere"           
    CLICK_TRACE = "click_trace"              
    ROTATE = "rotate"              
    PUZZLE = "puzzle"              
    FIVE_LINE = "five_line"           


@dataclass
class CaptchaResult:
    success: bool
    message: str
    expected: Optional[str] = None
    received: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class BaseCaptcha(ABC):

    def __init__(self, captcha_type: CaptchaType, **kwargs):
        self.captcha_type = captcha_type
        self.config = kwargs
        self._answer: Optional[str] = None
        self._generated: bool = False

    @abstractmethod
    def generate(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def render_html(self) -> str:
        pass

    @abstractmethod
    def verify(self, user_input: Any) -> CaptchaResult:
        pass

    def get_answer(self) -> Optional[str]:
        return self._answer

    def get_type(self) -> CaptchaType:
        return self.captcha_type

    def is_generated(self) -> bool:
        return self._generated

    def get_page_title(self) -> str:
        return self.config.get("title", "Captcha Verification")

    def get_page_description(self) -> str:
        return self.config.get("description", "Please complete the verification below.")

    def render_full_page(self) -> str:
        if not self._generated:
            self.generate()

        captcha_html = self.render_html()
        title = self.get_page_title()
        description = self.get_page_description()

        return self._build_page_template(title, description, captcha_html)

    def _build_page_template(self, title: str, description: str, captcha_html: str) -> str:
        import html as html_escape

        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{html_escape.escape(title)}</title>
  <style>
    :root {{ --gap: 16px; --radius: 16px; --primary: #4f46e5; --primary-hover: #4338ca; }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; 
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: #111827; 
      line-height: 1.6;
      display: grid; 
      place-items: center; 
      min-height: 100vh; 
      padding: 24px;
    }}
    .card {{
      width: 100%; 
      max-width: 480px; 
      background: #fff; 
      border-radius: var(--radius);
      box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25); 
      padding: 32px; 
      border: 1px solid #e5e7eb;
    }}
    h1 {{ 
      margin: 0 0 8px; 
      font-size: 24px; 
      font-weight: 700;
      color: #1f2937;
    }}
    p.desc {{ 
      margin: 0 0 24px; 
      color: #6b7280; 
      font-size: 14px; 
    }}
    .captcha-container {{
      margin-bottom: 20px;
    }}
    .field {{ 
      margin-bottom: var(--gap); 
    }}
    label {{ 
      display: block; 
      font-size: 14px; 
      color: #374151; 
      margin-bottom: 6px;
      font-weight: 500;
    }}
    input[type="text"] {{
      width: 100%; 
      padding: 12px 14px; 
      border: 2px solid #e5e7eb; 
      border-radius: 12px;
      font-size: 16px; 
      outline: none; 
      background: #fff;
      transition: border-color .2s ease, box-shadow .2s ease;
    }}
    input[type="text"]:focus {{ 
      border-color: var(--primary); 
      box-shadow: 0 0 0 4px rgba(79,70,229,0.1); 
    }}
    .actions {{ 
      display: flex; 
      gap: 12px; 
      margin-top: 24px; 
    }}
    button {{
      flex: 1;
      appearance: none; 
      border: none; 
      border-radius: 12px; 
      padding: 14px 20px; 
      cursor: pointer;
      font-weight: 600; 
      font-size: 15px;
      transition: all .2s ease;
    }}
    .btn-primary {{ 
      background: var(--primary); 
      color: #fff; 
    }}
    .btn-primary:hover {{
      background: var(--primary-hover);
      transform: translateY(-1px);
    }}
    .btn-secondary {{ 
      background: #f3f4f6; 
      color: #374151; 
    }}
    .btn-secondary:hover {{
      background: #e5e7eb;
    }}

    
    .modal {{
      position: fixed; 
      inset: 0; 
      display: none; 
      place-items: center;
      background: rgba(17,24,39,.6); 
      padding: 24px; 
      z-index: 50;
      backdrop-filter: blur(4px);
    }}
    .modal.show {{ display: grid; }}
    .modal-card {{
      width: 100%; 
      max-width: 400px; 
      background: #fff; 
      border-radius: 20px;
      padding: 32px; 
      box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);
      text-align: center;
    }}
    .modal-icon {{
      width: 64px;
      height: 64px;
      margin: 0 auto 16px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 32px;
    }}
    .modal-icon.success {{
      background: #d1fae5;
      color: #059669;
    }}
    .modal-icon.error {{
      background: #fee2e2;
      color: #dc2626;
    }}
    .modal-card h2 {{ 
      margin: 0 0 8px; 
      font-size: 22px;
      color: #1f2937;
    }}
    .modal-card p {{ 
      margin: 0 0 24px; 
      color: #6b7280; 
      font-size: 14px; 
    }}
    .modal-actions {{ 
      display: flex; 
      gap: 12px;
      justify-content: center; 
    }}
    .modal-actions button {{
      min-width: 120px;
    }}
    
    footer {{ 
      margin-top: 20px; 
      text-align: center; 
      color: #9ca3af; 
      font-size: 12px; 
    }}
  </style>
</head>
<body>
  <main class="card">
    <h1>{html_escape.escape(title)}</h1>
    <p class="desc">{html_escape.escape(description)}</p>

    <form id="captcha-form" method="post" action="/verify" novalidate>
      <div class="captcha-container">
        {captcha_html}
      </div>
      <div class="actions">
        <button type="submit" class="btn-primary">Verify</button>
        <button type="button" class="btn-secondary" id="refresh-btn">Refresh</button>
      </div>
    </form>

    <footer>Captcha Verification System</footer>
  </main>

  
  <div id="result-modal" class="modal" role="dialog" aria-modal="true">
    <div class="modal-card">
      <div class="modal-icon" id="modal-icon">✓</div>
      <h2 id="modal-title">Result</h2>
      <p id="modal-message">Message</p>
      <div class="modal-actions">
        <button type="button" class="btn-primary" id="modal-ok">OK</button>
        <button type="button" class="btn-secondary" id="modal-retry" style="display:none;">Try Again</button>
      </div>
    </div>
  </div>

  <script>
    (function() {{
      const form = document.getElementById('captcha-form');
      const modal = document.getElementById('result-modal');
      const modalIcon = document.getElementById('modal-icon');
      const modalTitle = document.getElementById('modal-title');
      const modalMessage = document.getElementById('modal-message');
      const modalOk = document.getElementById('modal-ok');
      const modalRetry = document.getElementById('modal-retry');
      const refreshBtn = document.getElementById('refresh-btn');

      function showModal(success, title, message) {{
        modalIcon.className = 'modal-icon ' + (success ? 'success' : 'error');
        modalIcon.textContent = success ? '✓' : '✗';
        modalTitle.textContent = title;
        modalMessage.textContent = message;
        modalRetry.style.display = success ? 'none' : 'inline-block';
        modal.classList.add('show');
      }}

      function hideModal() {{
        modal.classList.remove('show');
      }}

      form.addEventListener('submit', function(e) {{
        e.preventDefault();
        const formData = new FormData(form);
        const body = new URLSearchParams();
        for (const [key, value] of formData.entries()) {{
          body.append(key, value == null ? '' : String(value));
        }}
        
        fetch('/verify', {{
          method: 'POST',
          headers: {{
            'Content-Type': 'application/x-www-form-urlencoded',
          }},
          body: body.toString()
        }})
        .then(r => r.json())
        .then(data => {{
          showModal(data.success, data.success ? 'Success!' : 'Failed', data.message);
        }})
        .catch(err => {{
          console.error('Verify error:', err);
          showModal(false, 'Error', 'Verification failed. Please try again.');
        }});
      }});

      refreshBtn.addEventListener('click', function() {{
        window.location.href = '/refresh';
      }});

      modalOk.addEventListener('click', function() {{
        hideModal();
        window.location.href = '/refresh';
      }});

      modalRetry.addEventListener('click', function() {{
        hideModal();
        window.location.href = '/refresh';
      }});

      modal.addEventListener('click', function(e) {{
        if (e.target === modal) hideModal();
      }});

      document.addEventListener('keydown', function(e) {{
        if (e.key === 'Escape') hideModal();
      }});
    }})();
  </script>
</body>
</html>"""
