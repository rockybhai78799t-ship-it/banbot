#!/usr/bin/env python3
"""
Anti-Premium Guard Bot - Pure Python Single File Version
With REAL Payment Verification via FAM Gateway
UPI: Chandaliya@fam
"""

# CRITICAL: nest_asyncio MUST be applied before ANY other imports
import nest_asyncio
nest_asyncio.apply()

import sqlite3
import json
import asyncio
import logging
import os
import random
import string
import time
import sys
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any

# Now import pyrogram
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, ChatMemberUpdated
)
from pyrogram.enums import ChatType, ChatMemberStatus
from pyrogram.errors import RPCError

# ----------------- CONFIGURATION -----------------
BOT_TOKEN = '8441889585:AAEzK6uiWBPUG_4tEATWV2XojH80A0Jih8Y'
ADMIN_ID = 8790937904
FAM_API_KEY = 'fam_76e80dd1401deb6f2e74aa34e270c6f41ff9b088'
BASE_URL = 'https://famgateway.in'
DB_PATH = 'bot_database_v3.db'
UPI_ID = 'Chandaliya@fam'
UPI_NAME = 'Chandaliya'

API_ID = 35167678
API_HASH = "6e276419f272bd0d69c348463f02b17f"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------- DATABASE -----------------
class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.init_db()
    
    def get_conn(self):
        return sqlite3.connect(self.db_path)
    
    def init_db(self):
        with self.get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    access_until TEXT
                );
                CREATE TABLE IF NOT EXISTS access_keys (
                    key_code TEXT PRIMARY KEY,
                    days INTEGER DEFAULT 30,
                    is_used INTEGER DEFAULT 0,
                    used_by INTEGER,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS channels (
                    channel_id INTEGER PRIMARY KEY,
                    owner_id INTEGER,
                    title TEXT
                );
                CREATE TABLE IF NOT EXISTS approved_users (
                    owner_id INTEGER,
                    target_user_id INTEGER,
                    target_username TEXT,
                    PRIMARY KEY(owner_id, target_user_id)
                );
                CREATE TABLE IF NOT EXISTS kick_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER,
                    channel_id INTEGER,
                    user_id INTEGER,
                    kicked_at TEXT
                );
                CREATE TABLE IF NOT EXISTS payments (
                    order_id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    amount REAL,
                    status TEXT,
                    days INTEGER DEFAULT 30,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS user_states (
                    user_id INTEGER PRIMARY KEY,
                    state TEXT,
                    data TEXT
                );
                CREATE TABLE IF NOT EXISTS leave_messages (
                    owner_id INTEGER PRIMARY KEY,
                    messages_json TEXT
                );
                CREATE TABLE IF NOT EXISTS agents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_string TEXT UNIQUE,
                    added_at TEXT
                );
                CREATE TABLE IF NOT EXISTS pending_dms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_user_id INTEGER,
                    owner_id INTEGER,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT
                );
                
                INSERT OR IGNORE INTO config (key, value) VALUES ('price_7', '110');
                INSERT OR IGNORE INTO config (key, value) VALUES ('price_30', '350');
                INSERT OR IGNORE INTO config (key, value) VALUES ('price_life', '1200');
            """)
            conn.commit()
    
    # ---------- Config ----------
    def get_config(self, key: str, default: str = None) -> str:
        with self.get_conn() as conn:
            cur = conn.execute("SELECT value FROM config WHERE key = ?", (key,))
            row = cur.fetchone()
            return row[0] if row else default
    
    def set_config(self, key: str, value: str):
        with self.get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
    
    def get_prices(self) -> dict:
        prices = {'price_7': 110.0, 'price_30': 350.0, 'price_life': 1200.0}
        with self.get_conn() as conn:
            cur = conn.execute("SELECT key, value FROM config WHERE key IN ('price_7', 'price_30', 'price_life')")
            for row in cur.fetchall():
                prices[row[0]] = float(row[1])
        return prices
    
    # ---------- Users ----------
    def get_user_access(self, user_id: int) -> Tuple[bool, str]:
        if user_id == ADMIN_ID:
            return True, "Lifetime (Admin)"
        
        with self.get_conn() as conn:
            cur = conn.execute("SELECT access_until FROM users WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            
            if not row or not row[0]:
                return False, "Expired / No Access"
            
            try:
                expiry = datetime.fromisoformat(row[0])
                if expiry > datetime.now():
                    diff = expiry - datetime.now()
                    days = diff.days
                    hours = diff.seconds // 3600
                    return True, f"{days}d {hours}h remaining"
            except:
                pass
            
            return False, "Expired"
    
    def set_user_access(self, user_id: int, days: int):
        with self.get_conn() as conn:
            cur = conn.execute("SELECT access_until FROM users WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            
            now = datetime.now()
            if row and row[0]:
                try:
                    expiry = datetime.fromisoformat(row[0])
                    if expiry > now:
                        now = expiry
                except:
                    pass
            
            new_expiry = now + timedelta(days=days)
            conn.execute(
                "INSERT OR REPLACE INTO users (user_id, access_until) VALUES (?, ?)",
                (user_id, new_expiry.isoformat())
            )
            conn.commit()
    
    # ---------- Access Keys ----------
    def generate_key(self, days: int) -> str:
        chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        segments = []
        for _ in range(3):
            seg = ''.join(random.choice(chars) for _ in range(4))
            segments.append(seg)
        key = 'PREM-' + '-'.join(segments)
        
        with self.get_conn() as conn:
            conn.execute(
                "INSERT INTO access_keys (key_code, days, is_used, created_at) VALUES (?, ?, 0, ?)",
                (key, days, datetime.now().isoformat())
            )
            conn.commit()
        return key
    
    def activate_key(self, user_id: int, key_code: str) -> bool:
        with self.get_conn() as conn:
            cur = conn.execute("SELECT days, is_used FROM access_keys WHERE key_code = ?", (key_code,))
            row = cur.fetchone()
            
            if not row or row[1] == 1:
                return False
            
            days = row[0]
            self.set_user_access(user_id, days)
            
            conn.execute(
                "UPDATE access_keys SET is_used = 1, used_by = ? WHERE key_code = ?",
                (user_id, key_code)
            )
            conn.commit()
            return True
    
    # ---------- Channels ----------
    def add_channel(self, channel_id: int, owner_id: int, title: str):
        with self.get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO channels (channel_id, owner_id, title) VALUES (?, ?, ?)",
                (channel_id, owner_id, title)
            )
            conn.commit()
    
    def get_channel_owner(self, channel_id: int) -> Optional[int]:
        with self.get_conn() as conn:
            cur = conn.execute("SELECT owner_id FROM channels WHERE channel_id = ?", (channel_id,))
            row = cur.fetchone()
            return row[0] if row else None
    
    def get_user_channels(self, owner_id: int) -> List[str]:
        with self.get_conn() as conn:
            cur = conn.execute("SELECT title FROM channels WHERE owner_id = ?", (owner_id,))
            return [row[0] for row in cur.fetchall()]
    
    # ---------- Approved Users ----------
    def add_approved_user(self, owner_id: int, target_id: int, username: str = None):
        with self.get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO approved_users (owner_id, target_user_id, target_username) VALUES (?, ?, ?)",
                (owner_id, target_id, username or f"ID:{target_id}")
            )
            conn.commit()
    
    def remove_approved_user(self, owner_id: int, target_id: int):
        with self.get_conn() as conn:
            conn.execute(
                "DELETE FROM approved_users WHERE owner_id = ? AND target_user_id = ?",
                (owner_id, target_id)
            )
            conn.commit()
    
    def get_approved_users(self, owner_id: int) -> List[dict]:
        with self.get_conn() as conn:
            cur = conn.execute(
                "SELECT target_user_id, target_username FROM approved_users WHERE owner_id = ?",
                (owner_id,)
            )
            return [{'id': row[0], 'username': row[1]} for row in cur.fetchall()]
    
    def is_approved(self, owner_id: int, user_id: int) -> bool:
        with self.get_conn() as conn:
            cur = conn.execute(
                "SELECT 1 FROM approved_users WHERE owner_id = ? AND target_user_id = ?",
                (owner_id, user_id)
            )
            return cur.fetchone() is not None
    
    # ---------- Kick Logs ----------
    def log_kick(self, owner_id: int, channel_id: int, user_id: int):
        with self.get_conn() as conn:
            conn.execute(
                "INSERT INTO kick_logs (owner_id, channel_id, user_id, kicked_at) VALUES (?, ?, ?, ?)",
                (owner_id, channel_id, user_id, datetime.now().isoformat())
            )
            conn.commit()
    
    def get_kick_count(self, owner_id: int) -> int:
        with self.get_conn() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM kick_logs WHERE owner_id = ?", (owner_id,))
            return cur.fetchone()[0]
    
    # ---------- Payments ----------
    def add_payment(self, order_id: str, user_id: int, amount: float, days: int):
        with self.get_conn() as conn:
            conn.execute(
                "INSERT INTO payments (order_id, user_id, amount, status, days, created_at) VALUES (?, ?, ?, 'PENDING', ?, ?)",
                (order_id, user_id, amount, days, datetime.now().isoformat())
            )
            conn.commit()
    
    def get_payment_days(self, order_id: str) -> Optional[int]:
        with self.get_conn() as conn:
            cur = conn.execute("SELECT days FROM payments WHERE order_id = ?", (order_id,))
            row = cur.fetchone()
            return row[0] if row else None
    
    def mark_payment_success(self, order_id: str):
        with self.get_conn() as conn:
            conn.execute("UPDATE payments SET status = 'SUCCESS' WHERE order_id = ?", (order_id,))
            conn.commit()
    
    # ---------- Leave Messages ----------
    def save_leave_messages(self, owner_id: int, messages: list):
        with self.get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO leave_messages (owner_id, messages_json) VALUES (?, ?)",
                (owner_id, json.dumps(messages))
            )
            conn.commit()
    
    def get_leave_messages(self, owner_id: int) -> list:
        with self.get_conn() as conn:
            cur = conn.execute("SELECT messages_json FROM leave_messages WHERE owner_id = ?", (owner_id,))
            row = cur.fetchone()
            if row and row[0]:
                return json.loads(row[0])
            return []
    
    # ---------- Agents ----------
    def add_agent(self, session_string: str) -> bool:
        try:
            with self.get_conn() as conn:
                conn.execute(
                    "INSERT INTO agents (session_string, added_at) VALUES (?, ?)",
                    (session_string, datetime.now().isoformat())
                )
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    
    def get_agent_count(self) -> int:
        with self.get_conn() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM agents")
            return cur.fetchone()[0]
    
    def get_random_agent(self) -> Optional[str]:
        with self.get_conn() as conn:
            cur = conn.execute("SELECT session_string FROM agents ORDER BY RANDOM() LIMIT 1")
            row = cur.fetchone()
            return row[0] if row else None
    
    # ---------- Pending DMs ----------
    def add_pending_dm(self, target_user_id: int, owner_id: int):
        with self.get_conn() as conn:
            conn.execute(
                "INSERT INTO pending_dms (target_user_id, owner_id, created_at) VALUES (?, ?, ?)",
                (target_user_id, owner_id, datetime.now().isoformat())
            )
            conn.commit()
    
    def get_pending_dm(self) -> Optional[dict]:
        with self.get_conn() as conn:
            cur = conn.execute(
                "SELECT id, target_user_id, owner_id FROM pending_dms WHERE status='pending' LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                return {'id': row[0], 'target_user_id': row[1], 'owner_id': row[2]}
            return None
    
    def update_pending_dm_status(self, dm_id: int, status: str):
        with self.get_conn() as conn:
            conn.execute("UPDATE pending_dms SET status = ? WHERE id = ?", (status, dm_id))
            conn.commit()
    
    # ---------- States ----------
    def get_state(self, user_id: int) -> Optional[dict]:
        with self.get_conn() as conn:
            cur = conn.execute("SELECT state, data FROM user_states WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            if row:
                return {'state': row[0], 'data': row[1]}
            return None
    
    def set_state(self, user_id: int, state: Optional[str], data: Optional[str] = None):
        with self.get_conn() as conn:
            if state is None:
                conn.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO user_states (user_id, state, data) VALUES (?, ?, ?)",
                    (user_id, state, data)
                )
            conn.commit()
    
    # ---------- Stats ----------
    def get_financial_stats(self) -> dict:
        with self.get_conn() as conn:
            cur = conn.execute("SELECT SUM(amount), COUNT(*) FROM payments WHERE status = 'SUCCESS'")
            row = cur.fetchone()
            return {
                'revenue': float(row[0] or 0),
                'orders': int(row[1] or 0)
            }
    
    def get_recent_payments(self, limit: int = 5) -> list:
        with self.get_conn() as conn:
            cur = conn.execute(
                "SELECT user_id, amount, created_at FROM payments WHERE status = 'SUCCESS' ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
            return [{'user_id': row[0], 'amount': row[1], 'created_at': row[2]} for row in cur.fetchall()]
    
    def get_channel_kick_stats(self) -> list:
        with self.get_conn() as conn:
            cur = conn.execute(
                "SELECT c.title, c.owner_id, COUNT(k.id) AS kicks FROM channels c LEFT JOIN kick_logs k ON c.channel_id = k.channel_id GROUP BY c.channel_id"
            )
            return [{'title': row[0], 'owner_id': row[1], 'kicks': row[2]} for row in cur.fetchall()]

# ----------------- BOT CLASS -----------------
class AntiPremiumBot:
    def __init__(self):
        self.db = Database()
        self.app = Client("bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)
        self.dm_processor_task = None
        self.session = None  # aiohttp session
    
    # ---------- HTTP Helpers ----------
    async def make_post_request(self, url: str, payload: dict) -> Optional[dict]:
        """Make POST request to FAM Gateway with proper headers"""
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        headers = {
            "Authorization": f"Bearer {FAM_API_KEY}",
            "Content-Type": "application/json"
        }
        
        try:
            async with self.session.post(url, json=payload, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logger.error(f"HTTP Error {resp.status}: {await resp.text()}")
                    return None
        except Exception as e:
            logger.error(f"HTTP request failed: {e}")
            return None
    
    # ---------- Payment ----------
    async def initiate_payment(self, user_id: int, chat_id: int, amount: float, days: int):
        """Initiate payment with FAM Gateway - EXACTLY like original"""
        try:
            url = f"{BASE_URL}/api/create-order.php"
            
            payload = {
                "amount": amount,
                "redirect_url": f"https://t.me/YourBotUsername",  # Change this to your bot username
                "upi_id": UPI_ID,
                "payee_name": UPI_NAME
            }
            
            result = await self.make_post_request(url, payload)
            
            if not result or result.get('status') != 'success':
                err_msg = result.get('message', 'Payment gateway error.') if result else 'No response from gateway.'
                await self.app.send_message(chat_id, f"⚠️ Payment Error: {err_msg}")
                return
            
            order_data = result['data']
            order_id = order_data['order_id']
            checkout_url = order_data.get('checkout_url')
            
            # Store payment in DB
            self.db.add_payment(order_id, user_id, amount, days)
            
            plan_str = "Lifetime Access" if days > 36000 else f"{days} Days Access"
            text = f"""💳 **Payment Session Initiated**

• **Product:** {plan_str}
• **Amount:** ₹`{amount}`
• **Session Validity:** `10 Minutes`

Complete the payment via checkout and click **Verify Payment**."""

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Pay Now (UPI / QR)", url=checkout_url)],
                [InlineKeyboardButton("🔄 Verify Payment", callback_data=f"verify_pay:{order_id}")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
            ])
            
            await self.app.send_message(chat_id, text, reply_markup=kb)
            
        except Exception as e:
            logger.error(f"Payment initiation failed: {e}")
            await self.app.send_message(chat_id, f"⚠️ Payment error: {str(e)}")
    
    async def verify_payment(self, order_id: str, chat_id: int, callback_id: str = None):
        """Verify payment with FAM Gateway - EXACTLY like original"""
        try:
            url = f"{BASE_URL}/api/verify-order.php"
            
            payload = {
                "order_id": order_id
            }
            
            result = await self.make_post_request(url, payload)
            
            if result and result.get('status') == 'success':
                days = self.db.get_payment_days(order_id) or 30
                
                # Mark payment as success
                self.db.mark_payment_success(order_id)
                
                # Generate and save key
                new_key = self.db.generate_key(days)
                
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔑 Activate Automatically", callback_data=f"auto_claim:{new_key}")]
                ])
                
                plan_name = "Lifetime" if days > 36000 else f"{days}-Day"
                text = f"🎉 **Payment Verified!**\n\nYour {plan_name} Key:\n`{new_key}`"
                
                await self.app.send_message(chat_id, text, reply_markup=kb)
                
                if callback_id:
                    await self.app.answer_callback_query(callback_id, "✅ Payment verified successfully!")
                return True
            else:
                if callback_id:
                    await self.app.answer_callback_query(
                        callback_id, 
                        "⏳ Payment not received yet. Complete the transaction and try again.",
                        show_alert=True
                    )
                return False
                
        except Exception as e:
            logger.error(f"Payment verification failed: {e}")
            if callback_id:
                await self.app.answer_callback_query(
                    callback_id,
                    f"❌ Verification error: {str(e)}",
                    show_alert=True
                )
            return False
    
    # ---------- Helpers ----------
    def calculate_price(self, input_str: str) -> Tuple[float, int]:
        prices = self.db.get_prices()
        input_str = input_str.lower().strip()
        
        if input_str in ['life', 'lifetime']:
            return prices['price_life'], 36500
        
        try:
            days = int(input_str)
            if days < 7:
                return 0, 0
            if days == 7:
                return prices['price_7'], 7
            if days == 30:
                return prices['price_30'], 30
            
            per_day = prices['price_30'] / 30
            return round(per_day * days, 2), days
        except ValueError:
            return 0, 0
    
    def get_dashboard_text(self, user_id: int) -> str:
        channels = self.db.get_user_channels(user_id)
        channels_list = ', '.join(channels) if channels else 'None registered yet'
        kicked_count = self.db.get_kick_count(user_id)
        approved_count = len(self.db.get_approved_users(user_id))
        has_access, duration = self.db.get_user_access(user_id)
        
        return f"""✅ **ACCESS VERIFIED**

**SAVED CHANNELS:** `{channels_list}`
**Kicked users:** `{kicked_count}`
**Approved users:** `{approved_count}`
**Remaining access duration:** `{duration}`

⚡ _Auto-guard is actively screening Telegram Premium joins._"""
    
    # ---------- Keyboards ----------
    def dashboard_kb(self):
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ Approve User", callback_data="approve_user"),
                InlineKeyboardButton("🗑 Delete Approved", callback_data="del_approved_menu")
            ],
            [
                InlineKeyboardButton("💾 SAVE DM MSG", callback_data="setup_leave_dms")
            ],
            [
                InlineKeyboardButton("🔄 Refresh Dashboard", callback_data="open_dashboard")
            ]
        ])
    
    def admin_dashboard_kb(self):
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🤖 Add Agent Session", callback_data="adm_add_agent")
            ],
            [
                InlineKeyboardButton("💵 Change Pricing", callback_data="adm_change_price_menu"),
                InlineKeyboardButton("🔑 Gen Custom Key", callback_data="adm_gen_key")
            ],
            [
                InlineKeyboardButton("📊 Financial Stats", callback_data="adm_fin_stats"),
                InlineKeyboardButton("📈 Channel Kicks Data", callback_data="adm_kick_stats")
            ],
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="adm_dashboard")
            ]
        ])
    
    def back_kb(self, target: str = "open_dashboard"):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data=target)]
        ])
    
    def start_kb(self):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔑 Enter Access Key", callback_data="enter_key")],
            [InlineKeyboardButton("💳 Buy Subscription", callback_data="buy_key")]
        ])
    
    # ---------- DM Processor (Background) ----------
    async def process_dm_queue(self):
        """Background task to process pending DMs using agents"""
        while True:
            try:
                task = self.db.get_pending_dm()
                if task:
                    agent_session = self.db.get_random_agent()
                    if not agent_session:
                        await asyncio.sleep(3)
                        continue
                    
                    messages = self.db.get_leave_messages(task['owner_id'])
                    if not messages:
                        self.db.update_pending_dm_status(task['id'], 'no_msg')
                        await asyncio.sleep(1)
                        continue
                    
                    try:
                        async with Client(
                            f"agent_{task['id']}", 
                            api_id=API_ID, 
                            api_hash=API_HASH, 
                            session_string=agent_session,
                            in_memory=True
                        ) as agent:
                            await agent.start()
                            for msg in messages:
                                try:
                                    await agent.copy_message(
                                        chat_id=task['target_user_id'],
                                        from_chat_id=msg['chat_id'],
                                        message_id=msg['message_id']
                                    )
                                    await asyncio.sleep(0.5)
                                except Exception as e:
                                    logger.error(f"Failed to send message: {e}")
                            
                            self.db.update_pending_dm_status(task['id'], 'sent')
                    except Exception as e:
                        logger.error(f"Agent failed: {e}")
                        self.db.update_pending_dm_status(task['id'], 'failed')
                
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"DM Processor error: {e}")
                await asyncio.sleep(5)
    
    # ---------- Handlers ----------
    async def start_command(self, client: Client, message: Message):
        user_id = message.from_user.id
        self.db.set_state(user_id, None)
        
        if user_id == ADMIN_ID:
            await message.reply_text(
                "👑 **Admin Master Dashboard**",
                reply_markup=self.admin_dashboard_kb()
            )
            return
        
        has_access, _ = self.db.get_user_access(user_id)
        if has_access:
            await self.show_dashboard(message, user_id)
        else:
            await message.reply_text(
                "🔒 **Access Restricted**\n\nYou need an active subscription key to use this anti-premium guard.",
                reply_markup=self.start_kb()
            )
    
    async def show_dashboard(self, message: Message, user_id: int, callback: bool = False):
        text = self.get_dashboard_text(user_id)
        if callback:
            await message.edit_text(text, reply_markup=self.dashboard_kb())
        else:
            await message.reply_text(text, reply_markup=self.dashboard_kb())
    
    # ---------- Chat Member Updates ----------
    async def chat_member_handler(self, client: Client, chat_member: ChatMemberUpdated):
        chat = chat_member.chat
        new_status = chat_member.new_chat_member.status
        user = chat_member.new_chat_member.user
        
        # Bot became admin in a channel
        if user.id == client.me.id and new_status == ChatMemberStatus.ADMINISTRATOR:
            if chat.type in [ChatType.CHANNEL, ChatType.SUPERGROUP]:
                promoter_id = chat_member.from_user.id
                channel_id = chat.id
                channel_title = chat.title or "Channel"
                
                self.db.add_channel(channel_id, promoter_id, channel_title)
                await client.send_message(
                    promoter_id,
                    f"🎉 **Channel Linked Successfully!**\n\n• **Title:** {channel_title}\n• **ID:** `{channel_id}`\n\nAnti-Premium guard is now active."
                )
            return
        
        # User join/leave events
        if chat.type in [ChatType.CHANNEL, ChatType.SUPERGROUP]:
            owner_id = self.db.get_channel_owner(chat.id)
            if not owner_id:
                return
            
            # Anti-Premium Guard on JOIN
            if new_status == ChatMemberStatus.MEMBER and user.is_premium:
                has_access, _ = self.db.get_user_access(owner_id)
                if has_access:
                    if not self.db.is_approved(owner_id, user.id):
                        self.db.log_kick(owner_id, chat.id, user.id)
                        try:
                            await client.ban_chat_member(chat.id, user.id)
                            logger.info(f"Kicked premium user {user.id} from {chat.id}")
                        except RPCError as e:
                            logger.error(f"Failed to kick: {e}")
            
            # Leave DM Logic
            if new_status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
                messages = self.db.get_leave_messages(owner_id)
                if messages:
                    self.db.add_pending_dm(user.id, owner_id)
    
    # ---------- Callback Query Handler ----------
    async def callback_handler(self, client: Client, callback: CallbackQuery):
        user_id = callback.from_user.id
        data = callback.data
        
        # Agent checker
        if user_id != ADMIN_ID and self.db.get_agent_count() == 0:
            await callback.answer("Agent not added contact owner @absolecore", show_alert=True)
            return
        
        # ---------- Dashboard ----------
        if data == "open_dashboard":
            self.db.set_state(user_id, None)
            has_access, _ = self.db.get_user_access(user_id)
            if not has_access:
                await callback.answer("⚠️ Access expired. Please purchase or enter a new key.", show_alert=True)
                return
            await self.show_dashboard(callback.message, user_id, callback=True)
            await callback.answer()
            return
        
        # ---------- Leave DM Setup ----------
        if data == "setup_leave_dms":
            self.db.set_state(user_id, "waiting_for_leave_msgs", json.dumps([]))
            await callback.message.edit_text(
                "💾 **Leave DM Setup Engine**\n\nJo bhi message (Text, Image, Video, File, Premium Emojis) aap yaha send karoge, wo channel leave karne walo ko automatically agent ke through jayega.\n\n👉 Ek ek karke apne messages send karo.\n👉 Jab saare messages de do, to chat me **SAVE** type karke send karna.",
                reply_markup=self.back_kb("open_dashboard")
            )
            await callback.answer()
            return
        
        # ---------- Key Activation ----------
        if data == "enter_key":
            self.db.set_state(user_id, "waiting_for_key")
            await callback.message.edit_text(
                "🔑 **Send your access key below:**",
                reply_markup=self.back_kb("start_menu")
            )
            await callback.answer()
            return
        
        # ---------- Start Menu ----------
        if data == "start_menu":
            self.db.set_state(user_id, None)
            await callback.message.edit_text(
                "🔒 **Access Restricted**\n\nYou need an active subscription key to use this anti-premium guard.",
                reply_markup=self.start_kb()
            )
            await callback.answer()
            return
        
        # ---------- Buy Subscription ----------
        if data == "buy_key":
            self.db.set_state(user_id, "waiting_for_buy_days")
            prices = self.db.get_prices()
            text = f"""💳 **Buy Premium Subscription**

• **7 Days** : ₹{prices['price_7']}
• **Monthly** : ₹{prices['price_30']}
• **Lifetime** : ₹{prices['price_life']}

_(Custom days parameter applies automatically based on the monthly standard value)_

⌨️ **Reply with the number of days you want (Minimum 7). Type `life` for lifetime access:**"""
            
            await callback.message.edit_text(text, reply_markup=self.back_kb("start_menu"))
            await callback.answer()
            return
        
        # ---------- Verify Payment (REAL VERIFICATION) ----------
        if data.startswith("verify_pay:"):
            order_id = data.split(":")[1]
            
            # Call the real verification
            await self.verify_payment(
                order_id, 
                callback.message.chat.id, 
                callback.id
            )
            return
        
        # ---------- Auto Claim ----------
        if data.startswith("auto_claim:"):
            key_code = data.split(":")[1]
            if self.db.activate_key(user_id, key_code):
                await callback.answer("✅ Key activated successfully!")
                await self.show_dashboard(callback.message, user_id, callback=True)
            else:
                await callback.answer("❌ Key activation failed!", show_alert=True)
            return
        
        # ---------- Approve User ----------
        if data == "approve_user":
            self.db.set_state(user_id, "waiting_for_approved_id")
            await callback.message.edit_text(
                "➕ **Send the Telegram User ID** to approve (will skip premium ban):",
                reply_markup=self.back_kb("open_dashboard")
            )
            await callback.answer()
            return
        
        # ---------- Delete Approved Menu ----------
        if data == "del_approved_menu":
            users = self.db.get_approved_users(user_id)
            if not users:
                await callback.message.edit_text(
                    "ℹ️ No approved users found in your whitelist.",
                    reply_markup=self.back_kb("open_dashboard")
                )
                await callback.answer()
                return
            
            buttons = []
            for u in users:
                buttons.append([
                    InlineKeyboardButton(
                        f"❌ {u['username']} ({u['id']})",
                        callback_data=f"del_user:{u['id']}"
                    )
                ])
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="open_dashboard")])
            
            await callback.message.edit_text(
                "🗑 **SELECT whom to delete from approved whitelist:**",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            await callback.answer()
            return
        
        # ---------- Delete User ----------
        if data.startswith("del_user:"):
            target_id = int(data.split(":")[1])
            self.db.remove_approved_user(user_id, target_id)
            await callback.answer("User removed from whitelist.", show_alert=True)
            # Refresh the menu
            await self.callback_handler(client, callback.__class__(
                id=callback.id,
                from_user=callback.from_user,
                message=callback.message,
                data="del_approved_menu",
                chat_instance=callback.chat_instance
            ))
            return
        
        # ---------- Admin Handlers ----------
        if user_id == ADMIN_ID:
            if data == "adm_dashboard":
                self.db.set_state(user_id, None)
                await callback.message.edit_text(
                    "👑 **Admin Master Dashboard**",
                    reply_markup=self.admin_dashboard_kb()
                )
                await callback.answer()
                return
            
            if data == "adm_add_agent":
                self.db.set_state(user_id, "waiting_for_agent_session")
                await callback.message.edit_text(
                    "🤖 **Add New Pyrogram Agent**\n\nPlease send the Pyrogram String Session for the agent account below:",
                    reply_markup=self.back_kb("adm_dashboard")
                )
                await callback.answer()
                return
            
            if data == "adm_change_price_menu":
                kb = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("💵 7-Day Price", callback_data="set_price:price_7"),
                        InlineKeyboardButton("💵 Monthly Price", callback_data="set_price:price_30")
                    ],
                    [
                        InlineKeyboardButton("💵 Lifetime Price", callback_data="set_price:price_life")
                    ],
                    [
                        InlineKeyboardButton("🔙 Back", callback_data="adm_dashboard")
                    ]
                ])
                await callback.message.edit_text(
                    "💰 **Select which plan's price you want to update:**\n_(Custom days dynamically calculate using monthly)_",
                    reply_markup=kb
                )
                await callback.answer()
                return
            
            if data.startswith("set_price:"):
                plan = data.split(":")[1]
                self.db.set_state(user_id, f"waiting_for_{plan}")
                await callback.message.edit_text(
                    f"✏️ Enter new price in INR for **{plan}**:",
                    reply_markup=self.back_kb("adm_change_price_menu")
                )
                await callback.answer()
                return
            
            if data == "adm_gen_key":
                self.db.set_state(user_id, "waiting_for_custom_key_days")
                await callback.message.edit_text(
                    "⌛ Enter duration for the key in days (e.g. `28`):",
                    reply_markup=self.back_kb("adm_dashboard")
                )
                await callback.answer()
                return
            
            if data == "adm_fin_stats":
                stats = self.db.get_financial_stats()
                recent = self.db.get_recent_payments()
                
                text = f"""💵 **Financial Overview**

• **Total Revenue:** ₹`{stats['revenue']:.2f}`
• **Total Orders:** `{stats['orders']}`

**Recent 5 Payments:**"""
                
                for p in recent:
                    date_str = p['created_at'][:10]
                    text += f"\n• User `{p['user_id']}`: ₹`{p['amount']}` ({date_str})"
                
                await callback.message.edit_text(text, reply_markup=self.back_kb("adm_dashboard"))
                await callback.answer()
                return
            
            if data == "adm_kick_stats":
                stats = self.db.get_channel_kick_stats()
                text = "📈 **Channel Protection Statistics**\n\n"
                if not stats:
                    text += "No active channels registered."
                else:
                    for st in stats:
                        text += f"• **{st['title']}** (Owner: `{st['owner_id']}`): `{st['kicks']}` kicked\n"
                
                await callback.message.edit_text(text, reply_markup=self.back_kb("adm_dashboard"))
                await callback.answer()
                return
    
    # ---------- Message Handler ----------
    async def message_handler(self, client: Client, message: Message):
        user_id = message.from_user.id
        text = message.text.strip() if message.text else ""
        
        # Agent Check Blocker
        if user_id != ADMIN_ID and self.db.get_agent_count() == 0:
            await message.reply_text("Agent not added contact owner @absolecore")
            return
        
        state_data = self.db.get_state(user_id)
        state = state_data['state'] if state_data else None
        
        # ---------- Admin: Add Agent ----------
        if state == "waiting_for_agent_session" and user_id == ADMIN_ID:
            if self.db.add_agent(text):
                self.db.set_state(user_id, None)
                await message.reply_text(
                    "✅ **Agent Added Successfully!**\nThe internal Python engine can now use this session to send DMs.",
                    reply_markup=self.admin_dashboard_kb()
                )
            else:
                await message.reply_text("⚠️ Failed to add agent: It might already exist.")
            return
        
        # ---------- Leave Messages Setup ----------
        if state == "waiting_for_leave_msgs":
            if text.upper() == "SAVE":
                msgs = json.loads(state_data['data'] or "[]") if state_data else []
                if not msgs:
                    await message.reply_text("⚠️ Koi message queue me nahi tha. Save cancel ho gaya.")
                else:
                    self.db.save_leave_messages(user_id, msgs)
                    await message.reply_text(
                        f"✅ Total **{len(msgs)}** messages successfully save ho gaye hain.\nAb channel se jo bhi leave karega use Agent yahi send karega.",
                        reply_markup=self.dashboard_kb()
                    )
                self.db.set_state(user_id, None)
                return
            else:
                msgs = json.loads(state_data['data'] or "[]") if state_data else []
                msgs.append({
                    'chat_id': message.chat.id,
                    'message_id': message.id
                })
                self.db.set_state(user_id, "waiting_for_leave_msgs", json.dumps(msgs))
                await message.reply_text(
                    f"📥 **Message Saved to Queue!** (Total: {len(msgs)})\n\n👉 Agar aur messages dena hai to send karo, varna chat me **SAVE** type karo finalize karne ke liye."
                )
                return
        
        # ---------- Key Activation ----------
        if state == "waiting_for_key":
            if self.db.activate_key(user_id, text):
                self.db.set_state(user_id, None)
                await self.show_dashboard(message, user_id)
            else:
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Try Again", callback_data="enter_key")],
                    [InlineKeyboardButton("💳 Buy Subscription", callback_data="buy_key")]
                ])
                await message.reply_text(
                    "❌ **Invalid or Already Used Key!**",
                    reply_markup=kb
                )
            return
        
        # ---------- Buy Custom Days ----------
        if state == "waiting_for_buy_days":
            price, days = self.calculate_price(text)
            if days == 0:
                await message.reply_text(
                    "⚠️ **Invalid input.**\nMinimum 7 days allowed. Enter a valid number or type `life` for lifetime:"
                )
                return
            
            self.db.set_state(user_id, None)
            await self.initiate_payment(user_id, message.chat.id, price, days)
            return
        
        # ---------- Approved User Whitelist ----------
        if state == "waiting_for_approved_id":
            if not text.isdigit():
                await message.reply_text("⚠️ Please provide a valid numerical Telegram User ID.")
                return
            
            target_id = int(text)
            self.db.add_approved_user(user_id, target_id, f"ID:{target_id}")
            self.db.set_state(user_id, None)
            await message.reply_text(f"✅ User `{target_id}` has been added to your whitelist.")
            await self.show_dashboard(message, user_id)
            return
        
        # ---------- Admin: Change Price ----------
        if state and state.startswith("waiting_for_price_") and user_id == ADMIN_ID:
            try:
                new_price = float(text)
                config_key = state.replace("waiting_for_", "")
                self.db.set_config(config_key, str(new_price))
                self.db.set_state(user_id, None)
                await message.reply_text(
                    f"✅ Price for `{config_key}` updated successfully to ₹`{new_price}`",
                    reply_markup=self.admin_dashboard_kb()
                )
            except ValueError:
                await message.reply_text("⚠️ Please send a valid numeric price.")
            return
        
        # ---------- Admin: Generate Custom Key ----------
        if state == "waiting_for_custom_key_days" and user_id == ADMIN_ID:
            if not text.isdigit():
                await message.reply_text("⚠️ Please enter a valid number of days.")
                return
            
            days = int(text)
            new_key = self.db.generate_key(days)
            self.db.set_state(user_id, None)
            await message.reply_text(
                f"✅ **Generated {days}-Day Key:**\n`{new_key}`",
                reply_markup=self.admin_dashboard_kb()
            )
            return
    
    # ---------- Run ----------
    async def run(self):
        # Start DM processor
        self.dm_processor_task = asyncio.create_task(self.process_dm_queue())
        
        # Create aiohttp session
        self.session = aiohttp.ClientSession()
        
        # Register handlers
        self.app.on_message(filters.command("start"))(self.start_command)
        self.app.on_message(filters.text & ~filters.command("start"))(self.message_handler)
        self.app.on_callback_query()(self.callback_handler)
        self.app.on_chat_member_updated()(self.chat_member_handler)
        
        logger.info("🚀 Anti-Premium Guard Bot started!")
        logger.info(f"📱 UPI ID: {UPI_ID}")
        logger.info(f"🔑 API Key: {FAM_API_KEY[:20]}...")
        await self.app.start()
        
        try:
            await asyncio.Event().wait()
        finally:
            await self.session.close()

# ----------------- MAIN -----------------
if __name__ == "__main__":
    # Fix for Windows event loop
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    bot = AntiPremiumBot()
    asyncio.run(bot.run())
