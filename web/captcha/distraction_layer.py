from __future__ import annotations

import html
import random
import uuid
from typing import Any, Dict, List, Optional

from .base import BaseCaptcha, CaptchaResult


WEBPAGE_THEMES = [
    "shopping",
    "search",
    "social",
    "email_register",
]

CAPTCHA_POSITIONS = ["center", "top-left", "top-right"]


def _generate_random_text(words: int = 8) -> str:
    word_pool = [
        "secure",
        "delivery",
        "workspace",
        "results",
        "trusted",
        "members",
        "verified",
        "quality",
        "support",
        "setup",
        "insights",
        "faster",
        "modern",
        "workflow",
        "privacy",
        "productivity",
        "recommendations",
        "sharing",
        "updates",
        "community",
    ]
    return " ".join(random.choices(word_pool, k=words)).capitalize() + "."


def _sample_items(pool: List[Any], count: int) -> List[Any]:
    if count >= len(pool):
        shuffled = list(pool)
        random.shuffle(shuffled)
        return shuffled
    return random.sample(pool, count)


def _build_shopping_theme(_: str) -> Dict[str, Any]:
    product_pool = [
        {
            "title": "Aurora Wireless Headphones",
            "price": "$149",
            "badge": "Best Seller",
            "rating": "4.8",
            "delivery": "Free delivery tomorrow",
        },
        {
            "title": "Minimal Desk Lamp",
            "price": "$59",
            "badge": "New Arrival",
            "rating": "4.7",
            "delivery": "Ships in 24 hours",
        },
        {
            "title": "Magnetic Laptop Stand",
            "price": "$79",
            "badge": "Editor Pick",
            "rating": "4.9",
            "delivery": "Free pickup available",
        },
        {
            "title": "Compact Mechanical Keyboard",
            "price": "$119",
            "badge": "Limited Deal",
            "rating": "4.6",
            "delivery": "2-year warranty included",
        },
    ]
    return {
        "brand_name": random.choice(["Northstar Market", "NovaCart", "Urban Shelf", "Craft Lane"]),
        "accent": "#2563eb",
        "surface": "#eff6ff",
        "nav_items": ["New", "Best Sellers", "Workspace", "Audio", "Accessories"],
        "categories": ["Monitors", "Keyboards", "Lighting", "Furniture", "Travel", "Deals"],
        "hero_kicker": "Spring workspace edit",
        "hero_title": "Upgrade your desk with faster delivery and cleaner design",
        "hero_copy": "Curated accessories, member-only pricing and quick shipping across the items people actually use every day.",
        "promo_note": "Extra 15% off bundles over $120",
        "search_placeholder": "Search products, brands and deals",
        "products": _sample_items(product_pool, 4),
        "highlights": [
            "Free returns within 30 days",
            "Member pricing on selected items",
            "Secure checkout with saved addresses",
        ],
        "collections": ["Desk Setup", "Remote Work", "Audio Upgrade"],
    }


def _build_search_theme(_: str) -> Dict[str, Any]:
    results_pool = [
        {
            "title": "Best desk setup ideas for small spaces",
            "url": "layoutlab.design/small-space-setups",
            "snippet": "A practical guide to compact desk layouts, cable routing and lighting choices that keep a workspace productive without feeling crowded.",
        },
        {
            "title": "Mechanical keyboard buying guide",
            "url": "switchnotes.dev/keyboard-guide",
            "snippet": "Compare switch types, layouts and noise levels before choosing a board for coding, writing and everyday office work.",
        },
        {
            "title": "How to choose a monitor for remote work",
            "url": "displayreview.io/remote-monitor-guide",
            "snippet": "Screen size, USB-C charging, brightness and ergonomics explained with recommendations for common budget ranges.",
        },
        {
            "title": "Noise-cancelling headphones comparison",
            "url": "soundlens.com/headphone-comparison",
            "snippet": "A side-by-side breakdown of battery life, comfort and microphone quality for hybrid work and travel.",
        },
    ]
    query = random.choice(
        [
            "best workspace accessories 2026",
            "how to improve desk setup",
            "email productivity tools",
            "wireless headphones for office use",
        ]
    )
    return {
        "brand_name": random.choice(["Queryly", "Findr", "Atlas Search", "Nova Search"]),
        "accent": "#0f766e",
        "surface": "#ecfeff",
        "query": query,
        "tabs": ["All", "Images", "Videos", "Shopping", "News"],
        "filters": ["Past 24 hours", "Top results", "Verified sources", "English"],
        "results": _sample_items(results_pool, 4),
        "questions": [
            "What accessories improve desk comfort?",
            "How large should a work monitor be?",
            "Which apps help manage email overload?",
        ],
        "knowledge_title": "Quick summary",
        "knowledge_copy": _generate_random_text(10),
    }


def _build_social_theme(_: str) -> Dict[str, Any]:
    post_pool = [
        {
            "user": "Maya Chen",
            "handle": "@mayaworks",
            "time": "2h",
            "text": "Finished a tiny desk refresh today. The biggest win was moving chargers into one tray and adding a warmer lamp.",
            "likes": "342",
            "comments": "18",
        },
        {
            "user": "Noah Reed",
            "handle": "@reednotes",
            "time": "4h",
            "text": "Trying a single-task afternoon: notifications off, inbox closed, one document open. It feels suspiciously effective.",
            "likes": "521",
            "comments": "43",
        },
        {
            "user": "Sofia Park",
            "handle": "@sofialabs",
            "time": "6h",
            "text": "Small reminder: you probably do not need another productivity app. You might need a better system for using the ones you already have.",
            "likes": "807",
            "comments": "67",
        },
    ]
    suggestions = [
        {"name": "Luca Hart", "role": "Product designer"},
        {"name": "Ava Brooks", "role": "Remote work coach"},
        {"name": "Theo Lim", "role": "Ops lead"},
    ]
    return {
        "brand_name": random.choice(["Loop Social", "Circle Feed", "Pulse", "Neighborly"]),
        "accent": "#2563eb",
        "surface": "#eff6ff",
        "nav_items": ["Home", "Explore", "Messages", "Bookmarks"],
        "left_menu": ["For you", "Following", "Communities", "Saved", "Events"],
        "composer_prompt": "Share an update with your network",
        "posts": _sample_items(post_pool, 3),
        "suggestions": suggestions,
        "trends": ["#workspace", "#emailtips", "#remotehabits", "#focusmode"],
    }


def _build_email_register_theme(_: str) -> Dict[str, Any]:
    return {
        "brand_name": random.choice(["MailNest", "Inboxly", "CloudMail", "Northmail"]),
        "accent": "#7c3aed",
        "surface": "#f5f3ff",
        "nav_items": ["Features", "Security", "Pricing", "Help"],
        "headline": "Create a secure inbox that keeps work and life organized",
        "subheadline": "Sign up in minutes, sync across devices and get spam protection, priority filters and collaborative labels from day one.",
        "benefits": [
            "End-to-end encrypted sign-in flow",
            "Smart inbox rules and alias support",
            "Calendar and file storage included",
        ],
        "trust_points": ["99.99% uptime", "SOC 2 ready", "24/7 account recovery support"],
        "aside_title": "Why teams switch",
        "aside_copy": _generate_random_text(11),
    }


class DistractionMixin:

    distraction_level: int = 0
    _trap_clicked: bool = False
    _trap_element_id: Optional[str] = None

    def __init__(self, *args, distraction_level: int = 0, **kwargs):
        self.distraction_level = distraction_level
        self._trap_clicked = False
        self._trap_element_id = None
        self._captcha_position = "center"
        self._theme_name = "shopping"
        self._session_id = str(uuid.uuid4())[:8]
        self._decoy_counter = 0
        super().__init__(*args, **kwargs)

    def generate(self) -> Dict[str, Any]:
        result = super().generate()

        if self.distraction_level > 0:
            self._theme_name = random.choice(WEBPAGE_THEMES)
            self._decoy_counter = 0
            if self.distraction_level >= 2:
                self._captcha_position = random.choice(CAPTCHA_POSITIONS)
            else:
                self._captcha_position = "center"

        return result

    def _trap_enabled(self) -> bool:
        return self.distraction_level >= 2

    def _decoy_attrs(self, element_type: str, label: str) -> str:
        if not self._trap_enabled():
            return ""
        self._decoy_counter += 1
        element_id = f"decoy-{self._session_id}-{self._decoy_counter}"
        return (
            f' id="{html.escape(element_id, quote=True)}"'
            f' data-decoy="true"'
            f' data-decoy-type="{html.escape(element_type, quote=True)}"'
            f' data-decoy-label="{html.escape(label, quote=True)}"'
        )

    def _render_nav_link(self, label: str, extra_class: str = "") -> str:
        class_name = f"surface-link {extra_class}".strip()
        return (
            f'<a href="#" class="{class_name}"'
            f'{self._decoy_attrs("navigation", label)}>{html.escape(label)}</a>'
        )

    def _render_button(
        self,
        label: str,
        *,
        style: str = "primary",
        extra_class: str = "",
        element_type: str = "button",
    ) -> str:
        class_name = f"surface-button {style} {extra_class}".strip()
        return (
            f'<button type="button" class="{class_name}"'
            f'{self._decoy_attrs(element_type, label)}>{html.escape(label)}</button>'
        )

    def _render_input(
        self,
        placeholder: str,
        *,
        extra_class: str = "",
        input_type: str = "text",
        label: Optional[str] = None,
    ) -> str:
        class_name = f"surface-input {extra_class}".strip()
        element_label = label or placeholder
        return (
            f'<input type="{html.escape(input_type, quote=True)}"'
            f' class="{class_name}"'
            f' placeholder="{html.escape(placeholder, quote=True)}"'
            f' autocomplete="off"'
            f'{self._decoy_attrs("input", element_label)} />'
        )

    def _render_distraction_styles(self) -> str:
        return """
<style>
:root {
    color-scheme: light;
}
* {
    box-sizing: border-box;
}
body {
    margin: 0;
    font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: #0f172a;
    line-height: 1.5;
    background: #e8edf5;
}
a {
    color: inherit;
    text-decoration: none;
}
button,
input {
    font: inherit;
}
.distraction-page {
    min-height: 100vh;
    background:
        radial-gradient(circle at top left, rgba(255, 255, 255, 0.78), transparent 32%),
        linear-gradient(180deg, #f7f9fc 0%, #eef2f7 100%);
}
.page-shell {
    width: min(1280px, calc(100vw - 48px));
    margin: 0 auto;
}
.surface-card {
    background: rgba(255, 255, 255, 0.9);
    border: 1px solid rgba(148, 163, 184, 0.18);
    box-shadow: 0 22px 50px -34px rgba(15, 23, 42, 0.28);
}
.surface-link {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: #475569;
    font-size: 14px;
    font-weight: 500;
}
.surface-link:hover {
    color: var(--scene-accent, #2563eb);
}
.surface-pill {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 34px;
    padding: 0 14px;
    border-radius: 999px;
    background: #fff;
    border: 1px solid rgba(148, 163, 184, 0.22);
    color: #475569;
    font-size: 13px;
    font-weight: 600;
    box-shadow: 0 10px 28px -24px rgba(15, 23, 42, 0.3);
}
.surface-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-height: 42px;
    padding: 0 16px;
    border: 0;
    border-radius: 12px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 700;
    transition: transform .16s ease, box-shadow .16s ease, opacity .16s ease;
}
.surface-button:hover {
    transform: translateY(-1px);
}
.surface-button.primary {
    background: var(--scene-accent, #2563eb);
    color: #fff;
    box-shadow: 0 20px 30px -22px color-mix(in srgb, var(--scene-accent, #2563eb) 70%, #0f172a 30%);
}
.surface-button.secondary {
    background: #fff;
    color: #0f172a;
    border: 1px solid rgba(148, 163, 184, 0.22);
}
.surface-button.ghost {
    background: color-mix(in srgb, var(--scene-soft, #eff6ff) 78%, #fff 22%);
    color: var(--scene-accent, #2563eb);
}
.surface-input {
    width: 100%;
    min-height: 44px;
    padding: 0 14px;
    border-radius: 12px;
    border: 1px solid rgba(148, 163, 184, 0.24);
    background: rgba(255, 255, 255, 0.94);
    color: #0f172a;
    outline: none;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.65);
}
.surface-input:focus {
    border-color: color-mix(in srgb, var(--scene-accent, #2563eb) 55%, white 45%);
    box-shadow: 0 0 0 4px color-mix(in srgb, var(--scene-accent, #2563eb) 15%, white 85%);
}
.section-title {
    margin: 0 0 16px;
    font-size: 18px;
    font-weight: 800;
    color: #0f172a;
}
.muted {
    color: #64748b;
}
.mini-label {
    color: var(--scene-accent, #2563eb);
    font-size: 12px;
    font-weight: 800;
    letter-spacing: .08em;
    text-transform: uppercase;
}
.scene-header {
    width: 100%;
    border-bottom: 1px solid rgba(148, 163, 184, 0.15);
    background: rgba(255, 255, 255, 0.8);
}
.scene-header-inner {
    width: min(1280px, calc(100vw - 48px));
    margin: 0 auto;
    min-height: 72px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 20px;
}
.scene-brand {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    font-size: 20px;
    font-weight: 800;
    color: #0f172a;
}
.scene-brand-mark {
    width: 34px;
    height: 34px;
    border-radius: 11px;
    background: linear-gradient(135deg, var(--scene-accent, #2563eb), color-mix(in srgb, var(--scene-accent, #2563eb) 55%, #ffffff 45%));
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.45);
}
.scene-header-nav,
.scene-inline-list {
    display: flex;
    align-items: center;
    gap: 18px;
    flex-wrap: wrap;
}
.shopping-scene,
.search-scene,
.social-scene,
.register-scene {
    padding-bottom: 42px;
}
.shopping-toolbar {
    display: grid;
    grid-template-columns: 220px minmax(0, 1fr) auto;
    gap: 16px;
    align-items: center;
    padding: 16px 0 12px;
}
.searchbar-shell {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 52px;
    padding: 8px;
    border-radius: 18px;
    background: rgba(255,255,255,0.94);
    border: 1px solid rgba(148, 163, 184, 0.18);
    box-shadow: 0 28px 44px -38px rgba(15, 23, 42, 0.28);
}
.searchbar-shell .surface-input {
    border: 0;
    box-shadow: none;
    min-height: 36px;
}
.category-row,
.filter-row {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    padding: 0 0 18px;
}
.shopping-hero {
    display: grid;
    grid-template-columns: minmax(0, 1.35fr) minmax(280px, .85fr);
    gap: 28px;
    padding: 34px;
    border-radius: 28px;
    background:
        radial-gradient(circle at top right, color-mix(in srgb, var(--scene-soft, #eff6ff) 88%, #fff 12%), transparent 38%),
        linear-gradient(145deg, rgba(255,255,255,0.96), rgba(248,250,252,0.92));
}
.shopping-hero h1,
.register-copy h1 {
    margin: 10px 0 14px;
    font-size: clamp(32px, 5vw, 48px);
    line-height: 1.05;
    letter-spacing: -.03em;
}
.shopping-hero p,
.register-copy p {
    margin: 0;
    color: #475569;
    font-size: 16px;
    max-width: 60ch;
}
.hero-actions {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin-top: 24px;
}
.hero-note {
    margin-top: 20px;
    display: inline-flex;
    gap: 10px;
    align-items: center;
    color: #334155;
    font-weight: 600;
}
.hero-aside {
    display: grid;
    gap: 16px;
    align-content: start;
}
.highlight-list,
.clean-list {
    list-style: none;
    padding: 0;
    margin: 0;
}
.highlight-list li,
.clean-list li {
    padding: 12px 0;
    border-bottom: 1px solid rgba(148, 163, 184, 0.16);
    color: #334155;
}
.highlight-list li:last-child,
.clean-list li:last-child {
    border-bottom: 0;
}
.shopping-grid {
    display: grid;
    grid-template-columns: 260px minmax(0, 1fr);
    gap: 22px;
    margin-top: 24px;
}
.sidebar-panel,
.content-panel,
.result-card,
.feed-card,
.register-card,
.insight-card {
    border-radius: 22px;
    padding: 22px;
}
.shop-product-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 18px;
}
.shop-product {
    border-radius: 20px;
    overflow: hidden;
    border: 1px solid rgba(148, 163, 184, 0.16);
    background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(248,250,252,0.92));
    box-shadow: 0 20px 36px -34px rgba(15, 23, 42, 0.32);
}
.shop-product-thumb {
    aspect-ratio: 1.16 / 1;
    background:
        radial-gradient(circle at top left, rgba(255,255,255,0.55), transparent 32%),
        linear-gradient(135deg, color-mix(in srgb, var(--scene-soft, #eff6ff) 74%, #ffffff 26%), #ffffff);
}
.shop-product-body {
    padding: 16px;
}
.shop-product-title {
    font-size: 16px;
    font-weight: 800;
    color: #0f172a;
}
.shop-product-meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin: 10px 0 6px;
}
.shop-price {
    font-size: 20px;
    font-weight: 800;
    color: #0f172a;
}
.shop-rating {
    color: #475569;
    font-size: 13px;
    font-weight: 700;
}
.shop-badge {
    display: inline-flex;
    padding: 6px 10px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--scene-soft, #eff6ff) 85%, #fff 15%);
    color: var(--scene-accent, #2563eb);
    font-size: 12px;
    font-weight: 800;
}
.shop-actions {
    display: flex;
    gap: 10px;
    margin-top: 14px;
}
.collection-strip {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin-top: 16px;
}
.search-hero {
    padding-top: 28px;
}
.search-mainbar {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 320px;
    gap: 24px;
    margin-top: 20px;
}
.search-tabs {
    display: flex;
    gap: 16px;
    align-items: center;
    padding: 16px 0 14px;
    border-bottom: 1px solid rgba(148, 163, 184, 0.16);
}
.search-result-list {
    display: grid;
    gap: 16px;
}
.result-card .result-url {
    color: #0f766e;
    font-size: 13px;
    font-weight: 700;
}
.result-card h3 {
    margin: 8px 0;
    font-size: 22px;
    line-height: 1.25;
}
.result-card p {
    margin: 0;
    color: #475569;
    font-size: 14px;
}
.result-actions {
    display: flex;
    gap: 12px;
    margin-top: 16px;
}
.search-side-stack {
    display: grid;
    gap: 18px;
}
.social-layout {
    display: grid;
    grid-template-columns: 240px minmax(0, 1fr) 300px;
    gap: 20px;
    padding-top: 24px;
}
.social-composer {
    display: grid;
    gap: 14px;
}
.avatar-row,
.post-user {
    display: flex;
    align-items: center;
    gap: 12px;
}
.avatar {
    width: 42px;
    height: 42px;
    border-radius: 50%;
    background: linear-gradient(135deg, var(--scene-accent, #2563eb), color-mix(in srgb, var(--scene-accent, #2563eb) 55%, #fff 45%));
    color: #fff;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    font-weight: 800;
}
.feed-card {
    display: grid;
    gap: 14px;
}
.feed-card p {
    margin: 0;
    color: #334155;
}
.feed-actions {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}
.left-nav-list {
    display: grid;
    gap: 8px;
}
.left-nav-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 11px 12px;
    border-radius: 14px;
    color: #334155;
    font-weight: 600;
}
.left-nav-item:hover {
    background: color-mix(in srgb, var(--scene-soft, #eff6ff) 85%, #fff 15%);
}
.trend-item,
.suggestion-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px 0;
    border-bottom: 1px solid rgba(148, 163, 184, 0.15);
}
.trend-item:last-child,
.suggestion-item:last-child {
    border-bottom: 0;
}
.register-hero {
    display: grid;
    grid-template-columns: minmax(0, 1.12fr) minmax(340px, .88fr);
    gap: 24px;
    padding-top: 32px;
}
.register-copy {
    padding: 32px;
    border-radius: 28px;
    background:
        radial-gradient(circle at top right, color-mix(in srgb, var(--scene-soft, #f5f3ff) 85%, #fff 15%), transparent 42%),
        linear-gradient(140deg, rgba(255,255,255,0.97), rgba(248,250,252,0.92));
}
.register-card {
    background: rgba(255,255,255,0.95);
}
.form-stack {
    display: grid;
    gap: 14px;
}
.field-block {
    display: grid;
    gap: 7px;
}
.field-block label {
    font-size: 13px;
    font-weight: 700;
    color: #334155;
}
.subtle-panel {
    border-radius: 18px;
    padding: 16px;
    background: color-mix(in srgb, var(--scene-soft, #f5f3ff) 74%, #fff 26%);
    border: 1px solid rgba(148, 163, 184, 0.12);
}
.register-side-notes {
    display: grid;
    gap: 16px;
}
.cta-row {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}
.distraction-footer {
    border-top: 1px solid rgba(148, 163, 184, 0.14);
    margin-top: 36px;
    background: rgba(255,255,255,0.72);
}
.distraction-footer .page-shell {
    min-height: 66px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    color: #64748b;
    font-size: 13px;
}
.footer-links {
    display: flex;
    gap: 18px;
    flex-wrap: wrap;
}
.captcha-overlay {
    position: fixed;
    inset: 0;
    z-index: 20;
    pointer-events: none;
    padding: 24px;
    overflow-y: auto;
    overscroll-behavior: contain;
    -webkit-overflow-scrolling: touch;
}
.captcha-overlay.position-center {
    display: grid;
    place-items: center;
}
.captcha-overlay.position-top-left {
    display: flex;
    justify-content: flex-start;
    align-items: flex-start;
}
.captcha-overlay.position-top-right {
    display: flex;
    justify-content: flex-end;
    align-items: flex-start;
}
.captcha-overlay::before {
    content: "";
    position: absolute;
    inset: 0;
    background: rgba(15, 23, 42, 0.18);
}
.captcha-dialog {
    position: relative;
    z-index: 1;
    width: min(560px, calc(100vw - 48px));
    pointer-events: auto;
}
.captcha-wrapper {
    width: 100%;
    padding: 28px;
    border-radius: 24px;
    background: rgba(255,255,255,0.96);
    border: 1px solid rgba(226, 232, 240, 0.92);
    box-shadow: 0 36px 64px -32px rgba(15, 23, 42, 0.52);
}
.captcha-wrapper h3 {
    margin: 0 0 8px;
    font-size: 24px;
    color: #0f172a;
}
.captcha-wrapper p.captcha-desc {
    margin: 0 0 20px;
    color: #64748b;
    font-size: 14px;
}
.captcha-stage {
    width: 100%;
    min-width: 0;
}
.captcha-actions {
    display: flex;
    gap: 12px;
    margin-top: 24px;
}
.captcha-actions button {
    flex: 1;
    appearance: none;
    border: none;
    border-radius: 14px;
    padding: 14px 20px;
    cursor: pointer;
    font-size: 15px;
    font-weight: 700;
    transition: transform .18s ease, opacity .18s ease;
}
.captcha-actions button:hover {
    transform: translateY(-1px);
}
.captcha-actions .btn-primary {
    background: #4f46e5;
    color: #fff;
}
.captcha-actions .btn-secondary {
    background: #f3f4f6;
    color: #334155;
}
.modal {
    position: fixed;
    inset: 0;
    display: none;
    place-items: center;
    background: rgba(15, 23, 42, 0.58);
    z-index: 50;
    padding: 24px;
}
.modal.show {
    display: grid;
}
.modal-card {
    width: 100%;
    max-width: 420px;
    padding: 32px;
    border-radius: 24px;
    background: rgba(255,255,255,0.98);
    text-align: center;
    box-shadow: 0 28px 58px -28px rgba(15, 23, 42, 0.46);
}
.modal-icon {
    width: 64px;
    height: 64px;
    margin: 0 auto 16px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 32px;
}
.modal-icon.success {
    background: #dcfce7;
    color: #15803d;
}
.modal-icon.error {
    background: #fee2e2;
    color: #dc2626;
}
.modal-card h2 {
    margin: 0 0 8px;
    font-size: 22px;
}
.modal-card p {
    margin: 0 0 24px;
    color: #64748b;
    font-size: 14px;
}
.modal-actions {
    display: flex;
    justify-content: center;
    gap: 12px;
}
.modal-actions button {
    min-width: 120px;
}
@media (max-width: 1024px) {
    .shopping-grid,
    .search-mainbar,
    .social-layout,
    .register-hero,
    .shopping-hero {
        grid-template-columns: 1fr;
    }
    .shop-product-grid {
        grid-template-columns: 1fr 1fr;
    }
}
@media (max-width: 768px) {
    .page-shell,
    .scene-header-inner {
        width: min(100vw - 24px, 1280px);
    }
    .scene-header-inner,
    .shopping-toolbar {
        grid-template-columns: 1fr;
        flex-direction: column;
        align-items: stretch;
        gap: 14px;
    }
    .scene-header-inner {
        display: flex;
        min-height: auto;
        padding: 14px 0;
    }
    .scene-header-nav {
        width: 100%;
        overflow-x: auto;
        padding-bottom: 2px;
    }
    .shop-product-grid {
        grid-template-columns: 1fr;
    }
    .captcha-overlay {
        padding: 12px;
    }
    .captcha-overlay.position-center,
    .captcha-overlay.position-top-left,
    .captcha-overlay.position-top-right {
        display: flex;
        justify-content: center;
        align-items: flex-start;
    }
    .captcha-dialog {
        width: min(560px, calc(100vw - 24px));
        margin-top: 8px;
    }
    .captcha-wrapper {
        padding: 18px;
        border-radius: 18px;
    }
    .captcha-actions,
    .modal-actions,
    .hero-actions,
    .shop-actions,
    .result-actions,
    .cta-row {
        flex-direction: column;
    }
    .distraction-footer .page-shell {
        min-height: auto;
        padding: 16px 0;
        align-items: flex-start;
        flex-direction: column;
    }
}
</style>
"""

    def _render_footer(self) -> str:
        return f"""
<footer class="distraction-footer">
    <div class="page-shell">
        <div class="footer-links">
            {self._render_nav_link("Privacy")}
            {self._render_nav_link("Terms")}
            {self._render_nav_link("Help")}
            {self._render_nav_link("Status")}
        </div>
        <span>© 2026 HLL Demo Surfaces</span>
    </div>
</footer>
"""

    def _render_shopping_page(self, theme: Dict[str, Any]) -> str:
        nav_html = "".join(self._render_nav_link(item) for item in theme["nav_items"])
        category_html = "".join(
            f'<a href="#" class="surface-pill"{self._decoy_attrs("category", item)}>{html.escape(item)}</a>'
            for item in theme["categories"]
        )
        highlights_html = "".join(
            f"<li>{html.escape(item)}</li>" for item in theme["highlights"]
        )
        collections_html = "".join(
            f'<span class="surface-pill">{html.escape(item)}</span>'
            for item in theme["collections"]
        )

        product_cards = []
        for product in theme["products"]:
            product_cards.append(
                f"""
<article class="shop-product">
    <div class="shop-product-thumb"></div>
    <div class="shop-product-body">
        <span class="shop-badge">{html.escape(product['badge'])}</span>
        <div class="shop-product-title" style="margin-top: 12px;">{html.escape(product['title'])}</div>
        <div class="shop-product-meta">
            <span class="shop-price">{html.escape(product['price'])}</span>
            <span class="shop-rating">★ {html.escape(product['rating'])}</span>
        </div>
        <div class="muted" style="font-size: 13px;">{html.escape(product['delivery'])}</div>
        <div class="shop-actions">
            {self._render_button("Add to cart", style="primary", element_type="product-action")}
            {self._render_button("Save", style="secondary", element_type="wishlist")}
        </div>
    </div>
</article>
"""
            )

        return f"""
<section class="shopping-scene" style="--scene-accent: {theme['accent']}; --scene-soft: {theme['surface']};">
    <header class="scene-header">
        <div class="scene-header-inner">
            <div class="scene-brand">
                <span class="scene-brand-mark"></span>
                <span>{html.escape(theme['brand_name'])}</span>
            </div>
            <nav class="scene-header-nav">{nav_html}</nav>
            <div class="scene-inline-list">
                <span class="surface-pill">Free shipping</span>
                {self._render_button("Account", style="secondary", element_type="account")}
            </div>
        </div>
    </header>
    <div class="page-shell">
        <div class="shopping-toolbar">
            <span class="surface-pill">{html.escape(theme['promo_note'])}</span>
            <div class="searchbar-shell">
                {self._render_input(theme['search_placeholder'], label="Product search")}
                {self._render_button("Search", style="primary", element_type="search")}
            </div>
            {self._render_button("Today's deals", style="ghost", element_type="promotion")}
        </div>
        <div class="category-row">{category_html}</div>

        <section class="shopping-hero surface-card">
            <div>
                <div class="mini-label">{html.escape(theme['hero_kicker'])}</div>
                <h1>{html.escape(theme['hero_title'])}</h1>
                <p>{html.escape(theme['hero_copy'])}</p>
                <div class="hero-actions">
                    {self._render_button("Shop featured picks", style="primary", element_type="cta")}
                    {self._render_button("View bundles", style="secondary", element_type="cta")}
                </div>
                <div class="hero-note">Trusted checkout · curated categories · faster support</div>
            </div>
            <aside class="hero-aside">
                <div class="sidebar-panel surface-card">
                    <div class="section-title">What members get</div>
                    <ul class="highlight-list">{highlights_html}</ul>
                </div>
                <div class="sidebar-panel surface-card">
                    <div class="section-title">Popular collections</div>
                    <div class="collection-strip">{collections_html}</div>
                </div>
            </aside>
        </section>

        <div class="shopping-grid">
            <aside class="sidebar-panel surface-card">
                <div class="section-title">Filter by</div>
                <ul class="clean-list">
                    <li>Same-day delivery</li>
                    <li>Top-rated under $100</li>
                    <li>Bundles with setup guides</li>
                    <li>Member-only discounts</li>
                </ul>
            </aside>
            <main class="content-panel surface-card">
                <div class="section-title">Trending now</div>
                <div class="shop-product-grid">{''.join(product_cards)}</div>
            </main>
        </div>
    </div>
</section>
"""

    def _render_search_page(self, theme: Dict[str, Any]) -> str:
        tabs_html = "".join(
            f'<a href="#" class="surface-link"{self._decoy_attrs("tab", tab)}>{html.escape(tab)}</a>'
            for tab in theme["tabs"]
        )
        filters_html = "".join(
            f'<span class="surface-pill"{self._decoy_attrs("filter", item)}>{html.escape(item)}</span>'
            for item in theme["filters"]
        )
        questions_html = "".join(
            f'<li>{self._render_nav_link(question)}</li>' for question in theme["questions"]
        )

        result_cards = []
        for result in theme["results"]:
            result_cards.append(
                f"""
<article class="result-card surface-card">
    <div class="result-url">{html.escape(result['url'])}</div>
    <h3>{self._render_nav_link(result['title'])}</h3>
    <p>{html.escape(result['snippet'])}</p>
    <div class="result-actions">
        {self._render_button("Open result", style="primary", element_type="result")}
        {self._render_button("Save", style="secondary", element_type="result")}
    </div>
</article>
"""
            )

        return f"""
<section class="search-scene" style="--scene-accent: {theme['accent']}; --scene-soft: {theme['surface']};">
    <header class="scene-header">
        <div class="scene-header-inner">
            <div class="scene-brand">
                <span class="scene-brand-mark"></span>
                <span>{html.escape(theme['brand_name'])}</span>
            </div>
            <nav class="scene-header-nav">
                {self._render_nav_link("About")}
                {self._render_nav_link("Privacy")}
                {self._render_nav_link("Advertising")}
            </nav>
            {self._render_button("Sign in", style="secondary", element_type="account")}
        </div>
    </header>

    <div class="page-shell search-hero">
        <div class="searchbar-shell">
            {self._render_input(theme['query'], label="Search query")}
            {self._render_button("Search", style="primary", element_type="search")}
        </div>
        <div class="search-tabs">{tabs_html}</div>
        <div class="filter-row">{filters_html}</div>

        <div class="search-mainbar">
            <main class="search-result-list">
                {''.join(result_cards)}
            </main>
            <aside class="search-side-stack">
                <section class="insight-card surface-card">
                    <div class="section-title">{html.escape(theme['knowledge_title'])}</div>
                    <p class="muted" style="margin: 0 0 18px;">{html.escape(theme['knowledge_copy'])}</p>
                    {self._render_button("View source summary", style="ghost", element_type="knowledge")}
                </section>
                <section class="insight-card surface-card">
                    <div class="section-title">People also ask</div>
                    <ul class="clean-list">{questions_html}</ul>
                </section>
            </aside>
        </div>
    </div>
</section>
"""

    def _render_social_page(self, theme: Dict[str, Any]) -> str:
        top_nav_html = "".join(self._render_nav_link(item) for item in theme["nav_items"])
        left_menu_html = "".join(
            f'<a href="#" class="left-nav-item"{self._decoy_attrs("navigation", item)}>{html.escape(item)}</a>'
            for item in theme["left_menu"]
        )
        trend_html = "".join(
            f'<div class="trend-item"><span>{self._render_nav_link(item)}</span>{self._render_button("Join", style="ghost", element_type="trend")}</div>'
            for item in theme["trends"]
        )
        suggestion_html = "".join(
            f"""
<div class="suggestion-item">
    <div>
        <div style="font-weight: 700; color: #0f172a;">{html.escape(item['name'])}</div>
        <div class="muted" style="font-size: 13px;">{html.escape(item['role'])}</div>
    </div>
    {self._render_button("Follow", style="secondary", element_type="follow")}
</div>
"""
            for item in theme["suggestions"]
        )

        feed_html = []
        for post in theme["posts"]:
            initials = "".join(part[0] for part in post["user"].split()[:2]).upper()
            feed_html.append(
                f"""
<article class="feed-card surface-card">
    <div class="post-user">
        <span class="avatar">{html.escape(initials)}</span>
        <div>
            <div style="font-weight: 800; color: #0f172a;">{html.escape(post['user'])}</div>
            <div class="muted" style="font-size: 13px;">{html.escape(post['handle'])} · {html.escape(post['time'])}</div>
        </div>
    </div>
    <p>{html.escape(post['text'])}</p>
    <div class="feed-actions">
        {self._render_button(f"Like {post['likes']}", style="ghost", element_type="reaction")}
        {self._render_button(f"Reply {post['comments']}", style="secondary", element_type="reaction")}
        {self._render_button("Share", style="secondary", element_type="reaction")}
    </div>
</article>
"""
            )

        return f"""
<section class="social-scene" style="--scene-accent: {theme['accent']}; --scene-soft: {theme['surface']};">
    <header class="scene-header">
        <div class="scene-header-inner">
            <div class="scene-brand">
                <span class="scene-brand-mark"></span>
                <span>{html.escape(theme['brand_name'])}</span>
            </div>
            <nav class="scene-header-nav">{top_nav_html}</nav>
            <div class="scene-inline-list">
                {self._render_button("Create post", style="primary", element_type="composer")}
                <span class="surface-pill">3 notifications</span>
            </div>
        </div>
    </header>

    <div class="page-shell social-layout">
        <aside class="sidebar-panel surface-card">
            <div class="section-title">Menu</div>
            <div class="left-nav-list">{left_menu_html}</div>
        </aside>

        <main style="display: grid; gap: 18px;">
            <section class="feed-card surface-card social-composer">
                <div class="avatar-row">
                    <span class="avatar">ME</span>
                    <div>
                        <div style="font-weight: 800;">Share something useful</div>
                        <div class="muted" style="font-size: 13px;">{html.escape(theme['composer_prompt'])}</div>
                    </div>
                </div>
                {self._render_button("Start a post", style="ghost", element_type="composer")}
            </section>
            {''.join(feed_html)}
        </main>

        <aside style="display: grid; gap: 18px;">
            <section class="sidebar-panel surface-card">
                <div class="section-title">Who to follow</div>
                {suggestion_html}
            </section>
            <section class="sidebar-panel surface-card">
                <div class="section-title">Trending now</div>
                {trend_html}
            </section>
        </aside>
    </div>
</section>
"""

    def _render_email_register_page(self, theme: Dict[str, Any]) -> str:
        nav_html = "".join(self._render_nav_link(item) for item in theme["nav_items"])
        benefits_html = "".join(f"<li>{html.escape(item)}</li>" for item in theme["benefits"])
        trust_html = "".join(f"<li>{html.escape(item)}</li>" for item in theme["trust_points"])

        return f"""
<section class="register-scene" style="--scene-accent: {theme['accent']}; --scene-soft: {theme['surface']};">
    <header class="scene-header">
        <div class="scene-header-inner">
            <div class="scene-brand">
                <span class="scene-brand-mark"></span>
                <span>{html.escape(theme['brand_name'])}</span>
            </div>
            <nav class="scene-header-nav">{nav_html}</nav>
            {self._render_button("Log in", style="secondary", element_type="account")}
        </div>
    </header>

    <div class="page-shell register-hero">
        <section class="register-copy surface-card">
            <div class="mini-label">Create your account</div>
            <h1>{html.escape(theme['headline'])}</h1>
            <p>{html.escape(theme['subheadline'])}</p>
            <div class="subtle-panel" style="margin-top: 22px;">
                <div class="section-title" style="font-size: 16px; margin-bottom: 10px;">Included from day one</div>
                <ul class="highlight-list">{benefits_html}</ul>
            </div>
        </section>

        <div class="register-side-notes">
            <section class="register-card surface-card">
                <div class="section-title">Get started free</div>
                <div class="form-stack">
                    <div class="field-block">
                        <label>Email address</label>
                        {self._render_input("name@company.com", label="Email address")}
                    </div>
                    <div class="field-block">
                        <label>Password</label>
                        {self._render_input("Create a password", input_type="password", label="Password")}
                    </div>
                    <div class="field-block">
                        <label>Verification code</label>
                        {self._render_input("Enter 6-digit code", label="Verification code")}
                    </div>
                </div>
                <div class="cta-row" style="margin-top: 18px;">
                    {self._render_button("Create account", style="primary", element_type="signup")}
                    {self._render_button("Send code", style="ghost", element_type="signup")}
                </div>
                <div class="muted" style="margin-top: 14px; font-size: 13px;">
                    By continuing, you agree to the Terms and Privacy Policy.
                </div>
            </section>

            <section class="register-card surface-card">
                <div class="section-title">{html.escape(theme['aside_title'])}</div>
                <p class="muted" style="margin-top: 0;">{html.escape(theme['aside_copy'])}</p>
                <ul class="clean-list">{trust_html}</ul>
            </section>
        </div>
    </div>
</section>
"""

    def _render_background_page(self, theme: Dict[str, Any]) -> str:
        if self._theme_name == "shopping":
            return self._render_shopping_page(theme)
        if self._theme_name == "search":
            return self._render_search_page(theme)
        if self._theme_name == "social":
            return self._render_social_page(theme)
        return self._render_email_register_page(theme)

    def _render_trap_script(self) -> str:
        return """
<script>
(function() {
    const trapInput = document.getElementById('captcha-trap-input');

    function triggerTrap(payload) {
        if (trapInput) {
            trapInput.value = JSON.stringify({
                trapped: true,
                element_id: payload.id || 'unknown',
                element_type: payload.type || 'unknown',
                element_label: payload.label || 'unknown',
                timestamp: Date.now()
            });
        }

        const modal = document.getElementById('result-modal');
        const modalIcon = document.getElementById('modal-icon');
        const modalTitle = document.getElementById('modal-title');
        const modalMessage = document.getElementById('modal-message');
        const modalRetry = document.getElementById('modal-retry');

        if (modal && modalIcon && modalTitle && modalMessage) {
            modalIcon.className = 'modal-icon error';
            modalIcon.textContent = '✗';
            modalTitle.textContent = 'Verification Failed';
            modalMessage.textContent = 'You interacted with the background webpage instead of the real verification area.';
            if (modalRetry) modalRetry.style.display = 'inline-block';
            modal.classList.add('show');
        }
    }

    document.querySelectorAll('[data-decoy="true"]').forEach(function(el) {
        function payload() {
            return {
                id: el.id || 'unknown',
                type: el.getAttribute('data-decoy-type') || el.tagName.toLowerCase(),
                label: el.getAttribute('data-decoy-label') || el.textContent.trim() || 'unknown'
            };
        }

        if (el.tagName === 'INPUT') {
            ['focus', 'mousedown', 'touchstart', 'keydown'].forEach(function(eventName) {
                el.addEventListener(eventName, function(ev) {
                    ev.preventDefault();
                    ev.stopPropagation();
                    try { el.blur(); } catch (e) {}
                    triggerTrap(payload());
                });
            });
            return;
        }

        el.addEventListener('click', function(ev) {
            ev.preventDefault();
            ev.stopPropagation();
            triggerTrap(payload());
        });
    });
})();
</script>
"""

    def _build_distraction_page_template(
        self, title: str, description: str, inner_captcha_html: str
    ) -> str:
        theme_builders = {
            "shopping": _build_shopping_theme,
            "search": _build_search_theme,
            "social": _build_social_theme,
            "email_register": _build_email_register_theme,
        }
        theme = theme_builders.get(self._theme_name, _build_shopping_theme)(
            self._captcha_position
        )

        trap_input = ""
        trap_script = ""
        if self._trap_enabled():
            trap_input = (
                '<input type="hidden" id="captcha-trap-input" '
                'name="captcha_trap" value="" />'
            )
            trap_script = self._render_trap_script()

        position_class = f"position-{self._captcha_position}"

        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{html.escape(title)}</title>
{self._render_distraction_styles()}
</head>
<body>
<div class="distraction-page">
    {self._render_background_page(theme)}
    {self._render_footer()}
</div>
<div class="captcha-overlay {position_class}">
    <div class="captcha-dialog">
        <div class="captcha-wrapper">
            <h3>{html.escape(title)}</h3>
            <p class="captcha-desc">{html.escape(description)}</p>
            <form id="captcha-form" method="post" action="/verify" novalidate>
                <div class="captcha-stage">
                    {inner_captcha_html}
                </div>
                {trap_input}
                <div class="captcha-actions">
                    <button type="submit" class="btn-primary">Verify</button>
                    <button type="button" class="btn-secondary" id="refresh-btn">Refresh</button>
                </div>
            </form>
        </div>
    </div>
</div>
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
      const submitBtn = form.querySelector('button[type="submit"]');

      function setSubmitting(isSubmitting) {{
        if (!submitBtn) return;
        submitBtn.disabled = isSubmitting;
        submitBtn.style.opacity = isSubmitting ? '0.7' : '1';
        submitBtn.style.cursor = isSubmitting ? 'wait' : 'pointer';
        submitBtn.textContent = isSubmitting ? 'Verifying...' : 'Verify';
      }}

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
        setSubmitting(true);
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
        }})
        .finally(() => {{
          setSubmitting(false);
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
{trap_script}
</body>
</html>"""

    def render_full_page(self) -> str:
        if self.distraction_level == 0:
            return super().render_full_page()

        if not self._generated:
            self.generate()

        return self._build_distraction_page_template(
            self.get_page_title(),
            self.get_page_description(),
            super().render_html(),
        )

    def render_html(self) -> str:
        return super().render_html()

    def verify(self, user_input: Any, trap_input: Optional[str] = None) -> CaptchaResult:
        if trap_input:
            try:
                import json

                trap_data = json.loads(trap_input)
                if trap_data.get("trapped"):
                    return CaptchaResult(
                        success=False,
                        message=(
                            "Verification failed: interacted with background element "
                            f"({trap_data.get('element_type', 'unknown')})"
                        ),
                        expected=self._answer if hasattr(self, "_answer") else None,
                        received=f"trap:{trap_data.get('element_id', 'unknown')}",
                        extra={
                            "trap_triggered": True,
                            "decoy_element_id": trap_data.get("element_id"),
                            "decoy_element_type": trap_data.get("element_type"),
                            "decoy_element_label": trap_data.get("element_label"),
                        },
                    )
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass

        return super().verify(user_input)
