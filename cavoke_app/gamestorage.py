from typing import Dict, Tuple, Any
from threading import Lock

from cavoke import Game


game_type_dict: Dict[str, Any] = {}
game_session_dict: Dict[str, Tuple[Game, Lock]] = {}
