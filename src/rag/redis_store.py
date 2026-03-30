import json
import os

import redis


class RedisEmailStore:
    """Bare bones Redis store for email message embeddings and metadata.

    Each email message is stored as a Redis hash keyed by message_id,
    with thread_id stored as metadata for grouping/filtering.
    TTL defaults to 7 days.
    """

    TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

    def __init__(self):
        self.client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            password=os.getenv("REDIS_PASSWORD", None),
            decode_responses=True,
        )

    def store_message(
        self, message_id: str, thread_id: str, body: str, metadata: dict = {}
    ):
        """Store a raw email message with metadata. Embedding step to be added later."""
        key = f"email:msg:{message_id}"
        payload = {
            "message_id": message_id,
            "thread_id": thread_id,
            "body": body,
            **metadata,
        }
        self.client.hset(key, mapping=payload)
        self.client.expire(key, self.TTL_SECONDS)

    def get_message(self, message_id: str) -> dict | None:
        """Retrieve a stored message by message_id."""
        key = f"email:msg:{message_id}"
        data = self.client.hgetall(key)
        return data if data else None

    def exists(self, message_id: str) -> bool:
        """Check if a message is already stored."""
        return self.client.exists(f"email:msg:{message_id}") == 1
