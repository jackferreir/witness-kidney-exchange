"""Name -> mechanism registry, so a saved witness can be replayed from its name alone.

CRITICAL INTERFACE NOTE: `MechanismSpec.run` takes `(market, profile, config)` and MUST
do its own priority resolution internally. Do NOT resolve priorities once and share them
across runs. For plain DA, priority resolution is profile-free, so it makes no
difference either way. But a mechanism with first-choice priority (see
`witness.controls`) resolves priorities FROM THE REPORTS -- sharing a pre-resolved order
across the truthful run and a misreport run would silently destroy exactly the effect
the manipulation search exists to find.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Callable, Mapping

from witness.boston import BostonConfig, boston_immediate_acceptance
from witness.controls import run_first_choice_bonus_da
from witness.core import Market, Profile
from witness.da import Assignment, DAConfig, deferred_acceptance
from witness.errors import ModelError
from witness.reserves import ReserveConfig, reserve_da
from witness.ttc import TTCConfig, top_trading_cycles


@dataclass(frozen=True)
class MechanismSpec:
    """One registered mechanism.

    `config_from_dict` rebuilds a config object from its `to_dict()` form (for
    replay). `run` computes the final Assignment for a given (market, profile,
    config) -- see the interface note above.
    """

    name: str
    config_from_dict: Callable[[Mapping], object]
    run: Callable[[Market, Profile, object], Assignment]


_REGISTRY: dict[str, MechanismSpec] = {}


def register_mechanism(spec: MechanismSpec) -> None:
    """Register `spec` under `spec.name`. Raises `ModelError` on a duplicate name."""
    if spec.name in _REGISTRY:
        raise ModelError(
            f"mechanism {spec.name!r} is already registered; known mechanisms: "
            f"{mechanism_names()!r}"
        )
    _REGISTRY[spec.name] = spec


def get_mechanism(name: str) -> MechanismSpec:
    """Look up a registered mechanism by name. Raises `ModelError`, listing the
    known names, if `name` is not registered."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ModelError(
            f"unknown mechanism {name!r}; known mechanisms: {mechanism_names()!r}"
        ) from None


def mechanism_names() -> tuple[str, ...]:
    """Every registered mechanism name, sorted."""
    return tuple(sorted(_REGISTRY))


def _run_student_proposing_da(market: Market, profile: Profile, config: DAConfig) -> Assignment:
    return deferred_acceptance(market, profile, config).assignment


def _da_config_from_dict(expected_mechanism: str, data: Mapping) -> DAConfig:
    """Rebuild a `DAConfig` from `data`, insisting its own "mechanism" field
    agrees with `expected_mechanism`.

    `DAConfig` is shared verbatim by both mechanisms registered below, so its
    own `from_dict` default ("student_proposing_da") would silently be
    "right" for one of them and silently wrong for the other. Each spec below
    binds this to its own name explicitly rather than handing
    `DAConfig.from_dict` to both, so neither spec is trusting that default.
    """
    config = DAConfig.from_dict(data)
    if config.mechanism != expected_mechanism:
        raise ModelError(
            f"config data claims mechanism {config.mechanism!r}, but this is "
            f"the config_from_dict for mechanism {expected_mechanism!r}"
        )
    return config


register_mechanism(
    MechanismSpec(
        name="student_proposing_da",
        config_from_dict=partial(_da_config_from_dict, "student_proposing_da"),
        run=_run_student_proposing_da,
    )
)

register_mechanism(
    MechanismSpec(
        name="first_choice_bonus_da",
        config_from_dict=partial(_da_config_from_dict, "first_choice_bonus_da"),
        run=run_first_choice_bonus_da,
    )
)


def _run_boston_immediate_acceptance(
    market: Market, profile: Profile, config: BostonConfig
) -> Assignment:
    return boston_immediate_acceptance(market, profile, config).assignment


def _boston_config_from_dict(expected_mechanism: str, data: Mapping) -> BostonConfig:
    """Rebuild a `BostonConfig` from `data`, insisting its own "mechanism"
    field agrees with `expected_mechanism` -- same discipline as
    `_da_config_from_dict` above, and for the same reason: `mechanism` is an
    explicit, validated field, never inferred from which spec happened to be
    called."""
    config = BostonConfig.from_dict(data)
    if config.mechanism != expected_mechanism:
        raise ModelError(
            f"config data claims mechanism {config.mechanism!r}, but this is "
            f"the config_from_dict for mechanism {expected_mechanism!r}"
        )
    return config


register_mechanism(
    MechanismSpec(
        name="boston_immediate_acceptance",
        config_from_dict=partial(_boston_config_from_dict, "boston_immediate_acceptance"),
        run=_run_boston_immediate_acceptance,
    )
)


def _run_reserve_da(market: Market, profile: Profile, config: ReserveConfig) -> Assignment:
    return reserve_da(market, profile, config).assignment


def _reserve_config_from_dict(expected_mechanism: str, data: Mapping) -> ReserveConfig:
    """Same discipline as the two above: `mechanism` is read from the data and
    checked, never inferred from which spec was called."""
    config = ReserveConfig.from_dict(data)
    if config.mechanism != expected_mechanism:
        raise ModelError(
            f"config data claims mechanism {config.mechanism!r}, but this is "
            f"the config_from_dict for mechanism {expected_mechanism!r}"
        )
    return config


register_mechanism(
    MechanismSpec(
        name="reserve_da",
        config_from_dict=partial(_reserve_config_from_dict, "reserve_da"),
        run=_run_reserve_da,
    )
)


def _run_top_trading_cycles(
    market: Market, profile: Profile, config: TTCConfig
) -> Assignment:
    return top_trading_cycles(market, profile, config).assignment


def _ttc_config_from_dict(expected_mechanism: str, data: Mapping) -> TTCConfig:
    """Same discipline as the three above: `mechanism` is read from the data
    and checked, never inferred from which spec was called."""
    config = TTCConfig.from_dict(data)
    if config.mechanism != expected_mechanism:
        raise ModelError(
            f"config data claims mechanism {config.mechanism!r}, but this is "
            f"the config_from_dict for mechanism {expected_mechanism!r}"
        )
    return config


register_mechanism(
    MechanismSpec(
        name="top_trading_cycles",
        config_from_dict=partial(_ttc_config_from_dict, "top_trading_cycles"),
        run=_run_top_trading_cycles,
    )
)
