from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class KnowledgeChunk:
    title: str
    content: str
    source: str
    score: float = 0.0
    url: Optional[str] = None
    code_blocks: Optional[List[str]] = None
    updated_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BaseExternalKnowledgeProvider(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def search(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[KnowledgeChunk]:
        raise NotImplementedError
