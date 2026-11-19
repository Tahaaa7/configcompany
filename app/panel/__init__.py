from functools import lru_cache
from ..config import PANEL
from .base import Panel

@lru_cache
def get_panel() -> Panel:
    if PANEL == "remnawave":
        from .remnawave import Remnawave
        return Remnawave()
    if PANEL == "marzban":
        from .marzban import Marzban
        return Marzban()
    from .base import MockPanel
    return MockPanel()
