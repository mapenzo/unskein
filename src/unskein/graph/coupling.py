"""Afferent/efferent coupling of a single module, kept apart so metrics and findings both use it."""

from dataclasses import dataclass


@dataclass(slots=True)
class CouplingMetrics:
    """Afferent/efferent coupling of a single module.

    Attributes:
        module: Dotted module name.
        afferent: Ca, number of modules that depend on this one.
        efferent: Ce, number of modules this one depends on.
    """

    module: str
    afferent: int
    efferent: int

    @property
    def instability(self) -> float:
        """Instability ``Ce / (Ca + Ce)`` in ``[0, 1]``; 0.0 for isolated modules."""
        total = self.afferent + self.efferent
        return self.efferent / total if total else 0.0
