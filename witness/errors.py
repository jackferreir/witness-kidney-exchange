"""Exception types.

Kept in their own module so `core` and `tiebreak` can both raise them without
an import cycle.
"""


class WitnessError(Exception):
    """Base class for every error this package raises deliberately."""


class ModelError(WitnessError, ValueError):
    """A malformed market, profile, or configuration."""


class TieError(ModelError):
    """Two students share a priority class and the configured tiebreak rule
    refuses to break the tie.

    This is raised rather than picked arbitrarily. An arbitrary choice here is
    exactly the class of bug that manufactures fake manipulations.
    """


class MechanismError(WitnessError, RuntimeError):
    """A mechanism hit a state its published description says is impossible
    (e.g. more proposals than the algorithm's own termination bound allows).
    """
