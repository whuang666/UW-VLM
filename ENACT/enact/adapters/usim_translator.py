"""USIM state vocabulary for ENACT's template-based translator.

Upstream ``StateChangeTranslator`` only knows BEHAVIOR predicates.  USIM manipulates
a small set of objects with a clear lifecycle, so v0.1 extends the vocabulary with
four unary states and keeps every upstream predicate available:

    物体生命周期      OnSeabed -> InGripper(+Lifted) -> InBox
    robot 接近关系    NextTo(robot, object)

The subclass is injected into the upstream generators/verifier at construction time
(``generator.translator = USIMStateChangeTranslator(...)``), so upstream code paths,
diffing and signature logic stay untouched.
"""

from __future__ import annotations

from typing import Dict

from enact.utils.state_change_translator import StateChangeTranslator

USIM_STATE_TEMPLATES: Dict[str, str] = {
    # unary object lifecycle states
    "OnSeabed": "on the seabed",
    "InGripper": "grasped by the robot",
    "Lifted": "lifted above the seabed",
    "InBox": "inside the green box",
    # binary relations reused from the BEHAVIOR vocabulary
    "NextTo": "next to",
    "Touching": "touching",
    "Inside": "inside",
    "OnTop": "on top of and touching",
    "Grasping": "grasping",
}

USIM_NODE_STATE_NAMES = ("OnSeabed", "InGripper", "Lifted", "InBox")
USIM_EDGE_PREDICATES = ("NextTo", "Touching", "Inside", "OnTop", "Grasping")


class USIMStateChangeTranslator(StateChangeTranslator):
    """Translator with the USIM vocabulary and grammatical node-state templates."""

    def __init__(self, type: str = "multi_forward_world_modeling") -> None:
        super().__init__(type=type)
        self._state_templates.update(USIM_STATE_TEMPLATES)
        # Rewrite node templates so that adjective-like states read naturally,
        # e.g. "the red cylinder is now grasped by the robot".
        self._change_type_templates["add"]["nodes"] = [
            "{object} is now {state}",
            "{object} becomes {state}",
        ]
        self._change_type_templates["remove"]["nodes"] = [
            "{object} is no longer {state}",
            "{object} is not {state} anymore",
        ]
