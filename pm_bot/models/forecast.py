from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SourceForecast:
    source: str
    temp_high_c: float
    std_c: float
    weight: float = 1.0
    members: list[float] = field(default_factory=list)

    @property
    def mean(self) -> float:
        if not self.members:
            return self.temp_high_c
        return sum(self.members) / len(self.members)

    @property
    def std(self) -> float:
        if self.std_c > 0:
            return self.std_c
        if len(self.members) < 2:
            return 0.0
        import numpy as np
        return float(np.std(self.members))


@dataclass
class ConsensusForecast:
    city: str
    date: str
    temp_high_c: float
    std_c: float
    consensus_prob: float = 0.5
    agreement_score: float = 1.0
    sources: dict[str, SourceForecast] = field(default_factory=dict)
    individual_probs: dict[str, float] = field(default_factory=dict)
