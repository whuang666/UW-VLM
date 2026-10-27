"""USIM -> ENACT adaptation layer.

The upstream ENACT pipeline expects BEHAVIOR/OmniGibson style directories:

    <root>/<episode_key>/scene_graph_0.json
    <root>/<episode_key>/external_sensor1/00000.png

USIM ships as a LeRobot v2.1 dataset (Parquet + two MP4 streams per episode).
This package bridges the two without modifying upstream core code:

* ``usim_reader``      LeRobot access, global episode keys, frame<->row alignment.
* ``usim_visibility``  Visibility providers (annotation boolean / mask pixel count).
* ``usim_scene_graph`` ``SceneGraphReader`` subclass that understands boolean visibility.
* ``usim_annotations`` Annotation schema, validation, ENACT scene-graph compilation.
"""

from enact.adapters.usim_reader import USIMEpisode, USIMReader, episode_key  # noqa: F401
from enact.adapters.usim_visibility import BooleanVisibilityProvider  # noqa: F401
from enact.adapters.usim_scene_graph import USIMSceneGraphReader  # noqa: F401

__all__ = [
    "USIMEpisode",
    "USIMReader",
    "episode_key",
    "BooleanVisibilityProvider",
    "USIMSceneGraphReader",
]
