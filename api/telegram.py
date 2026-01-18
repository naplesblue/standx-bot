"""
Telegram Bot Application Interface.
Handles interactive commands via long-polling.
"""
import logging
import asyncio
import httpx
from core.reporting import parse_efficiency_log, generate_efficiency_report_text

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self, token: str, allowed_chat_id: str):
        self.token = token
        self.allowed_chat_id = str(allowed_chat_id)
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.offset = 0
        self.running = False
        
    async def run(self):
        """Start the bot polling loop."""
        logger.info("Starting Telegram Bot polling...")
        self.running = True
        
        while self.running:
            try:
                updates = await self.get_updates()
                for update in updates:
                    await self.process_update(update)
                    # Update offset to confirm receipt
                    self.offset = update["update_id"] + 1
                    
                # Short sleep to avoid busy loop if no updates/error
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                logger.info("Telegram Bot stopped.")
                break
            except Exception as e:
                logger.error(f"Telegram polling error: {e}")
                await asyncio.sleep(5) # Backoff on error

    async def get_updates(self):
        """Long-poll for new updates."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    f"{self.base_url}/getUpdates",
                    params={"offset": self.offset, "timeout": 20}
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        return data.get("result", [])
        except httpx.ReadTimeout:
            pass # Normal timeout
        except Exception:
            raise
        return []

    async def process_update(self, update: dict):
        """Process a single update."""
        if "message" not in update:
            return
            
        message = update["message"]
        chat_id = str(message.get("chat", {}).get("id"))
        text = message.get("text", "")
        
        # Security Check: Only allow configured chat_id
        if chat_id != self.allowed_chat_id:
            logger.warning(f"Ignored command from unauthorized chat_id: {chat_id}")
            return
            
        if text.startswith("/status"):
            await self.handle_status_command(chat_id)

    async def handle_status_command(self, chat_id: str):
        """Handle /status command."""
        logger.info("Received /status command from authorized user.")
        
        # Send "Processing..." typing status or message? 
        # Just process and send.
        
        # Parse logs for last 4 hours
        stats = parse_efficiency_log("efficiency.log", hours=4)
        report_text = generate_efficiency_report_text(stats, hours=4)
        
        await self.send_message(chat_id, report_text)

    async def send_message(self, chat_id: str, text: str):
        """Send a message to a chat."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "Markdown"
                    }
                )
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

    def stop(self):
        """Stop the polling loop."""
        self.running = False
