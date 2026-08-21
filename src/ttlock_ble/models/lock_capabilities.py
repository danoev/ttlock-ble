"""Typed interpretation of the lock's device-feature bit field."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LockCapabilities:
    """Expose independently advertised management capabilities."""

    feature_mask: int

    def _has(self, bit: int) -> bool:
        return bool(self.feature_mask & (1 << bit))

    @property
    def supports_lock(self) -> bool:
        """Return whether the baseline lock-control command is available."""
        return True

    @property
    def supports_passcodes(self) -> bool:
        """Return whether keypad passcodes are advertised."""
        return self._has(0)

    @property
    def supports_cards(self) -> bool:
        """Return whether IC-card credentials are advertised."""
        return self._has(1)

    @property
    def supports_fingerprints(self) -> bool:
        """Return whether fingerprint credentials are advertised."""
        return self._has(2)

    @property
    def supports_auto_lock(self) -> bool:
        """Return whether auto-lock management is advertised."""
        return self._has(4)

    @property
    def supports_passcode_deletion(self) -> bool:
        """Return whether individual passcode deletion is advertised."""
        return self._has(5)

    @property
    def supports_passcode_updates(self) -> bool:
        """Return whether custom passcode modification is advertised."""
        return self._has(7)

    @property
    def supports_cyclic_passcodes(self) -> bool:
        """Return whether cyclic passcodes are advertised."""
        return self._has(12)

    @property
    def supports_sound(self) -> bool:
        """Return whether sound management is advertised."""
        return self._has(15)

    @property
    def has_clock(self) -> bool:
        """Return whether the device advertises an on-lock clock chip."""
        return not self._has(20)

    @property
    def supports_passage_mode(self) -> bool:
        """Return whether native passage-mode scheduling is advertised."""
        return self._has(22)

    @property
    def supports_passage_mode_auto_lock_disable(self) -> bool:
        """Return whether passage mode may disable auto-lock."""
        return self._has(23)

    @property
    def supports_cyclic_cards_or_fingerprints(self) -> bool:
        """Return whether recurring card/fingerprint validity is advertised."""
        return self._has(34)
