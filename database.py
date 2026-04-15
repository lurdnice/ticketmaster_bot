import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import asyncio
import aiosqlite

class Database:
    def __init__(self, db_path: str = "ticketmaster.db"):
        self.db_path = db_path
    
    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            # User searches cache
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_searches (
                    user_id INTEGER,
                    search_query TEXT,
                    search_time TIMESTAMP,
                    results TEXT,
                    PRIMARY KEY (user_id, search_query, search_time)
                )
            ''')
            
            # User emails cache
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_emails (
                    user_id INTEGER PRIMARY KEY,
                    email TEXT,
                    created_at TIMESTAMP
                )
            ''')
            
            # Rate limiting
            await db.execute('''
                CREATE TABLE IF NOT EXISTS rate_limits (
                    user_id INTEGER,
                    search_time TIMESTAMP,
                    PRIMARY KEY (user_id, search_time)
                )
            ''')
            
            # Event cache (to avoid repeated scraping)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS event_cache (
                    event_url TEXT PRIMARY KEY,
                    event_data TEXT,
                    image_data TEXT,
                    cached_at TIMESTAMP
                )
            ''')
            
            await db.commit()
    
    async def cache_search_result(self, user_id: int, query: str, results: List[Dict]):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO user_searches (user_id, search_query, search_time, results) VALUES (?, ?, ?, ?)",
                (user_id, query.lower(), datetime.now(), json.dumps(results))
            )
            await db.commit()
    
    async def get_cached_search(self, user_id: int, query: str) -> Optional[List[Dict]]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT results, search_time FROM user_searches WHERE user_id = ? AND search_query = ? ORDER BY search_time DESC LIMIT 1",
                (user_id, query.lower())
            )
            row = await cursor.fetchone()
            if row:
                results, search_time = row
                search_time = datetime.fromisoformat(search_time)
                if datetime.now() - search_time < timedelta(hours=1):
                    return json.loads(results)
            return None
    
    async def save_user_email(self, user_id: int, email: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO user_emails (user_id, email, created_at) VALUES (?, ?, ?)",
                (user_id, email, datetime.now())
            )
            await db.commit()
    
    async def get_user_email(self, user_id: int) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT email FROM user_emails WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else None
    
    async def check_rate_limit(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            # Count searches in last hour
            hour_ago = datetime.now() - timedelta(hours=1)
            cursor = await db.execute(
                "SELECT COUNT(*) FROM rate_limits WHERE user_id = ? AND search_time > ?",
                (user_id, hour_ago)
            )
            count = (await cursor.fetchone())[0]
            
            if count >= 10:  # 10 searches per hour
                return False
            
            # Log this search
            await db.execute(
                "INSERT INTO rate_limits (user_id, search_time) VALUES (?, ?)",
                (user_id, datetime.now())
            )
            await db.commit()
            return True
    
    async def cache_event(self, event_url: str, event_data: Dict, image_data: Optional[str] = None):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO event_cache (event_url, event_data, image_data, cached_at) VALUES (?, ?, ?, ?)",
                (event_url, json.dumps(event_data), image_data, datetime.now())
            )
            await db.commit()
    
    async def get_cached_event(self, event_url: str) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT event_data, image_data, cached_at FROM event_cache WHERE event_url = ?",
                (event_url,)
            )
            row = await cursor.fetchone()
            if row:
                event_data, image_data, cached_at = row
                cached_at = datetime.fromisoformat(cached_at)
                if datetime.now() - cached_at < timedelta(hours=24):
                    return {
                        'event_data': json.loads(event_data),
                        'image_data': image_data
                    }
            return None

# Global database instance
db = Database()