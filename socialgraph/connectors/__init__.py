"""Connectors for external platforms (e.g. LinkedIn)."""

from socialgraph.connectors.base import BaseConnector, RawPost
from socialgraph.connectors.linkedin import LinkedInJSONConnector

__all__ = ["BaseConnector", "LinkedInJSONConnector", "RawPost"]
