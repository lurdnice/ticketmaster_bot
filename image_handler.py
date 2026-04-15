import base64
import io
import asyncio
from typing import Optional, Tuple
from PIL import Image
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import aiohttp
import logging

logger = logging.getLogger(__name__)

class ImageHandler:
    @staticmethod
    async def capture_event_image(driver, event_url: str) -> Optional[str]:
        """Capture event image and return as base64"""
        try:
            # Navigate to event page
            driver.get(event_url)
            await asyncio.sleep(3)
            
            # Find event image
            image_selectors = [
                "//img[contains(@class, 'event-image')]",
                "//img[contains(@class, 'hero-image')]",
                "//div[contains(@class, 'image')]//img",
                "//meta[@property='og:image']",
                "//img[@data-testid='event-image']",
                "//picture//img"
            ]
            
            image_url = None
            for selector in image_selectors:
                try:
                    if selector.startswith("//meta"):
                        element = driver.find_element(By.XPATH, selector)
                        image_url = element.get_attribute('content')
                    else:
                        element = driver.find_element(By.XPATH, selector)
                        image_url = element.get_attribute('src')
                    
                    if image_url and not image_url.startswith('data:'):
                        break
                except:
                    continue
            
            if not image_url:
                # Try to get from background image
                try:
                    style_element = driver.find_element(By.XPATH, "//div[contains(@class, 'hero')]")
                    style = style_element.get_attribute('style')
                    if 'background-image' in style:
                        import re
                        match = re.search(r'url\("?(.*?)"?\)', style)
                        if match:
                            image_url = match.group(1)
                except:
                    pass
            
            if image_url:
                # Download and convert image
                async with aiohttp.ClientSession() as session:
                    async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status == 200:
                            image_data = await response.read()
                            # Optimize image
                            img = Image.open(io.BytesIO(image_data))
                            # Resize if too large
                            if img.size[0] > 1200:
                                ratio = 1200 / img.size[0]
                                new_size = (1200, int(img.size[1] * ratio))
                                img = img.resize(new_size, Image.Resampling.LANCZOS)
                            # Convert to base64
                            buffered = io.BytesIO()
                            img.save(buffered, format="JPEG", quality=85)
                            img_base64 = base64.b64encode(buffered.getvalue()).decode()
                            return f"data:image/jpeg;base64,{img_base64}"
            return None
            
        except Exception as e:
            logger.error(f"Error capturing image: {e}")
            return None
    
    @staticmethod
    async def download_event_images(event_urls: list, driver) -> dict:
        """Download images for multiple events"""
        images = {}
        for url in event_urls[:5]:  # Limit to 5 images
            try:
                img = await ImageHandler.capture_event_image(driver, url)
                if img:
                    images[url] = img
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Error downloading image for {url}: {e}")
        return images