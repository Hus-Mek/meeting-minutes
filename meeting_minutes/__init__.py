"""Automated meeting-minutes generator.

Reconciles sparse human notes (the *spine* — what mattered) with a full diarized
transcript (the *detail source* — accurate facts) into topic-by-topic minutes.
"""

__all__ = ["transcript", "prompt", "llm", "minutes"]
