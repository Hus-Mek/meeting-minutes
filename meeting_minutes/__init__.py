"""Automated meeting-minutes generator.

Reconciles sparse human notes (the *spine* — what mattered) with a full diarized
transcript (the *detail source* — accurate facts) into topic-by-topic minutes.
"""

# Single source of truth for the app version. Kept in lockstep with
# packaging/installer.iss's AppVersion and surfaced by the update checker
# (meeting_minutes/update.py) and GET /api/update/check.
__version__ = "1.0.7"

from . import llm, minutes, prompt, transcript

__all__ = ["transcript", "prompt", "llm", "minutes", "__version__"]
