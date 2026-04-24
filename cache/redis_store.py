"""
Redis Store — Incident caching and deduplication.

Provides fingerprint-based caching of investigation results so that
repeated incidents get instant responses. Degrades gracefully when
Redis is unavailable.
"""

import hashlib
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import redis; make it optional
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("redis package not installed — caching disabled")


class IncidentCache:
    """Fingerprint-based incident result cache backed by Redis.

    If Redis is unreachable or the redis package is not installed,
    all operations become safe no-ops so the rest of the system
    continues to work.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.available = False
        self.client = None

        if not REDIS_AVAILABLE:
            logger.warning("redis package not installed — caching disabled")
            return

        try:
            self.client = redis.Redis.from_url(redis_url, decode_responses=True)
            self.client.ping()
            self.available = True
            logger.info("Redis connection established — caching enabled")
        except Exception as exc:
            logger.warning("Redis unavailable (%s) — caching disabled", exc)

    # ------------------------------------------------------------------
    # Fingerprinting
    # ------------------------------------------------------------------

    @staticmethod
    def generate_fingerprint(
        service: str,
        exception_type: str,
        file: str,
        line: int,
    ) -> str:
        """Generate a deterministic incident fingerprint.

        Format: service|exception_type|file|line  →  SHA-256 (first 16 chars)
        """
        raw = f"{service}|{exception_type}|{file}|{line}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Cache operations
    # ------------------------------------------------------------------

    def lookup(self, fingerprint: str) -> Optional[dict]:
        """Look up a cached investigation result by fingerprint.

        Returns None if not found or Redis is unavailable.
        """
        if not self.available:
            return None
        try:
            data = self.client.get(f"incident:{fingerprint}")
            if data:
                result = json.loads(data)
                logger.info("Cache HIT for fingerprint %s", fingerprint)
                return result
            logger.info("Cache MISS for fingerprint %s", fingerprint)
            return None
        except Exception as exc:
            logger.warning("Cache lookup failed: %s", exc)
            return None

    def store(
        self,
        fingerprint: str,
        result: dict,
        ttl: int = 3600,
    ) -> bool:
        """Store an investigation result in the cache.

        Args:
            fingerprint: The incident fingerprint key.
            result: The investigation result dict (must be JSON-serializable).
            ttl: Time-to-live in seconds (default: 1 hour).

        Returns:
            True if stored successfully, False otherwise.
        """
        if not self.available:
            return False
        try:
            self.client.setex(
                f"incident:{fingerprint}",
                ttl,
                json.dumps(result, default=str),
            )
            # Track occurrence count
            self.client.incr(f"incident_count:{fingerprint}")
            logger.info("Cached result for fingerprint %s (TTL=%ds)", fingerprint, ttl)
            return True
        except Exception as exc:
            logger.warning("Cache store failed: %s", exc)
            return False

    def get_occurrence_count(self, fingerprint: str) -> int:
        """Get how many times this incident fingerprint has been seen."""
        if not self.available:
            return 0
        try:
            count = self.client.get(f"incident_count:{fingerprint}")
            return int(count) if count else 0
        except Exception:
            return 0

    def clear(self, fingerprint: str) -> bool:
        """Remove a cached result."""
        if not self.available:
            return False
        try:
            self.client.delete(f"incident:{fingerprint}")
            return True
        except Exception:
            return False
