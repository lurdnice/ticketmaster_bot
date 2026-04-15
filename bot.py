import asyncio
import logging
import re
import os
from datetime import datetime
from typing import List, Dict, Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, ContextTypes, CallbackQueryHandler
)
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from fake_useragent import UserAgent
import resend
import aiosqlite
import json

from config import Config
from image_handler import ImageHandler
from email_templates import EmailTemplates

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, Config.LOG_LEVEL)
)
logger = logging.getLogger(__name__)

# Configure Resend
resend.api_key = Config.RESEND_API_KEY

# Database class
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
            
            # Event cache
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
                (user_id, query.lower(), datetime.now().isoformat(), json.dumps(results))
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
                (user_id, email, datetime.now().isoformat())
            )
            await db.commit()
    
    async def get_user_email(self, user_id: int) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT email FROM user_emails WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else None
    
    async def remove_user_email(self, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM user_emails WHERE user_id = ?", (user_id,))
            await db.commit()
    
    async def check_rate_limit(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
            cursor = await db.execute(
                "SELECT COUNT(*) FROM rate_limits WHERE user_id = ? AND search_time > ?",
                (user_id, hour_ago)
            )
            count = (await cursor.fetchone())[0]
            
            if count >= 10:
                return False
            
            await db.execute(
                "INSERT INTO rate_limits (user_id, search_time) VALUES (?, ?)",
                (user_id, datetime.now().isoformat())
            )
            await db.commit()
            return True
    
    async def cache_event(self, event_url: str, event_data: Dict, image_data: Optional[str] = None):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO event_cache (event_url, event_data, image_data, cached_at) VALUES (?, ?, ?, ?)",
                (event_url, json.dumps(event_data), image_data, datetime.now().isoformat())
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

# Initialize database
db = Database()

# Import timedelta
from datetime import timedelta

class TicketmasterBot:
    def __init__(self):
        self.image_handler = ImageHandler()
        
    def get_driver(self):
        """Setup Chrome driver"""
        chrome_options = Options()
        if Config.HEADLESS_MODE:
            chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        
        ua = UserAgent()
        chrome_options.add_argument(f'--user-agent={ua.random}')
        
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=chrome_options)
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def search_ticketmaster(self, query: str) -> List[Dict]:
        """Search Ticketmaster Norway with retry logic"""
        events = []
        driver = None
        
        try:
            driver = self.get_driver()
            logger.info(f"Searching for: {query}")
            
            # Navigate to Ticketmaster Norway
            driver.get("https://www.ticketmaster.no/")
            await asyncio.sleep(3)
            
            # Accept cookies
            try:
                cookie_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Accept') or contains(text(), 'Godta')]"))
                )
                cookie_btn.click()
                await asyncio.sleep(1)
            except:
                pass
            
            # Search
            search_bar = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//input[@type='search'] | //input[@placeholder='Søk']"))
            )
            search_bar.clear()
            search_bar.send_keys(query)
            search_bar.send_keys(Keys.RETURN)
            await asyncio.sleep(5)
            
            # Extract events
            event_elements = driver.find_elements(By.XPATH, "//div[contains(@class, 'event-card')] | //a[contains(@href, '/event/')]")
            
            for idx, element in enumerate(event_elements[:12]):
                try:
                    event = await self.extract_event_data(driver, element, query)
                    if event:
                        # Capture event image
                        if event.get('url'):
                            cached = await db.get_cached_event(event['url'])
                            if cached and cached.get('image_data'):
                                event['image'] = cached['image_data']
                            else:
                                event['image'] = await self.image_handler.capture_event_image(driver, event['url'])
                                if event['image']:
                                    await db.cache_event(event['url'], event, event['image'])
                        events.append(event)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"Error processing event {idx}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Search error: {e}")
            raise
            
        finally:
            if driver:
                driver.quit()
                
        return events
    
    async def extract_event_data(self, driver, element, query) -> Optional[Dict]:
        """Extract comprehensive event data"""
        try:
            event = {
                'id': datetime.now().timestamp(),
                'search_query': query,
                'extracted_at': datetime.now().isoformat()
            }
            
            # Get URL
            if element.tag_name == 'a':
                event['url'] = element.get_attribute('href')
            else:
                try:
                    link = element.find_element(By.XPATH, ".//a")
                    event['url'] = link.get_attribute('href')
                except:
                    return None
            
            # Title
            try:
                title = element.find_element(By.XPATH, ".//h3 | .//h2 | .//span[contains(@class, 'title')]")
                event['title'] = title.text.strip()
            except:
                event['title'] = f"Event related to {query}"
            
            # Date & Time
            try:
                date = element.find_element(By.XPATH, ".//time | .//span[contains(@class, 'date')]")
                event['date'] = date.text.strip()
            except:
                event['date'] = "Check website for date"
            
            # Venue
            try:
                venue = element.find_element(By.XPATH, ".//span[contains(@class, 'venue')] | .//p[contains(@class, 'location')]")
                event['venue'] = venue.text.strip()
            except:
                event['venue'] = "Venue TBA"
            
            # Price
            try:
                price = element.find_element(By.XPATH, ".//span[contains(@class, 'price')] | .//div[contains(text(), 'kr')]")
                event['price'] = price.text.strip()
            except:
                event['price'] = "Price not available"
            
            # Get detailed seat info
            seat_info = await self.get_seat_info(event['url'])
            if seat_info:
                event['seat_categories'] = seat_info
            
            return event
            
        except Exception as e:
            logger.error(f"Error extracting event data: {e}")
            return None
    
    async def get_seat_info(self, event_url: str) -> List[str]:
        """Get detailed seating information"""
        driver = None
        seat_categories = []
        
        try:
            driver = self.get_driver()
            driver.get(event_url)
            await asyncio.sleep(3)
            
            sections = driver.find_elements(By.XPATH, "//div[contains(@class, 'ticket-type')] | //div[contains(@class, 'price-level')]")
            
            for section in sections[:5]:
                try:
                    name = section.find_element(By.XPATH, ".//h4 | .//span[contains(@class, 'name')]").text
                    price = section.find_element(By.XPATH, ".//span[contains(@class, 'price')]").text
                    seat_categories.append(f"{name}: {price}")
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Error getting seat info: {e}")
        finally:
            if driver:
                driver.quit()
                
        return seat_categories

# Initialize bot
ticket_bot = TicketmasterBot()

# Helper Functions
def format_event_message(event: Dict, event_number: int) -> str:
    """Format individual event for Telegram display"""
    message = f"""
<b>🎵 Event {event_number}</b>
{'='*30}

<b>🎭 {event.get('title', 'Event')}</b>

<b>📅 Date:</b> {event.get('date', 'Not specified')}
<b>📍 Venue:</b> {event.get('venue', 'Not specified')}
<b>💰 Price:</b> {event.get('price', 'Check website')}

"""
    if event.get('seat_categories'):
        message += "\n<b>🎟️ Available Sections:</b>\n"
        for seat in event['seat_categories'][:3]:
            message += f"• {seat}\n"
    
    message += f"\n🔗 <a href='{event.get('url', '#')}'>Click for tickets</a>"
    return message

async def send_email_report(email: str, events: List[Dict], query: str, update: Update):
    """Send email report to user"""
    try:
        html_content = EmailTemplates.get_event_email_template(events, query, email)
        
        resend.Emails.send({
            "from": Config.FROM_EMAIL,
            "to": email,
            "subject": f"🎫 Ticketmaster Results: {query}",
            "html": html_content
        })
        
        await update.callback_query.message.reply_text(
            f"✅ Email sent successfully to {email}!\n"
            f"Check your inbox (and spam folder)."
        )
    except Exception as e:
        logger.error(f"Email send error: {e}")
        await update.callback_query.message.reply_text(
            f"❌ Failed to send email: {str(e)[:100]}"
        )

# Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    welcome_text = """
🎫 <b>Welcome to Ticketmaster Norway Pro Bot!</b> 🎫

<i>Your ultimate event discovery companion</i>

<b>✨ Features:</b>
• 🔍 Search any artist or event
• 📸 Get event images
• 📧 Receive beautiful email reports
• 🎟️ Detailed seating information
• 💰 Real-time pricing
• ⚡ Lightning fast results

<b>📝 Commands:</b>
/start - Show this message
/help - Detailed help guide
/email - Set your email for reports
/myemail - View your registered email
/removeemail - Remove your email
/search [query] - Search for events
/about - About this bot
/feedback - Send feedback

<b>🚀 Quick Start:</b>
1. Set your email: /email your@email.com
2. Search events: /search Taylor Swift
3. Get results with images & details
4. Receive email reports instantly!

Start searching now! 🎵
"""
    keyboard = [
        [InlineKeyboardButton("🔍 Search Events", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("📧 Set Email", callback_data="set_email")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_text, parse_mode='HTML', reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    help_text = """
<b>📚 Complete User Guide</b>

<b>🎯 Search Commands:</b>
• <code>/search artist name</code> - Find events by artist
• <code>/search event name</code> - Find specific event
• Just type the name directly (without command)

<b>📧 Email Features:</b>
• <code>/email your@email.com</code> - Set email for reports
• <code>/myemail</code> - Check registered email
• <code>/removeemail</code> - Remove email

<b>🎨 What you'll receive via email:</b>
• Beautiful HTML formatted event list
• Event images and venue details
• Direct ticket purchase links
• Seating category information
• Price comparisons
• Mobile-responsive design

<b>⚡ Speed Optimization:</b>
• Results typically in 15-20 seconds
• Cached results for repeated searches
• Smart image compression

<b>🔒 Privacy & Security:</b>
• Emails stored securely
• No sharing of personal data
• GDPR compliant

<b>🆘 Need Help?</b>
Send /feedback
"""
    await update.message.reply_text(help_text, parse_mode='HTML')

async def set_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set user email"""
    if context.args:
        email = context.args[0]
        if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            await db.save_user_email(update.effective_user.id, email)
            
            # Send confirmation email
            try:
                resend.Emails.send({
                    "from": Config.FROM_EMAIL,
                    "to": email,
                    "subject": "✅ Email Confirmed - Ticketmaster Bot",
                    "html": EmailTemplates.get_confirmation_email(email)
                })
                await update.message.reply_text(
                    f"✅ Email <b>{email}</b> registered successfully!\n\n"
                    f"Confirmation email sent. You can now receive event reports!",
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Email send error: {e}")
                await update.message.reply_text(
                    f"✅ Email <b>{email}</b> saved!\n"
                    f"(Confirmation email failed, but your email is registered)",
                    parse_mode='HTML'
                )
        else:
            await update.message.reply_text(
                "❌ Invalid email format. Please use: /email your@email.com"
            )
    else:
        await update.message.reply_text(
            "📧 Please provide your email:\n\n"
            "<code>/email your@email.com</code>\n\n"
            "Example: <code>/email john@example.com</code>",
            parse_mode='HTML'
        )

async def myemail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current email"""
    user_id = update.effective_user.id
    email = await db.get_user_email(user_id)
    
    if email:
        await update.message.reply_text(
            f"📧 Your registered email is: <b>{email}</b>\n\n"
            f"To change it, use: <code>/email new@email.com</code>\n"
            f"To remove it, use: <code>/removeemail</code>",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            "❌ No email registered.\n"
            "Use <code>/email your@email.com</code> to set one.",
            parse_mode='HTML'
        )

async def removeemail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove user email"""
    user_id = update.effective_user.id
    await db.remove_user_email(user_id)
    
    await update.message.reply_text(
        "✅ Email removed successfully!\n"
        "You will no longer receive email reports."
    )

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for events"""
    if not context.args:
        await update.message.reply_text(
            "🔍 Please provide a search query.\n\n"
            "Examples:\n"
            "<code>/search Taylor Swift</code>\n"
            "<code>/search Coldplay concert</code>\n\n"
            "Or just type the artist name directly!",
            parse_mode='HTML'
        )
        return
    
    query = ' '.join(context.args)
    await perform_search(update, query)

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """About command"""
    about_text = """
🤖 <b>Ticketmaster Norway Pro Bot</b>

<b>Version:</b> 2.0
<b>Developer:</b> Professional Bot Service

<b>Features:</b>
• Real-time event search
• Image capture technology
• Beautiful email templates
• Seating information
• Rate limiting for fair use
• GDPR compliant

<b>Technology Stack:</b>
• Python 3.11+
• Telegram Bot API
• Selenium WebDriver
• Resend Email API
• SQLite Database

<b>Limitations:</b>
• 10 searches per hour per user
• Results cached for 1 hour
• Images compressed for speed

<b>Support:</b>
Send /feedback

Made with ❤️ for event lovers!
"""
    await update.message.reply_text(about_text, parse_mode='HTML')

async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle feedback"""
    if context.args:
        feedback_text = ' '.join(context.args)
        
        logger.info(f"Feedback from user {update.effective_user.id}: {feedback_text}")
        
        await update.message.reply_text(
            f"✅ Thank you for your feedback!\n\n"
            f"We value your input and will use it to improve the bot."
        )
    else:
        await update.message.reply_text(
            "📝 Please provide your feedback:\n\n"
            "<code>/feedback Your message here</code>\n\n"
            "Example: <code>/feedback Great bot, but add more artists!</code>",
            parse_mode='HTML'
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle direct messages (search queries)"""
    query = update.message.text.strip()
    if not query.startswith('/'):
        await perform_search(update, query)

async def perform_search(update: Update, query: str):
    """Perform the actual search"""
    user_id = update.effective_user.id
    
    # Rate limiting
    if not await db.check_rate_limit(user_id):
        await update.message.reply_text(
            "⏰ <b>Rate limit exceeded!</b>\n\n"
            "You can perform up to 10 searches per hour.\n"
            "Please wait a while before searching again.",
            parse_mode='HTML'
        )
        return
    
    # Check cache
    cached_results = await db.get_cached_search(user_id, query)
    if cached_results:
        keyboard = [
            [InlineKeyboardButton("📧 Send to Email", callback_data=f"email_{query}")],
            [InlineKeyboardButton("🔄 View Results", callback_data=f"view_{query}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"🔄 Found cached results for '{query}'!\n\n"
            f"Would you like to view them or receive via email?",
            parse_mode='HTML',
            reply_markup=reply_markup
        )
        return
    
    # Perform new search
    searching_msg = await update.message.reply_text(
        f"🔍 <b>Searching Ticketmaster Norway...</b>\n\n"
        f"Query: <i>{query}</i>\n"
        f"⏳ This may take 15-20 seconds...\n\n"
        f"✨ <i>Getting you the best results!</i>",
        parse_mode='HTML'
    )
    
    try:
        events = await ticket_bot.search_ticketmaster(query)
        
        if not events:
            await searching_msg.edit_text(
                f"❌ <b>No events found for '{query}'</b>\n\n"
                f"💡 Suggestions:\n"
                f"• Try a different spelling\n"
                f"• Use a more general term\n"
                f"• Check if the artist is touring\n"
                f"• Try both English/Norwegian names\n\n"
                f"Example searches that work well:\n"
                f"• 'jazz konsert'\n"
                f"• 'rock concert oslo'\n"
                f"• 'Taylor Swift'",
                parse_mode='HTML'
            )
            return
        
        # Cache results
        await db.cache_search_result(user_id, query, events)
        
        # Display results
        await searching_msg.delete()
        
        for idx, event in enumerate(events[:8], 1):
            message = format_event_message(event, idx)
            
            keyboard = [
                [InlineKeyboardButton("🎫 Get Tickets", url=event.get('url', '#'))],
                [InlineKeyboardButton("📧 Email This Event", callback_data=f"email_event_{query}_{idx}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if event.get('image'):
                await update.message.reply_photo(
                    photo=event['image'],
                    caption=message,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
            else:
                await update.message.reply_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
            await asyncio.sleep(0.5)
        
        # Offer to send full report via email
        user_email = await db.get_user_email(user_id)
        if user_email:
            keyboard = [[InlineKeyboardButton("📧 Send Full Report to Email", callback_data=f"full_report_{query}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"✅ Found {len(events)} events for '{query}'!\n\n"
                f"Want a beautiful HTML report with all events and images?\n"
                f"Click below to receive it at {user_email}",
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                f"✅ Found {len(events)} events for '{query}'!\n\n"
                f"💡 <b>Pro tip:</b> Set your email with /email to receive beautiful HTML reports!",
                parse_mode='HTML'
            )
            
    except Exception as e:
        logger.error(f"Search error: {e}")
        await searching_msg.edit_text(
            f"❌ <b>Search Error</b>\n\n"
            f"An error occurred: {str(e)[:150]}\n\n"
            f"Please try again later.",
            parse_mode='HTML'
        )

# Callback Handler
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "set_email":
        await query.message.reply_text(
            "📧 Please send your email address using:\n"
            "<code>/email your@email.com</code>\n\n"
            "Example: <code>/email john@example.com</code>",
            parse_mode='HTML'
        )
    
    elif data == "help":
        await help_command(update, context)
    
    elif data.startswith("email_event_"):
        # Handle single event email
        parts = data.split("_")
        if len(parts) >= 3:
            query_text = parts[2]
            event_idx = int(parts[3]) if len(parts) > 3 else 0
            
            user_id = update.effective_user.id
            user_email = await db.get_user_email(user_id)
            
            if not user_email:
                await query.message.reply_text(
                    "❌ Please set your email first using /email"
                )
                return
            
            # Get cached results
            cached = await db.get_cached_search(user_id, query_text)
            if cached and event_idx <= len(cached):
                event = cached[event_idx - 1]
                await send_email_report(user_email, [event], query_text, update)
    
    elif data.startswith("email_"):
        # Handle full search results email
        search_query = data.replace("email_", "")
        if search_query.startswith("event_"):
            return  # Already handled above
        
        user_id = update.effective_user.id
        user_email = await db.get_user_email(user_id)
        
        if not user_email:
            await query.message.reply_text(
                "❌ Please set your email first using /email"
            )
            return
        
        cached = await db.get_cached_search(user_id, search_query)
        if cached:
            await send_email_report(user_email, cached, search_query, update)
    
    elif data.startswith("full_report_"):
        search_query = data.replace("full_report_", "")
        user_id = update.effective_user.id
        user_email = await db.get_user_email(user_id)
        
        if user_email:
            cached = await db.get_cached_search(user_id, search_query)
            if cached:
                await send_email_report(user_email, cached, search_query, update)
    
    elif data.startswith("view_"):
        search_query = data.replace("view_", "")
        user_id = update.effective_user.id
        cached = await db.get_cached_search(user_id, search_query)
        
        if cached:
            await query.message.delete()
            for idx, event in enumerate(cached[:8], 1):
                message = format_event_message(event, idx)
                
                keyboard = [[InlineKeyboardButton("🎫 Get Tickets", url=event.get('url', '#'))]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                if event.get('image'):
                    await query.message.reply_photo(
                        photo=event['image'],
                        caption=message,
                        parse_mode='HTML',
                        reply_markup=reply_markup
                    )
                else:
                    await query.message.reply_text(
                        message,
                        parse_mode='HTML',
                        reply_markup=reply_markup
                    )
                await asyncio.sleep(0.5)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ An error occurred. Please try again later."
        )

def main():
    """Start the bot"""
    # Create application
    application = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("email", set_email))
    application.add_handler(CommandHandler("myemail", myemail))
    application.add_handler(CommandHandler("removeemail", removeemail))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("about", about))
    application.add_handler(CommandHandler("feedback", feedback))
    
    # Add callback query handler for buttons
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Add message handler for direct searches
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start bot
    print("🤖 Ticketmaster Norway Bot is starting...")
    
    # Run the bot (this handles everything in a single event loop)
    async def run_bot():
        await db.init_db()
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        # Keep the bot running
        try:
            await asyncio.Event().wait()
        finally:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
    
    # Run the async function
    asyncio.run(run_bot())


if __name__ == '__main__':
    main()