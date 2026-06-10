# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   utils/db.py — MongoDB handler
#   © AnimeTadka
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone, timedelta
from config import MONGO_URI, MONGO_DB

_client = None
_db     = None


def get_db():
    global _client, _db
    if _db is None:
        _client = AsyncIOMotorClient(MONGO_URI)
        _db     = _client[MONGO_DB]
    return _db


# ── Collections ───────────────────────────────────
# groups             → { group_id, group_title, authorised_by, authorised_at }
# admins             → { user_id, added_by, added_at }
# requests           → { anime, user_id, username, group_id, group_title, status, requested_at }
# searches           → { query, user_id, username, group_id, results_count, searched_at }
# pending_deletions  → { chat_id, bot_message_id, user_message_id, delete_at, created_at }


# ── Groups ────────────────────────────────────────

async def authorise_group(group_id: int, group_title: str, authorised_by: int):
    db = get_db()
    await db.groups.update_one(
        {"group_id": group_id},
        {"$set": {
            "group_id":      group_id,
            "group_title":   group_title,
            "authorised_by": authorised_by,
            "authorised_at": datetime.now(timezone.utc),
            "active":        True
        }},
        upsert=True
    )


async def revoke_group(group_id: int):
    db = get_db()
    await db.groups.update_one(
        {"group_id": group_id},
        {"$set": {"active": False}}
    )


async def get_authorised_groups() -> set:
    db = get_db()
    cursor = db.groups.find({"active": True}, {"group_id": 1})
    groups = set()
    async for doc in cursor:
        groups.add(doc["group_id"])
    return groups


# ── Admins ────────────────────────────────────────

async def add_admin(user_id: int, added_by: int):
    db = get_db()
    await db.admins.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id":  user_id,
            "added_by": added_by,
            "added_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )


async def get_all_admins() -> set:
    db = get_db()
    cursor = db.admins.find({}, {"user_id": 1})
    admins = set()
    async for doc in cursor:
        admins.add(doc["user_id"])
    return admins


# ── Requests ──────────────────────────────────────

async def add_request(user_id: int, username: str, anime: str, group_id: int, group_title: str):
    db = get_db()
    await db.requests.insert_one({
        "anime":        anime,
        "user_id":      user_id,
        "username":     username,
        "group_id":     group_id,
        "group_title":  group_title,
        "status":       "pending",
        "requested_at": datetime.now(timezone.utc)
    })


async def get_pending_requests() -> list:
    db = get_db()
    cursor = db.requests.find({"status": "pending"}).sort("requested_at", -1).limit(20)
    results = []
    async for doc in cursor:
        results.append({
            "id":    str(doc["_id"]),
            "anime": doc["anime"],
            "user":  f"@{doc['username']}" if doc.get("username") else str(doc["user_id"]),
            "group": doc.get("group_title", "Unknown"),
            "time":  doc["requested_at"].strftime("%d %b %Y • %H:%M UTC")
        })
    return results


async def mark_request_done(request_id: str):
    from bson import ObjectId
    db = get_db()
    await db.requests.update_one(
        {"_id": ObjectId(request_id)},
        {"$set": {"status": "done"}}
    )


async def dismiss_request(request_id: str):
    from bson import ObjectId
    db = get_db()
    await db.requests.update_one(
        {"_id": ObjectId(request_id)},
        {"$set": {"status": "dismissed"}}
    )


# ── Searches ──────────────────────────────────────

async def log_search(user_id: int, username: str, query: str, results_count: int, group_id: int):
    db = get_db()
    await db.searches.insert_one({
        "query":         query.lower().strip(),
        "user_id":       user_id,
        "username":      username,
        "group_id":      group_id,
        "results_count": results_count,
        "searched_at":   datetime.now(timezone.utc)
    })


async def get_search_stats() -> dict:
    db = get_db()
    total = await db.searches.count_documents({})

    pipeline = [
        {"$group": {"_id": "$query", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5}
    ]
    top = []
    async for doc in db.searches.aggregate(pipeline):
        top.append((doc["_id"], doc["count"]))

    return {"total": total, "top": top}


# ── Pending Deletions ─────────────────────────────

async def schedule_deletion(
    chat_id: int,
    bot_message_id: int,
    user_message_id: int | None = None,
    delay_seconds: int = 600
):
    """
    Schedule bot_message_id (and optionally user_message_id) for
    deletion after delay_seconds. Stored in MongoDB so it survives restarts.
    """
    db = get_db()
    delete_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
    await db.pending_deletions.insert_one({
        "chat_id":         chat_id,
        "bot_message_id":  bot_message_id,
        "user_message_id": user_message_id,
        "delete_at":       delete_at,
        "created_at":      datetime.now(timezone.utc)
    })


async def get_due_deletions() -> list:
    """Return all entries whose delete_at is now or in the past."""
    db = get_db()
    now = datetime.now(timezone.utc)
    cursor = db.pending_deletions.find({"delete_at": {"$lte": now}})
    results = []
    async for doc in cursor:
        results.append(doc)
    return results


async def remove_deletion(doc_id):
    """Remove a processed deletion entry by its _id."""
    db = get_db()
    await db.pending_deletions.delete_one({"_id": doc_id})


async def get_user_message_for_bot_message(chat_id: int, bot_message_id: int) -> int | None:
    """
    Look up which user_message_id is paired with a given bot message.
    Used by close buttons to also delete the triggering command.
    """
    db = get_db()
    doc = await db.pending_deletions.find_one({
        "chat_id":        chat_id,
        "bot_message_id": bot_message_id
    })
    if doc:
        return doc.get("user_message_id")
    return None


async def cleanup_old_deletions():
    """
    Remove entries older than 2 hours from pending_deletions.
    Called hourly to keep the collection lean.
    """
    db = get_db()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    result = await db.pending_deletions.delete_many({"created_at": {"$lt": cutoff}})
    return result.deleted_count
