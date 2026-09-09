from typing import Callable
from dataclasses import dataclass


@dataclass
class Tool:
    name: str
    func: Callable
    schema: dict
