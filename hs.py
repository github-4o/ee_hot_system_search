import discord
from discord.ext import commands
import aiohttp
import io
import os
import re
import json
import collections
import difflib
import asyncio
from datetime import datetime, timedelta, timezone
from PIL import Image
import pytesseract
from typing import Tuple, List

# ==============================================================================
# STRICT ENVIRONMENT VARIABLE CONFIGURATION
# The bot will crash on startup if these are not set in the environment.
# ==============================================================================
PROXY_URL = os.environ['HTTPS_PROXY']
TARGET_CHANNEL_ID = int(os.environ['TARGET_CHANNEL_ID'])

class KillmailAnalyzerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: aiohttp.ClientSession = None
        self.CROP_BOX = (100, 30, 500, 80)
        self.MAX_JUMPS = 7
        self.MAX_REPORT_LENGTH = 128
        self.MAX_REPORTS = 3
        
        self.system_names = []
        self.id_to_name = {}
        self.name_to_id = {}
        self.graph = collections.defaultdict(list)

    async def cog_load(self):
        connector = aiohttp.TCPConnector()
        self.session = aiohttp.ClientSession(connector=connector)
        await self.load_systems("systems.json")

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    async def load_systems(self, filepath: str):
        # Strictly require the real systems.json file. No mock data.
        if not os.path.exists(filepath):
            raise FileNotFoundError(
                f"Required file '{filepath}' not found. "
                "Please place a valid systems.json file in the bot's directory."
            )

        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        for entry in data:
            name = entry.get("Name") or entry.get("System")
            sys_id = str(entry.get("ID"))
            if not name or not sys_id:
                continue
                
            self.system_names.append(name)
            self.id_to_name[sys_id] = name
            self.name_to_id[name] = sys_id
            
            neighbors_val = entry.get("Neighbors", 0)
            if not neighbors_val or neighbors_val == 0:
                continue
            elif isinstance(neighbors_val, int):
                neighbors = [str(neighbors_val)]
            elif isinstance(neighbors_val, str):
                neighbors = [n.strip() for n in neighbors_val.split(':') if n.strip()]
            else:
                neighbors = []
                
            for neighbor_id in neighbors:
                self.graph[sys_id].append(neighbor_id)
                if sys_id not in self.graph[neighbor_id]:
                    self.graph[neighbor_id].append(sys_id)

    def _process_image_sync(self, img_bytes: bytes) -> Tuple[str, bytes]:
        """Processes image and returns (cleaned_ocr_text, processed_image_bytes)"""
        img = Image.open(io.BytesIO(img_bytes))
        cropped = img.crop(self.CROP_BOX)
        cropped = cropped.convert('L')
        cropped = cropped.point(lambda p: 255 if p > 229 else 0)
        
        # Save to an in-memory buffer instead of disk
        buffer = io.BytesIO()
        cropped.save(buffer, format="JPEG")
        buffer.seek(0)
        
        raw_text = pytesseract.image_to_string(cropped, config='--oem 3 --psm 7')
        cleaned_text = re.sub(r'[^a-zA-Z0-9\s]', '', raw_text).strip()
        
        return cleaned_text, buffer.getvalue()

    def _find_best_match(self, ocr_text: str) -> str:
        if not ocr_text:
            raise ValueError("OCR returned empty text.")
        matches = difflib.get_close_matches(ocr_text, self.system_names, n=1, cutoff=0.6)
        if not matches:
            raise ValueError(f"No matching system found for: '{ocr_text}'")
        return matches[0]

    def _get_systems_in_radius(self, start_id: str) -> list:
        visited = {start_id: 0}
        queue = collections.deque([start_id])
        while queue:
            current = queue.popleft()
            current_dist = visited[current]
            if current_dist == self.MAX_JUMPS:
                continue
            for neighbor in self.graph.get(current, []):
                if neighbor not in visited:
                    visited[neighbor] = current_dist + 1
                    queue.append(neighbor)
        return list(visited.keys())

    def _generate_reports(self, system_values: dict) -> Tuple[List[str], List[str]]:
        sorted_systems = sorted(system_values.items(), key=lambda x: x[1], reverse=True)
        reports = []
        current_report = ""
        included_names = []
        
        for sys_id, total_value in sorted_systems:
            if total_value > 0:
                link = f'<loc s="{sys_id}" t="system" sj="1">'
                potential_add = link if not current_report else current_report + " " + link
                
                if len(potential_add) <= self.MAX_REPORT_LENGTH:
                    current_report = potential_add
                    included_names.append(self.id_to_name.get(sys_id, f"Unknown({sys_id})"))
                else:
                    if current_report:
                        reports.append(current_report)
                    if len(reports) >= self.MAX_REPORTS:
                        break
                    current_report = link
                    included_names.append(self.id_to_name.get(sys_id, f"Unknown({sys_id})"))
                    
        if current_report and len(reports) < self.MAX_REPORTS:
            reports.append(current_report)
            
        if not reports:
            return ["No killmail value found in the specified radius."], []
            
        return reports, included_names

    async def fetch_killmails_async(self, radius_system_ids: list) -> dict:
        date_format = '%m-%d-%Y'
        today = datetime.now(timezone.utc)
        end_date = today - timedelta(days=15)
        
        url = f'https://echoes.mobi/killboard/export/{end_date.strftime(date_format)}/{today.strftime(date_format)}/json'
        system_values = collections.defaultdict(int)
        
        async with self.session.get(url, proxy=PROXY_URL, timeout=15) as resp:
            resp.raise_for_status()
            killmails = await resp.json()
            
            for km in killmails:
                sys_name = km.get("system")
                if not sys_name:
                    continue
                sys_id = self.name_to_id.get(sys_name)
                if not sys_id or sys_id not in radius_system_ids:
                    continue
                system_values[sys_id] += float(km.get("isk", 0))
                
        return dict(system_values)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.channel.id != TARGET_CHANNEL_ID:
            return
            
        matched_name = None
        is_image_search = False
        processed_img_bytes = None
        
        try:
            if ' ' not in message.content and len(message.attachments) == 0:
                await message.channel.send(f'searching for {message.content}')
                matched_name = self._find_best_match(message.content)
            else:
                is_image_search = True
                if len(message.attachments) != 1:
                    return
                    
                attachment = message.attachments[0]
                if not attachment.content_type or not attachment.content_type.startswith('image/'):
                    return

                await message.add_reaction('⏳')
                
                async with self.session.get(attachment.url, proxy=PROXY_URL, timeout=30) as resp:
                    resp.raise_for_status()
                    img_bytes = await resp.read()

                # Run blocking image processing in a thread pool, returns text AND image bytes
                loop = asyncio.get_running_loop()
                ocr_text, processed_img_bytes = await loop.run_in_executor(None, self._process_image_sync, img_bytes)
                matched_name = self._find_best_match(ocr_text)
            
            start_id = self.name_to_id[matched_name]
            radius_ids = self._get_systems_in_radius(start_id)
            
            system_values = await self.fetch_killmails_async(radius_ids)
            reports, included_names = self._generate_reports(system_values)
            
            if is_image_search:
                await message.remove_reaction('⏳', self.bot.user)
            await message.add_reaction('✅')
            
            pre_msg = f"🔍 **Parsed System:** `{matched_name}`\n"
            if included_names:
                pre_msg += f"📍 **Systems in Report:** {', '.join(included_names)}\n\n"
            pre_msg += "⚠️ *The following messages, when pasted into EVE chat, will turn into clickable system links.*"
            
            # Attach the processed image to the pre-message if it was an image search
            if is_image_search and processed_img_bytes:
                file = discord.File(io.BytesIO(processed_img_bytes), filename="processed_crop.jpg")
                await message.channel.send(pre_msg, file=file)
            else:
                await message.channel.send(pre_msg)
            
            for report in reports:
                await message.channel.send(report)
                await asyncio.sleep(0.5)
                
        except Exception as e:
            if is_image_search:
                await message.remove_reaction('⏳', self.bot.user)
                await message.add_reaction('❌')
            
            error_details = str(e)
            if len(error_details) > 1900:
                error_details = error_details[:1900] + "..."
                
            await message.channel.send(f"⚠️ **Processing Failed:**\n```{error_details}```")


async def setup(bot: commands.Bot):
    await bot.add_cog(KillmailAnalyzerCog(bot))

