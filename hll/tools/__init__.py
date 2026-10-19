from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hll.tools.registry import ToolRegistry


def build_observation_registry() -> "ToolRegistry":
    from hll.tools.observation import register_observation_tools
    from hll.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_observation_tools(registry)
    return registry


def build_default_registry() -> "ToolRegistry":
    from hll.tools.actions import register_action_tools
    from hll.tools.classify import register_classify_tools
    from hll.tools.crop import register_crop_tools
    from hll.tools.drag import register_drag_tools
    from hll.tools.elements import register_element_tools
    from hll.tools.grid import register_grid_tools
    from hll.tools.ocr import register_ocr_tools
    from hll.tools.recovery import register_recovery_tools
    from hll.tools.solve import register_solve_tools
    from hll.tools.submit import register_submit_tools
    from hll.tools.vision import register_vision_tools
    from hll.tools.observation import register_observation_tools
    from hll.tools.registry import ToolRegistry

    registry = ToolRegistry()
    register_action_tools(registry)
    register_grid_tools(registry)
    register_submit_tools(registry)
    register_element_tools(registry)
    register_recovery_tools(registry)
    register_observation_tools(registry)
    register_crop_tools(registry)
    register_drag_tools(registry)
    register_ocr_tools(registry)
    register_classify_tools(registry)
    register_solve_tools(registry)
    register_vision_tools(registry)
    return registry


__all__ = ["build_default_registry", "build_observation_registry"]
