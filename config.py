import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    
    # Resend Email
    RESEND_API_KEY = os.getenv('RESEND_API_KEY')
    FROM_EMAIL = os.getenv('FROM_EMAIL', 'ticketmaster@yourdomain.com')
    
    # Rate limiting
    MAX_SEARCHES_PER_USER = 10  # per hour
    SEARCH_TIMEOUT = 30  # seconds
    
    # Cache
    CACHE_TTL = 3600  # 1 hour
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///ticketmaster.db')
    
    # Selenium
    HEADLESS_MODE = os.getenv('HEADLESS_MODE', 'True') == 'True'
    
    # Allowed users (empty = all users)
    ALLOWED_USER_IDS = os.getenv('ALLOWED_USER_IDS', '').split(',') if os.getenv('ALLOWED_USER_IDS') else []
    
    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')