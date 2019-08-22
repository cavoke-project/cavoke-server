from typing import Dict, Tuple, Any
from threading import Lock

from cavoke import Game

"""
game_session_dict dictionary for storing game sessions
"""
game_session_dict: Dict[str, Tuple[Game, Lock]] = {}
