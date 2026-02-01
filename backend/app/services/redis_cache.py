"""
Redis L1 cache for classification results.

Provides fast in-memory caching for email classification lookups,
with graceful fallback to DB-only when Redis is unavailable.
"""
import json
import logging
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)

_redis_client = None
_redis_unavailable = False  # Track if Redis connection failed


def get_redis_client():
    """
    Get or create Redis client.
    Returns None if Redis unavailable (connection failed).
    """
    global _redis_client, _redis_unavailable

    # If we already know Redis is unavailable, skip connection attempts
    if _redis_unavailable:
        return None

    if _redis_client is not None:
        return _redis_client

    try:
        import redis
        _redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        # Test connection
        _redis_client.ping()
        logger.debug("Redis cache connected successfully")
        return _redis_client
    except ImportError:
        logger.warning("Redis package not installed. Using DB-only cache.")
        _redis_unavailable = True
        return None
    except Exception as e:
        logger.warning(f"Redis unavailable: {e}. Using DB-only cache.")
        _redis_unavailable = True
        return None


def get_cached_classification_redis(content_hash: str, user_id: Optional[int]) -> Optional[dict]:
    """
    Try to get classification from Redis cache.

    Args:
        content_hash: SHA-256 hash of email content

    Returns:
        Cached classification dict or None on miss/error
    """
    if user_id is None:
        return None
    client = get_redis_client()
    if not client:
        return None

    try:
        key = f"class:{user_id}:{content_hash}"
        data = client.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.debug(f"Redis get error: {e}")

    return None


def set_cached_classification_redis(
    content_hash: str,
    user_id: Optional[int],
    data: dict,
    ttl_hours: int = 24 * 7,  # 7 days default
) -> bool:
    """
    Store classification in Redis cache with TTL.

    Args:
        content_hash: SHA-256 hash of email content
        data: Classification result dict to cache
        ttl_hours: Time-to-live in hours (default 7 days)

    Returns:
        True if cached successfully, False otherwise
    """
    if user_id is None:
        return False
    client = get_redis_client()
    if not client:
        return False

    try:
        key = f"class:{user_id}:{content_hash}"
        client.setex(key, ttl_hours * 3600, json.dumps(data))
        return True
    except Exception as e:
        logger.debug(f"Redis set error: {e}")
        return False


def invalidate_cached_classification_redis(content_hash: str, user_id: Optional[int]) -> bool:
    """
    Remove classification from Redis cache.

    Args:
        content_hash: SHA-256 hash of email content

    Returns:
        True if deleted (or didn't exist), False on error
    """
    if user_id is None:
        return True
    client = get_redis_client()
    if not client:
        return True  # No cache to invalidate

    try:
        key = f"class:{user_id}:{content_hash}"
        client.delete(key)
        return True
    except Exception as e:
        logger.debug(f"Redis delete error: {e}")
        return False


def get_cache_stats() -> dict:
    """
    Get Redis cache statistics.

    Returns:
        Dict with cache stats or empty dict if unavailable
    """
    client = get_redis_client()
    if not client:
        return {"status": "unavailable"}

    try:
        info = client.info("memory")
        key_count = client.dbsize()
        return {
            "status": "connected",
            "keys": key_count,
            "used_memory_human": info.get("used_memory_human", "unknown"),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
