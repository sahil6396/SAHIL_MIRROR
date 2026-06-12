import json
import random 
from aiofiles import open as aiopen
from aiofiles.os import path as aiopath, makedirs
from aioshutil import move
from asyncio import create_subprocess_exec, sleep, gather, Event
from asyncio.subprocess import PIPE
from math import floor
from natsort import natsorted
from os import path as ospath, walk
from re import findall as re_findall
from time import time

from bot import bot_loop, config_dict, download_dict, download_dict_lock, LOGGER, VID_MODE, user_data, bot_cache
from bot.helper.ext_utils.bot_utils import sync_to_async, new_task
from bot.helper.ext_utils.fs_utils import get_path_size, clean_target, count_files_and_folders
from bot.helper.ext_utils.leech_utils import get_document_type, get_media_info
from bot.helper.mirror_utils.status_utils.ffmpeg_status import FFMpegStatus
from bot.helper.video_utils.extra_selector import ExtraSelect
from bot.helper.telegram_helper.message_utils import update_all_messages


class VidEcxecutor:
    def __init__(self, listener, path, gid):
        self.listener = listener
        self.path = path
        self.size = 0
        self.is_cancel = False
        self.data = None
        self.event = Event()
        self.__up_path = path
        self.__gid = gid
        self.__processed_bytes = 0
        self.__start_time = time()
        self.__files = []
        self.__percentage = '0%'
        self.__eta = 0

    @property
    def processed_bytes(self):
        return self.__processed_bytes

    @property
    def speed(self):
        return self.__processed_bytes / (time() - self.__start_time)

    @property
    def percentage(self):
        return self.__percentage

    @property
    def eta(self):
        return self.__eta

    async def __progress(self, outfile, progfile):
        if progfile:
            try:
                duration = (await get_media_info(self.path))[0]
            except Exception as e:
                LOGGER.warning(f"Failed to get duration for progress: {e}")
                duration = 0
        while True:
            if not progfile:
                await sleep(1)
                if await aiopath.exists(outfile):
                    self.__processed_bytes = await get_path_size(outfile)
            elif await aiopath.exists(progfile):
                async with aiopen(progfile, 'r+') as f:
                    text = await f.read()
                    time_used = re_findall(r'out_time_ms=(\d+)', text)
                    prog = re_findall(r'progress=(\w+)', text)
                    total_size = re_findall(r'total_size=(\d+)', text)
                    if len(total_size) > 1000:
                        await f.truncate(0)
                    if prog and prog[-1] == 'end':
                        break
                time_used = time_used[-1] if time_used else 1
                elapsed_time = int(time_used) / 1000000
                self.__processed_bytes = int(total_size[-1]) if total_size else 1
                if duration:
                    self.__percentage = f'{round(floor(elapsed_time * 100 / duration), 2)}%'
                else:
                    self.__percentage = "N/A"
            await sleep(2.5)

    @staticmethod
    async def __get_metavideo(media_file):
        try:
            ffmpeg_path = 'ffmpeg'
            if ospath.isabs(ffmpeg_path):
                ffprobe_path = ospath.join(ospath.dirname(ffmpeg_path), 'ffprobe')
            else:
                ffprobe_path = 'ffprobe'

            cmd = [ffprobe_path, '-hide_banner', '-loglevel', 'error', '-of', 'json', '-show_format', '-show_streams', media_file]
            
            process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                LOGGER.error(f"FFprobe Error for {media_file}: {stderr.decode().strip()}")
                return [], {}
            
            metadata = json.loads(stdout.decode())
            return metadata.get('streams', []), metadata.get('format', {})
        except Exception as e:
            LOGGER.error(f"Metadata Parse Error: {e}")
            return [], {}

    @new_task
    async def __start_handler(self, *args):
        selector = ExtraSelect(self)
        if len(args) > 0 and isinstance(args[0], list):
             selector.streams = args[0]
        elif len(args) > 0 and not args[0]:
             selector.streams = []
        await selector.get_buttons(*args)

    async def __send_status(self, status='wait'):
        async with download_dict_lock:
            download_dict[self.listener.uid] = FFMpegStatus(self.name, self.size, self.__gid, self, self.listener, status)
        await update_all_messages(force=True)

    async def __get_files(self):
        file_list = []
        if await aiopath.isfile(self.path):
            if (await get_document_type(self.path))[0]:
                file_list.append(self.path)
        else:
            for dirpath, _, files in await sync_to_async(walk, self.path):
                for file in natsorted(files):
                    file = ospath.join(dirpath, file)
                    if (await get_document_type(file))[0]:
                        file_list.append(file)
        return file_list

    async def __get_video(self):
        if await aiopath.isfile(self.path) and (await get_document_type(self.path))[0]:
            return self.path
        for dirpath, _, files in await sync_to_async(walk, self.path):
            for file in natsorted(files):
                file = ospath.join(dirpath, file)
                if (await get_document_type(file))[0]:
                    return file

    async def __final_path(self, outfile):
        scan_dir = self.__up_path if self.__is_dir else ospath.split(self.__up_path)[0]
        if (await count_files_and_folders(scan_dir))[1] <= 1 and outfile:
            self.__up_path = outfile
        LOGGER.info(f"Final output path set to: {self.__up_path}")
        return self.__up_path

    async def __get_file_name(self, path, info: str=None, multi: bool=False):
        base_dir, file_name = ospath.split(path)
        if not self.name or multi:
            if info:
                if await aiopath.isfile(path):
                    file_name = file_name.rsplit('.', 1)[0]
                file_name += f'_{info}.mkv'
            self.name = file_name
        if not self.name.endswith(('.mkv', '.mp4')):
            self.name += '.mkv'
        return self.name, base_dir if await aiopath.isfile(path) else path

    async def __run_cmd(self, cmd, outfile, progfile=None):
        await self.__send_status('prog' if progfile else 'direct')
        
        LOGGER.info(f"Running FFmpeg command: {' '.join(cmd)}")
        self.listener.suproc = await create_subprocess_exec(*cmd)
        
        task = bot_loop.create_task(self.__progress(outfile, progfile))
        code = await self.listener.suproc.wait()
        task.cancel()
        
        if (is_cancel := self.listener.suproc == 'cancelled') or code != 0:
            if is_cancel or code == -9:
                self.is_cancel = True
                LOGGER.info(f"Process Cancelled: {outfile}")
            else:
                LOGGER.error('Failed to %s: %s', VID_MODE.get(self.mode, "Process"), outfile)
                self.__files.clear()
            await clean_target(outfile)
        elif code == 0:
            if progfile:
                await clean_target(progfile)
            if not self.listener.seed:
                await gather(*[clean_target(file) for file in self.__files])
            self.__files.clear()
            LOGGER.info(f"Process Success: {outfile}")
            return True

    async def execute(self):
        self.__is_dir = await aiopath.isdir(self.path)
        try:
            mode_data = self.listener.vidMode
            self.mode = mode_data[0]
            self.name = mode_data[1]
            extra_data = mode_data[2] if len(mode_data) > 2 else {}
            LOGGER.info(f"VidExecutor started with Mode: {self.mode}")
        except Exception as e:
            LOGGER.error(f"Failed to parse VidMode data: {e}")
            self.mode = 'unknown'
            self.name = ''
            extra_data = {}

        if self.mode in config_dict.get('DISABLE_MULTI_VIDTOOLS', []):
            if path := await self.__get_video():
                self.path = path
            else:
                return self.__up_path

        try:
            if self.mode == 'vid_vid':
                return await self.__merge_vids()
            if self.mode == 'vid_aud':
                return await self.__merge_auds()
            if self.mode == 'vid_sub':
                return await self.__merge_subs()
            if self.mode == 'trim':
                return await self.__vid_trimmer(*extra_data.values())
            if self.mode == 'watermark':
                return await self.__vid_marker(**extra_data)
            if self.mode == 'compress':
                return await self.__vid_compress()
            if self.mode == 'rmstream':
                return await self.__rm_stream()
            if self.mode == 'extract':
                return await self.__vid_extract()
            if self.mode == 'sample_video':
                return await self.__vid_sample()
            if self.mode == 'fix_delay':
                # ✅ FIX: Ensure data is passed even if user flow was minimal
                return await self.__vid_delay(self.data if self.data else {})

            return await self.__vid_convert()
        except Exception as e:
            LOGGER.error(f"Execution Error in {self.mode}: {e}")
        return self.__up_path

    async def __vid_convert(self):
        file_list = await self.__get_files()
        multi = len(file_list) > 1
        ffmpeg = 'ffmpeg'
        if file_list:
            media_file = file_list[0]
            (_, base_dir), (streams, _), self.size = await gather(self.__get_file_name(media_file, 'Convert', len(file_list) > 1),
                                                                  self.__get_metavideo(media_file), get_path_size(media_file))
            self.__start_handler(streams)
            await gather(self.__send_status(), self.event.wait())
        else:
            return self.__up_path

        if self.is_cancel:
            return
        if not self.data:
            return self.__up_path
        outfile = None
        for file in file_list:
            self.path = file
            conver_dict = {'1080p': '1920', '720p': '1280', '540p': '960', '480p': '854', '360p': '640'}
            (_, base_dir), self.size = await gather(self.__get_file_name(self.path, f'Convert-{self.data}', multi), get_path_size(self.path))
            outfile, progress = ospath.join(base_dir, self.name), ospath.join(base_dir, 'progress.txt')
            self.__files.append(self.path)
            
            cmd = [ffmpeg, '-hide_banner', '-ignore_unknown', '-y', '-loglevel', 'error', '-progress', progress, '-i', self.path,
                   '-map', '0', '-c:a', 'copy', '-c:s', 'copy', '-vf', f'scale={conver_dict[self.data]}:-2', outfile]
            
            await self.__run_cmd(cmd, outfile, progress)
            if self.is_cancel:
                return

        return await self.__final_path(outfile)

    async def __rm_stream(self):
        file_list = await self.__get_files()
        multi = len(file_list) > 1
        ffmpeg = 'ffmpeg'
        
        if file_list:
            media_file = file_list[0]
            (_, base_dir), (streams, _), self.size = await gather(self.__get_file_name(media_file, 'Remove', multi),
                                                                  self.__get_metavideo(media_file), get_path_size(media_file))
            self.__start_handler(streams)
            await gather(self.__send_status(), self.event.wait())
        else:
            return self.__up_path

        if self.is_cancel:
            return
        
        if not self.data or (not self.data.get('sdata') and not self.data.get('key')):
             return self.__up_path

        outfile = None
        for file in file_list:
            self.path = file
            (_, base_dir), self.size = await gather(self.__get_file_name(self.path, 'Remove', multi), get_path_size(self.path))
            await self.__get_file_name(self.path, 'Remove', multi)
            key = self.data.get('key', '')
            outfile, progress = ospath.join(base_dir, self.name), ospath.join(base_dir, 'progress.txt')
            self.__files.append(self.path)
            
            cmd = [ffmpeg, '-hide_banner', '-y', '-ignore_unknown', '-loglevel', 'error', '-progress', progress, '-i', self.path]
            
            if key == 'audio':
                cmd.extend(('-map', '0', '-map', '-0:a'))
            elif key == 'subtitle':
                cmd.extend(('-map', '0', '-map', '-0:s'))
            else:
                for x in self.data['stream']:
                    if x not in self.data['sdata']:
                        cmd.extend(('-map', f'0:{x}'))
            cmd.extend(('-c', 'copy', outfile))
            
            await self.__run_cmd(cmd, outfile, progress)
            if self.is_cancel:
                return

        return await self.__final_path(outfile)

    async def __vid_trimmer(self, start_time, end_time):
        ffmpeg = 'ffmpeg'
        for file in (file_list := await self.__get_files()):
            self.path = file
            (_, base_dir), self.size = await gather(self.__get_file_name(self.path, 'Trim', len(file_list) > 1), get_path_size(self.path))
            outfile, progress = ospath.join(base_dir, self.name), ospath.join(base_dir, 'progress.txt')
            self.__files.append(self.path)
            
            cmd = [ffmpeg, '-hide_banner', '-ignore_unknown', '-loglevel', 'error', '-i', self.path, '-ss', start_time,
                   '-to', end_time, '-c:v', 'copy', '-c:a', 'copy', '-c:s', 'copy', outfile, '-y']
            
            await self.__run_cmd(cmd, outfile, progress)
            if self.is_cancel:
                return

        return await self.__final_path(outfile)

    async def __vid_compress(self):
        file_list = await self.__get_files()
        multi = len(file_list) > 1
        ffmpeg = 'ffmpeg'
        
        if file_list:
            media_file = file_list[0]
            (_, base_dir), (streams, _), self.size = await gather(self.__get_file_name(media_file, 'Compress', multi),
                                                                  self.__get_metavideo(media_file), get_path_size(media_file))
            self.__start_handler(streams)
            await gather(self.__send_status(), self.event.wait())
        else:
            return self.__up_path

        if self.is_cancel:
            return
        if not isinstance(self.data, int):
            return self.__up_path

        outfile = None
        for file in file_list:
            self.path = file
            (_, base_dir), self.size = await gather(self.__get_file_name(self.path, 'Compress', multi), get_path_size(self.path))
            outfile, progress = ospath.join(base_dir, self.name), ospath.join(base_dir, 'progress.txt')
            self.__files.append(self.path)
            
            cmd = [ffmpeg, '-hide_banner', '-ignore_unknown', '-y', '-loglevel', 'error', '-progress', progress, '-i', self.path, '-preset',
                   'faster', '-c:v', 'libx265', '-pix_fmt', 'yuv420p10le', '-crf', '24', '-map', '0:0', '-map', '0:s:?', '-c:s', 'copy']
            
            cmd.extend(('-b:a', '156k', '-map', f'0:{self.data}?', outfile) if self.data else [outfile])
            
            await self.__run_cmd(cmd, outfile, progress)
            if self.is_cancel:
                return

        return await self.__final_path(outfile)

    async def __vid_marker(self, wmsize, wmposition):
        ffmpeg = 'ffmpeg'
        for file in (file_list := await self.__get_files()):
            self.path = file
            self.__files.append(self.path)
            wmpath = ospath.join('watermark', f'{self.listener.user_id}.png')
            (_, base_dir), fsize, fwmsize = await gather(self.__get_file_name(self.path, 'Marker', len(file_list) > 1),
                                                         get_path_size(self.path), get_path_size(wmpath))
            self.size = fsize + fwmsize
            outfile = ospath.join(base_dir, self.name)
            
            cmd = [ffmpeg, '-hide_banner', '-ignore_unknown', '-loglevel', 'error', '-y', '-i', self.path, '-i', wmpath, '-filter_complex',
                   f"[1][0]scale2ref=w='iw*{wmsize}/100':h='ow/mdar'[wm][vid];[vid][wm]overlay={wmposition}", '-preset', 'faster', '-crf', '24']
            
            cmd.extend(('-c:s', 'copy', '-c:a', 'copy', outfile))
            
            await self.__run_cmd(cmd, outfile)
            if self.is_cancel:
                return

        return await self.__final_path(outfile)

    async def __merge_vids(self):
        list_files = []
        ffmpeg = 'ffmpeg'
        
        for dirpath, _, files in await sync_to_async(walk, self.path):
            for file in natsorted(files):
                media_file = ospath.join(dirpath, file)
                if (await get_document_type(media_file))[0]:
                    self.size += await get_path_size(media_file)
                    safe_path = media_file.replace("'", "'\\''")
                    list_files.append(f"file '{safe_path}'")
                    self.__files.append(media_file)

        outfile = None
        if len(list_files) > 1:
            await self.__get_file_name(self.path)
            input_file = ospath.join(self.path, 'input.txt')
            async with aiopen(input_file, 'w') as f:
                await f.write('\n'.join(list_files))

            outfile = ospath.join(self.path, self.name)
            cmd = [ffmpeg, '-ignore_unknown', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', input_file, '-map', '0', '-c', 'copy', outfile, '-y']
            
            await self.__run_cmd(cmd, outfile)
            await clean_target(input_file)
            if self.is_cancel:
                return
        else:
            LOGGER.info("Merge Video: Not enough video files found to merge. Returning original path.")
            return self.__up_path

        return await self.__final_path(outfile)

    async def __merge_auds(self):
        media_file = False
        ffmpeg = 'ffmpeg'
        for dirpath, _, files in await sync_to_async(walk, self.path):
            for file in natsorted(files):
                file = ospath.join(dirpath, file)
                is_video, is_audio, _ = await get_document_type(file)
                if is_video and media_file:
                    continue
                if is_video and not media_file:
                    media_file = file
                if is_audio:
                    self.size += await get_path_size(file)
                    self.__files.append(file)

        self.__files.insert(0, media_file)
        outfile = None
        if len(self.__files) > 1:
            (_, _), size = await gather(self.__get_file_name(self.path), get_path_size(media_file))
            self.size += size
            
            cmd = [ffmpeg, '-hide_banner', '-ignore_unknown', '-loglevel', 'error']
            for i in self.__files:
                cmd.extend(('-i', i))
            cmd.extend(('-map', '0:v:0?', '-map', '0:a:?'))
            for j in range(1, len(self.__files)):
                cmd.extend(('-map', f'{j}:a'))

            outfile = ospath.join(self.path, self.name)
            streams = (await self.__get_metavideo(media_file))[0]
            audio_track = len([1+i for i in range(len(streams)) if streams[i]['codec_type'] == 'audio'])
            cmd.extend((f'-disposition:s:a:{audio_track if audio_track == 0 else audio_track+1}', 'default', '-map', '0:s:?', '-c:v', 'copy', '-c:a', 'copy', '-c:s', 'copy', outfile, '-y'))
            
            await self.__run_cmd(cmd, outfile)
            if self.is_cancel:
                return

        return await self.__final_path(outfile)

    async def __merge_subs(self):
        media_file = False
        ffmpeg = 'ffmpeg'
        for dirpath, _, files in await sync_to_async(walk, self.path):
            for file in natsorted(files):
                file = ospath.join(dirpath, file)
                is_video, is_sub = (await get_document_type(file))[0], file.endswith(('.ass', '.srt', '.vtt'))
                if is_video and media_file:
                    continue
                if is_video and not media_file:
                    media_file = file
                if is_sub:
                    self.size += await get_path_size(file)
                    self.__files.append(file)

        self.__files.insert(0, media_file)
        outfile = None
        if len(self.__files) > 1:
            (_, _), (streams, _), size = await gather(self.__get_file_name(self.path),
                                                      self.__get_metavideo(media_file),
                                                      get_path_size(media_file))
            self.size += size
            
            cmd = [ffmpeg, '-hide_banner', '-ignore_unknown', '-loglevel', 'error']
            sub_track = 0
            for i, item in enumerate(streams):
                if item['codec_type'] == 'subtitle':
                    sub_track += 1
            for i in self.__files:
                cmd.extend(('-i', i))
            cmd.extend(('-map', '0:v:0', '-map', '0:a:?', '-map', '0:s:?'))
            for j in range(1, (len(self.__files))):
                cmd.extend(('-map', f'{j}:s'))
            outfile = ospath.join(self.path, self.name)
            cmd.extend(('-c:v', 'copy', '-c:a', 'copy', '-c:s', 'srt', outfile, '-y'))
            
            await self.__run_cmd(cmd, outfile)
            if self.is_cancel:
                return

        return await self.__final_path(outfile)

    async def __vid_extract(self):
        file_list = await self.__get_files()
        multi = len(file_list) > 1
        ffmpeg = 'ffmpeg'
        
        if file_list:
            media_file = file_list[0]
            (_, base_dir), (streams, _), self.size = await gather(self.__get_file_name(media_file, 'Extract', multi),
                                                                  self.__get_metavideo(media_file), get_path_size(media_file))
            self.__start_handler(streams)
            await gather(self.__send_status(), self.event.wait())
        else:
            return self.__up_path

        if self.is_cancel:
            return
        
        if not self.data or not self.data.get('key'):
             return self.__up_path

        outfile = None
        for file in file_list:
            self.path = file
            (_, base_dir), self.size = await gather(self.__get_file_name(self.path, 'Extract', multi), get_path_size(self.path))
            
            outfile = ospath.join(base_dir, self.name) 
            self.__files.append(self.path)
            
            key = self.data.get('key')
            
            cmd = [ffmpeg, '-hide_banner', '-ignore_unknown', '-loglevel', 'error', '-i', self.path]
            
            if isinstance(key, int):
                cmd.extend(('-map', f'0:{key}', '-c', 'copy'))
            else:
                 if key == 'video':
                     cmd.extend(('-map', '0:v', '-c', 'copy'))
                 elif key == 'audio':
                     cmd.extend(('-map', '0:a', '-c', 'copy'))
                 elif key == 'subtitle':
                     cmd.extend(('-map', '0:s', '-c', 'copy'))

            cmd.extend(('-y', outfile))
            
            await self.__run_cmd(cmd, outfile)
            if self.is_cancel:
                return

        return await self.__final_path(outfile)

    async def __vid_sample(self):
        ffmpeg = 'ffmpeg'
        file_list = await self.__get_files()
        
        if not file_list:
            return self.__up_path

        media_file = file_list[0]
        
        # 1. Get metadata to find duration
        (_, base_dir), (streams, meta_format), self.size = await gather(
            self.__get_file_name(media_file, 'Sample', len(file_list) > 1),
            self.__get_metavideo(media_file),
            get_path_size(media_file)
        )
        
        # 2. Get Total duration from metadata
        try:
            total_duration = float(meta_format.get('duration', 0))
        except:
            total_duration = 0
            
        # 3. Trigger the button handler
        self.__start_handler(streams)
        
        # 4. Wait for user input
        await gather(self.__send_status(), self.event.wait())

        if self.is_cancel:
            return
            
        # 5. Get user selected duration
        if not self.data: 
             return self.__up_path
             
        sample_duration = int(self.data)
        
        outfile = ospath.join(base_dir, self.name)
        self.__files.append(media_file)

        # 6. Calculate Random Start Time
        if total_duration > sample_duration:
            start_time = random.randint(0, int(total_duration - sample_duration))
        else:
            start_time = 0

        LOGGER.info(f"Creating {sample_duration}s sample starting at {start_time}s")

        cmd = [
            ffmpeg, '-hide_banner', '-ignore_unknown', '-y', 
            '-ss', str(start_time), 
            '-t', str(sample_duration), 
            '-i', media_file, 
            '-map', '0', 
            '-c', 'copy',
            '-avoid_negative_ts', 'make_zero', 
            outfile
        ]

        await self.__run_cmd(cmd, outfile)
        
        if self.is_cancel:
            return

        return await self.__final_path(outfile)

    async def __vid_delay(self, delay_dict):
        # 1. Get the downloaded file
        file_list = await self.__get_files()
        if not file_list:
            return self.__up_path
            
        media_file = file_list[0]
        multi = len(file_list) > 1
        
        # 2. Get Metadata (Streams) for the Menu
        (_, base_dir), (streams, _), self.size = await gather(
            self.__get_file_name(media_file, 'Sync', multi), 
            self.__get_metavideo(media_file),
            get_path_size(media_file)
        )
        
        # 3. Trigger the ExtraSelect Menu (User Interface) - Only if delay_dict is empty (initial call)
        if not self.data:
            self.__start_handler(streams)
            # 4. Wait for User to click "Done"
            await gather(self.__send_status(), self.event.wait())
            
            if self.is_cancel:
                return
                
            delay_dict = self.data

        if not isinstance(delay_dict, dict) or not delay_dict:
            LOGGER.warning("No audio delay set. Returning original path.")
            return self.__up_path

        # 5. Process the Delay (Sync)
        ffmpeg = 'ffmpeg'
        outfile = ospath.join(base_dir, self.name)
        self.__files.append(media_file)
        
        delay_groups = {}
        
        for stream in streams:
            idx = stream.get('index')
            delay_ms = delay_dict.get(idx, 0)
            delay_sec = delay_ms / 1000.0
            
            if delay_sec not in delay_groups:
                delay_groups[delay_sec] = []
            delay_groups[delay_sec].append(idx)
            
        cmd = [ffmpeg, '-hide_banner', '-ignore_unknown', '-y']
        
        delay_to_input_map = {}
        input_counter = 0
        
        sorted_delays = sorted(delay_groups.keys())
        
        for d_sec in sorted_delays:
            if d_sec != 0:
                cmd.extend(['-itsoffset', str(d_sec)])
            cmd.extend(['-i', media_file])
            delay_to_input_map[d_sec] = input_counter
            input_counter += 1
            
        for stream in streams:
            idx = stream.get('index')
            found_delay = 0.0
            for d, indices in delay_groups.items():
                if idx in indices:
                    found_delay = d
                    break
            
            input_idx = delay_to_input_map[found_delay]
            cmd.extend(['-map', f'{input_idx}:{idx}'])
            
        cmd.extend(['-c', 'copy'])
        cmd.append(outfile)

        LOGGER.info(f"Applying Sync Correction with {len(delay_groups)} offset groups.")
        
        await self.__run_cmd(cmd, outfile)
        
        if self.is_cancel:
            return

        return await self.__final_path(outfile)
