"""Connectors for external platforms (e.g. LinkedIn, Reddit)."""

from socialgraph.connectors.base import BaseConnector, RawPost
from socialgraph.connectors.linkedin import LinkedInJSONConnector
from socialgraph.connectors.reddit import RedditAPIConnector

__all__ = ["BaseConnector", "LinkedInJSONConnector", "RawPost", "RedditAPIConnector"]
