import re
from aiofiles import open as aiopen
from aiofiles.os import path as aiopath
from asyncio import create_subprocess_exec, sleep, gather
from natsort import natsorted
from os import path as ospath, walk
from time import time

from bot import bot_loop, download_dict, download_dict_lock, LOGGER, bot_cache, user_data
from bot.helper.ext_utils.bot_utils import sync_to_async
from bot.helper.ext_utils.fs_utils import get_path_size, clean_target
from bot.helper.mirror_utils.status_utils.merge_status import MergeStatus
from bot.helper.telegram_helper.message_utils import update_all_messages

def extract_episode_number(filename: str):
    """Extract episode number from filename like Ep01, Episode-12, e13 etc."""
    match = re.search(r'(?:ep|episode|e)[^\d]?(\d{1,3})', filename, re.IGNORECASE)
    return int(match.group(1)) if match else float('inf')

class Merge:
    def __init__(self, listener):
        self.__listener = listener
        self.__processed_bytes = 0
        self.__start_time = time()
        self.__total_groups = 0
        self.__total_input_size = 0

    @property
    def processed_bytes(self):
        return self.__processed_bytes

    @property
    def speed(self):
        elapsed = time() - self.__start_time
        return self.__processed_bytes / elapsed if elapsed > 0 else 0

    async def __progress(self, outfile):
        """Tracks output file size growth during ffmpeg merge."""
        while True:
            await sleep(1)
            if await aiopath.exists(outfile):
                self.__processed_bytes = await get_path_size(outfile)
                if self.__total_input_size:
                    percent = (self.__processed_bytes / self.__total_input_size) * 100
                else:
                    percent = 0
                LOGGER.info(f"Processed: {self.__processed_bytes} bytes ({percent:.2f}%)")

    async def merge_vids(self, path, gid):
        """Collects, sorts and merges all video files inside given folder path."""
        list_files = []

        for dirpath, _, files in await sync_to_async(walk, path):
            for file in natsorted(files, key=lambda f: f.lower()):
                video_file = ospath.join(dirpath, file)
                if video_file.endswith(('.mp4', '.mkv')):
                    list_files.append((video_file, await get_path_size(video_file)))
                else:
                    continue
        
        if len(list_files) <= 1:
            LOGGER.info(f"Only {len(list_files)} video found. Skipping merge logic.")
            return True

        # ----------------------------------------------------------------------
        # LEECH DETECTION & SORTING
        # ----------------------------------------------------------------------
        is_leech = getattr(self.__listener, "is_leech", False) or getattr(self.__listener, "isLeech", False)

        if is_leech:
            LOGGER.info("Merge Mode: LEECH (Grouping enabled at 3.9GB)")
            list_files.sort(key=lambda x: extract_episode_number(ospath.basename(x[0])))
            max_size = 3.9 * 1024 * 1024 * 1024
        else:
            LOGGER.info("Merge Mode: MIRROR (Grouping disabled / Infinite Size)")
            list_files = natsorted(list_files, key=lambda x: x[0].lower())
            max_size = float('inf')
            
        self.__total_input_size = sum(f[1] for f in list_files)

        group_count = 0
        current_group, current_size, episode_numbers = [], 0, []

        for video_file, file_size in list_files:
            ep_num = extract_episode_number(ospath.basename(video_file))

            # Single huge file
            if file_size > max_size:
                if current_group:
                    await self._merge_group(current_group, path, group_count, gid, episode_numbers)
                    self.__total_groups += 1
                    group_count += 1
                    current_group, current_size, episode_numbers = [], 0, []
                await self._merge_group([video_file], path, group_count, gid, [ep_num])
                self.__total_groups += 1
                group_count += 1
                continue

            # If adding this file exceeds limit, start a new group
            if current_size + file_size > max_size and current_group:
                await self._merge_group(current_group, path, group_count, gid, episode_numbers)
                self.__total_groups += 1
                group_count += 1
                current_group, current_size, episode_numbers = [], 0, []

            current_group.append(video_file)
            current_size += file_size
            episode_numbers.append(ep_num)

        # Merge last group
        if current_group:
            await self._merge_group(current_group, path, group_count, gid, episode_numbers)
            self.__total_groups += 1

        return True

    async def _merge_group(self, group_files, path, group_count, gid, episode_numbers):
        """Merges a group of files into one mkv using ffmpeg concat."""
        group_name = ospath.basename(path)
        input_file = ospath.join(path, f"input.txt")

        # Write concat file
        concat_lines = [f"file '{f}'" for f in group_files]
        async with aiopen(input_file, 'w') as f:
            await f.write('\n'.join(concat_lines))

        # --- 1. Episode String Construction ---
        valid_eps = sorted([e for e in episode_numbers if isinstance(e, int)])
        ep_str = ""
        if valid_eps:
            if len(valid_eps) > 1:
                ep_str = f"EP({valid_eps[0]:02d}-{valid_eps[-1]:02d})"
            else:
                ep_str = f"EP({valid_eps[0]:02d})"

        # --- 2. Define Combined Tag ---
        combined_tag = " - COMBINED -" if len(valid_eps) > 1 else " -"

        # --- 3. Clean Filename (FIXED REGEX) ---
        # \b ensures we match 'E01' but NOT 'PolicE'
        cleaned_name = re.sub(
            r"(?i)\b(?:e|ep|episode)[\s.]*\(?\d{1,3}(?:[-_–—]\d{1,3})?\)?(?!\d)",
            "", group_name
        )
        
        # Remove old size info
        cleaned_name = re.sub(r"-?\s?\d+(\.\d+)?\s?(GB|MB|KB|Gb|Mb)(?!ps)", "", cleaned_name, flags=re.IGNORECASE)
        
        # Clean extra spaces
        cleaned_name = re.sub(r"\s{2,}", " ", cleaned_name).strip(" -_")

        # --- 4. Reconstruct Name Structure ---
        # Pattern: Title S04 Rest
        match = re.search(r"(?i)^(.*?)(\bS\d{1,2}\b)(.*)$", cleaned_name)
        
        if match:
            title_part = match.group(1).strip(" -")
            season_part = match.group(2).upper()
            rest_part = match.group(3).strip(" -")
            # Format: Title S01 EP(..) COMBINED Rest
            final_name = f"{title_part} {season_part} {ep_str}{combined_tag} {rest_part}"
        else:
            final_name = f"{cleaned_name} {ep_str}{combined_tag}"

        # --- 5. Size Injection Logic ---
        total_size = sum([await get_path_size(f) for f in group_files])
        if total_size >= 1024 ** 3:
            size_str = f"{total_size / (1024 ** 3):.1f}GB" # GB Uppercase
        elif total_size >= 1024 ** 2:
            size_str = f"{total_size / (1024 ** 2):.0f}MB"
        else:
            size_str = f"{total_size / 1024:.0f}KB"

        # ✅ NEW LOGIC: Place size correctly based on ESub existence
        # This handles both [Bracketed] and Unbracketed files correctly
        
        # Check if ESub exists in the name
        if re.search(r"(?i)\bESub\b", final_name):
            # Regex replacement: Find 'ESub', put '{size} ESub' in its place
            # This works even if ESub is inside brackets
            final_name = re.sub(r"(?i)(\bESub\b)", f"{size_str} \\1", final_name)
        
        # If no ESub, check if file ends in ']' (meaning it has outer brackets)
        elif final_name.strip().endswith("]"):
            # Insert size before the last bracket: "... AAC]" -> "... AAC 2.5GB]"
            final_name = final_name.strip()[:-1] + f" {size_str}]"
        
        # Fallback: Just append size
        else:
            final_name = f"{final_name} {size_str}"

        # Final cleanup of double spaces
        final_name = re.sub(r"\s{2,}", " ", final_name)

        # --- 6. Output & Processing ---
        outfile = ospath.join(path, f"{final_name}.mkv")

        LOGGER.info(f"📦 Merging {len(group_files)} files → {ospath.basename(outfile)}")

        async with download_dict_lock:
            download_dict[self.__listener.uid] = MergeStatus(group_name, total_size, gid, self, self.__listener)
        await update_all_messages()

        cmd = [
            'ffmpeg', '-ignore_unknown', '-loglevel', 'error',
            '-f', 'concat', '-safe', '0', '-i', input_file,
            '-map', '0', '-c', 'copy', outfile
        ]
        self.__listener.suproc = await create_subprocess_exec(*cmd)
        task = bot_loop.create_task(self.__progress(outfile))
        code = await self.__listener.suproc.wait()
        task.cancel()

        if code == 0:
            await clean_target(input_file)
            
            user_id = self.__listener.message.from_user.id if hasattr(self.__listener, "message") else None
            keep_sources = False
            if user_id and user_id in user_data:
                keep_sources = user_data[user_id].get("keepsource", False)

            if not self.__listener.seed and not keep_sources:
                await gather(*[clean_target(f) for f in group_files])
            
            LOGGER.info(f"✅ Merge completed: {outfile}")
            
        elif code == -9:
            LOGGER.warning(f"⛔ Merge cancelled: {outfile}")
        else:
            LOGGER.error(f"❌ Merge failed: {outfile}")
