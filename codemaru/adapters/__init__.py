"""External platform adapters.

Each adapter fetches one platform and returns a typed snapshot. A failure (HTTP
error, timeout, schema change, missing user) is mapped to an ``unavailable``
snapshot rather than raising, so one platform never breaks the whole card. The
parsing functions are pure and tested against saved fixture payloads — default
CI does not make live calls.
"""

from codemaru.adapters.github import fetch_github
from codemaru.adapters.leetcode import fetch_leetcode
from codemaru.adapters.solvedac import fetch_solvedac

__all__ = ["fetch_github", "fetch_leetcode", "fetch_solvedac"]
