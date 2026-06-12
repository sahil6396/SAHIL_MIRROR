import os
import re
import aiofiles
import asyncio
import subprocess
import logging
import json
import aiohttp
import shutil
import mimetypes
import tempfile
import imghdr
from os import walk, path as ospath
from aioshutil import move
from asyncio import create_subprocess_exec
from asyncio.subprocess import PIPE
from bot import bot_cache, LOGGER, config_dict, user_data
from bot.helper.ext_utils.fs_utils import clean_target
from bot.helper.ext_utils.leech_utils import format_filename
from typing import List, Tuple
from langcodes import Language
from fractions import Fraction


async def download_file(url: str, dest_path: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    with open(dest_path, 'wb') as f:
                        f.write(await resp.read())
                    return True
                else:
                    return False
    except Exception as e:
        return False

# =============================
# STREAM INFO FUNCTIONS
# =============================

async def get_video_codec(file_path):
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=codec_name',
        '-of', 'default=noprint_wrappers=1:nokey=1', file_path
    ]
    try:
        process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            return None
        return stdout.decode().strip()
    except Exception:
        return None

async def get_audio_info(input_file: str):
    # Ask for Duration & Bytes to calculate missing bitrates if standard header is missing
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'a',
        '-show_entries', 'stream=codec_name,bit_rate,channels,codec_type,duration:stream_tags=language,LANGUAGE,lang,title,BPS,BPS-eng,NUMBER_OF_BYTES,NUMBER_OF_BYTES-eng,DURATION,DURATION-eng',
        '-of', 'json', input_file
    ]
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode('utf-8')
        audio_info = json.loads(output)

        audio_streams = []
        for stream in audio_info.get('streams', []):
            if stream.get('codec_type') == 'audio':
                codec = stream.get('codec_name')
                tags = stream.get('tags', {})
                
                # --- BITRATE CALCULATION LOGIC ---
                bitrate = stream.get('bit_rate')
                
                # 1. Check Tags if header is empty (Common for MKV)
                if not bitrate or bitrate == 'N/A':
                    bitrate = tags.get('BPS') or tags.get('BPS-eng')
                
                # 2. Calculate from Bytes/Duration (Math Fallback)
                if not bitrate or bitrate == 'N/A':
                    try:
                        num_bytes = tags.get('NUMBER_OF_BYTES') or tags.get('NUMBER_OF_BYTES-eng')
                        
                        # Get Duration
                        duration = stream.get('duration')
                        if not duration or duration == 'N/A':
                            dur_tag = tags.get('DURATION') or tags.get('DURATION-eng')
                            if dur_tag and ':' in dur_tag:
                                h, m, s = dur_tag.split(':')
                                duration = float(h)*3600 + float(m)*60 + float(s)
                            elif dur_tag:
                                duration = float(dur_tag)

                        if num_bytes and duration:
                            # Formula: (Bytes * 8) / Duration = Bits per second
                            bitrate = (float(num_bytes) * 8) / float(duration)
                    except Exception:
                        pass

                # Final Integer Formatting (Kbps)
                try:
                    if bitrate:
                        bitrate = int(float(bitrate)) // 1000
                    else:
                        bitrate = None
                except:
                    bitrate = None
                
                # --- LANGUAGE LOGIC ---
                channels = stream.get('channels')
                language = tags.get('language') or tags.get('LANGUAGE') or tags.get('lang') or 'und'
                
                audio_streams.append((codec, bitrate, channels, language))
        return audio_streams
    except Exception as e:
        LOGGER.error(f"Error getting audio info: {e}")
        return []

async def get_audio_stream_count(file_path):
    cmd = ['ffprobe', '-v', 'error', '-select_streams', 'a',
           '-show_entries', 'stream=index', '-of', 'csv=p=0', file_path]
    process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await process.communicate()
    return len(stdout.decode().strip().split('\n'))

async def get_subtitle_stream_count(file_path: str) -> int:
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 's',
        '-show_entries', 'stream=index', '-of', 'csv=p=0', file_path
    ]
    process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await process.communicate()
    lines = stdout.decode().strip().split('\n')
    return len([line for line in lines if line.strip() != ''])

async def get_subtitle_info(media_file: str):
    command = [
        'ffprobe', '-v', 'error', '-select_streams', 's',
        '-show_entries', 'stream=index,codec_name:stream_tags=language,title',
        '-of', 'json', media_file
    ]
    process = await create_subprocess_exec(*command, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        return []
    try:
        data = json.loads(stdout.decode())
        subtitle_streams = []
        for stream in data.get("streams", []):
            tags = stream.get("tags", {})
            subtitle_streams.append({
                "index": stream.get("index"),
                "codec_name": stream.get("codec_name"), 
                "language": tags.get("language", "und"),
                "title": tags.get("title", "")
            })
        return subtitle_streams
    except json.JSONDecodeError:
        return []

# =============================
# EDIT METADATA (MAIN FUNCTION)
# =============================

async def edit_metadata(listener,
                        base_dir: str,
                        media_file: str,
                        outfile: str,
                        general_metadata: str = '',
                        video_metadata: str = '',
                        audio_metadata: str = '',
                        subtitle_metadata: str = '',
                        introsub: str = '',
                        attachment: str = None,
                        attachment_name: str = '',
                        force_metadata: bool = False):

    user_id = listener.message.from_user.id
    metadata_enabled = user_data.get(user_id, {}).get('metadata_mode', config_dict.get('METADATA_MODE', False))

    # Master Flag: If False, stop EVERYTHING immediately.
    is_meta_active = metadata_enabled or force_metadata

    if not is_meta_active:
        LOGGER.info(f"Metadata modification disabled for user {user_id}. Skipping processing.")
        return 

    temp_dir = None
    try:
        if not outfile.endswith(('.mkv', '.mp4', '.webm')):
            outfile += '.mkv'

        # Clean file name
        file_name, _ = await format_filename(os.path.basename(media_file), user_id, dirpath=base_dir, for_metadata=True)
        file_name = file_name.strip()
        
        audio_info = await get_audio_info(media_file)
        subtitle_info = await get_subtitle_info(media_file) or []

        # --- INTRO SUBTITLE LOGIC ---
        modified_subs_map = {} 
        
        if introsub:
            LOGGER.info(f"⚡ Processing Intro Subtitle...")
            temp_dir = tempfile.mkdtemp()
            
            intro_font = user_data.get(user_id, {}).get('intro_font', 'Arial')
            intro_colour = user_data.get(user_id, {}).get('intro_colour', '#FFFFFF')
            styled_intro = f'<font color="{intro_colour}" face="{intro_font}">{introsub.strip()}</font>'

            if subtitle_info:
                extract_cmd = ['ffmpeg', "-hide_banner", "-y", "-i", media_file]
                extraction_tasks = []

                for idx, sub in enumerate(subtitle_info):
                    codec = sub.get('codec_name', 'unknown').lower()
                    if codec in ['subrip', 'srt', 'ass', 'ssa', 'mov_text', 'webvtt', 'text', 'ply']:
                        extracted_path = os.path.join(temp_dir, f"sub_{idx}.srt")
                        extract_cmd.extend(["-map", f"0:s:{idx}", "-c:s", "subrip", extracted_path])
                        extraction_tasks.append((idx, extracted_path))
                    else:
                        modified_subs_map[idx] = None

                if extraction_tasks:
                    process = await create_subprocess_exec(*extract_cmd, stdout=PIPE, stderr=PIPE)
                    await process.communicate()
                    
                    for idx, path in extraction_tasks:
                        if os.path.exists(path) and os.path.getsize(path) > 0:
                            try:
                                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                                    content = f.read()
                                match = re.findall(r'^(\d+)\s*$', content, re.MULTILINE)
                                next_index = int(match[-1]) + 1 if match else 1
                                intro_block = f"\n{next_index}\n00:00:05,000 --> 00:00:30,000\n{styled_intro}\n"
                                with open(path, "w", encoding="utf-8") as f:
                                    f.write(content + intro_block)
                                modified_subs_map[idx] = path
                            except Exception:
                                modified_subs_map[idx] = None
                        else:
                            modified_subs_map[idx] = None
            else:
                new_sub_path = os.path.join(temp_dir, "intro_only.srt")
                intro_block = f"1\n00:00:05,000 --> 00:00:30,000\n{styled_intro}\n"
                with open(new_sub_path, "w", encoding="utf-8") as f:
                    f.write(intro_block)
                modified_subs_map['new'] = new_sub_path

        # --- Construct Final FFmpeg Command ---
        cmd = ['ffmpeg', '-hide_banner', '-ignore_unknown', '-i', media_file]

        ext_sub_input_indices = {}
        current_input_idx = 1 
        sorted_keys = sorted([k for k in modified_subs_map.keys() if isinstance(k, int)])
        
        for idx in sorted_keys:
            path = modified_subs_map[idx]
            if path:
                cmd.extend(['-i', path])
                ext_sub_input_indices[idx] = current_input_idx
                current_input_idx += 1
        
        if 'new' in modified_subs_map:
            cmd.extend(['-i', modified_subs_map['new']])
            ext_sub_input_indices['new'] = current_input_idx
            current_input_idx += 1

        # Clear Fields Loop
        clear_fields = [
            'copyright', 'description', 'license', 'LICENSE', 'author', 'summary',
            'credit', 'artist', 'album', 'genre', 'title', 'date', 'creation_time', 'publisher',
            'note', 'SUMMARY', 'AUTHOR', 'WEBSITE', 'CREDIT', 'ENCODER', 'FILENAME',
            'MIMETYPE', 'PURL', 'ALBUM', 'TELEGRAM_FILE_UPLOADER', 'SYNOPSIS', 'GROUP',
            'NOTE', 'comments', 'comment', 'COMMENT', 'Encoded by', 'ENCODED BY',
            'CREDITS', 'credits', 'DEVELOPER', 'developer', 'encoded_by', 'group', 'TITLE'
        ]
        
        for field in clear_fields:
            cmd.extend(['-metadata', f'{field}='])
            cmd.extend(['-metadata:s:v:0', f'{field}='])
            for i in range(len(audio_info)):
                cmd.extend([f'-metadata:s:a:{i}', f'{field}='])
            total_subs = 1 if 'new' in modified_subs_map else len(subtitle_info)
            for i in range(total_subs):
                cmd.extend([f'-metadata:s:s:{i}', f'{field}='])

        # General Title Logic
        if general_metadata:
            formatted_meta = general_metadata.format(file_name=file_name)
            for meta_pair in formatted_meta.split("|"):
                if "=" in meta_pair:
                    key, value = meta_pair.strip().split("=", 1)
                    if key.lower() == "title":
                        cmd.extend(["-metadata", f"title={value}"])
                    else:
                        cmd.extend(["-metadata", f"{key}={value}"])
        else:
            cmd.extend(["-metadata", f"title={file_name}"])

        # Video Metadata Logic
        if video_metadata:
            final_video_meta = video_metadata
            if "{video_codec}" in video_metadata:
                codec = await get_video_codec(media_file)
                if codec:
                    codec_map = {'h264': 'x264 - AVC', 'hevc': 'x265 - HEVC', 'vp9': 'VP9', 'av1': 'AV1', 'mpeg4': 'MPEG-4', 'mpeg2video': 'MPEG-2'}
                    mapped_codec = codec_map.get(codec.lower(), codec.upper())
                    final_video_meta = video_metadata.replace("{video_codec}", f"[{mapped_codec}]")
                else:
                    final_video_meta = video_metadata.replace("{video_codec}", "")
            cmd.extend(['-metadata:s:v:0', f'title={final_video_meta}'])

        def get_codec_name(codec):
            codec_map = {'eac3': 'DDP', 'aac': 'AAC', 'ac3': 'DDP', 'mp3': 'MP3', 'opus': 'OPUS', 'truehd':'TRUEHD', 'dts':'DTS'}
            return codec_map.get(codec.lower(), codec.upper())

        # Audio Metadata Logic
        for i, (codec, bitrate, channels, language) in enumerate(audio_info):
            final_audio_title = audio_metadata if audio_metadata else ""
            if final_audio_title:
                regional_name = 'Unknown'
                if language and language.lower() != 'und':
                    try:
                        clean_lang = language.lower().strip()
                        lang_obj = Language.get(clean_lang)
                        regional_name = lang_obj.autonym() or lang_obj.display_name()
                    except:
                        regional_name = language.capitalize()

                final_audio_title = final_audio_title.replace("{language}", str(regional_name))

                if "{codec_info}" in final_audio_title:
                    codec_name = get_codec_name(codec)
                    channel_info = "5.1" if channels == 6 else "2.0" if channels == 2 else "7.1" if channels == 8 else f"{channels}ch"
                    codec_details = f'[{codec_name} {channel_info}' + (f' - {bitrate}Kbps' if bitrate else '') + ']'
                    final_audio_title = final_audio_title.replace("{codec_info}", codec_details)
            else:
                codec_name = get_codec_name(codec)
                channel_info = "5.1" if channels == 6 else "2.0" if channels == 2 else f"{channels}ch"
                metadata_str = f'[{codec_name} {channel_info}' + (f' - {bitrate}Kbps' if bitrate else '') + ']'
                fallback_prefix = general_metadata.split('|')[0].split('=')[1] if general_metadata and '=' in general_metadata else ''
                final_audio_title = f"{fallback_prefix} - {metadata_str}".strip(' -')

            cmd.extend([f'-metadata:s:a:{i}', f'title={final_audio_title}'])

        # Subtitle Metadata
        if subtitle_metadata:
             for i in range(1 if 'new' in modified_subs_map else len(subtitle_info)):
                meta_lang = 'eng' if 'new' in modified_subs_map else subtitle_info[i].get('language', 'und')
                try:
                    formatted_lang = Language.get(meta_lang).display_name()
                except:
                    formatted_lang = meta_lang.capitalize()
                
                final_sub_title = subtitle_metadata.replace("{sub_lang}", f"[{formatted_lang}]") if "{sub_lang}" in subtitle_metadata else subtitle_metadata
                cmd.extend([f'-metadata:s:s:{i}', f'title={final_sub_title}'])

        cmd.extend(['-map', '0:v:0?', '-map', '0:a:?'])

        subtitle_codec_text = 'mov_text' if outfile.endswith(".mp4") else 'subrip'

        if 'new' in modified_subs_map:
            input_idx = ext_sub_input_indices['new']
            cmd.extend(['-map', f'{input_idx}:s', '-c:s', subtitle_codec_text, '-disposition:s:0', 'default', '-metadata:s:s:0', 'language=eng'])
        elif subtitle_info:
            for i in range(len(subtitle_info)):
                current_stream_lang = subtitle_info[i].get('language', 'und')
                if i in modified_subs_map and modified_subs_map[i] is not None:
                    input_idx = ext_sub_input_indices[i]
                    cmd.extend(['-map', f'{input_idx}:s', '-c:s', subtitle_codec_text, f'-metadata:s:s:{i}', f'language={current_stream_lang}'])
                else:
                    cmd.extend(['-map', f'0:s:{i}', '-c:s', 'copy', f'-metadata:s:s:{i}', f'language={current_stream_lang}'])
        else:
            cmd.extend(['-map', '0:s?', '-c:s', 'copy'])

        if attachment:
            attachment_ext = attachment.split(".")[-1].lower()
            mime_type = "image/jpeg" if attachment_ext in ["jpg", "jpeg"] else "image/png" if attachment_ext == "png" else "application/octet-stream"
            final_attach_name = f"{attachment_name}.{attachment_ext}" if attachment_name else f"cover.{attachment_ext}"
            cmd.extend(['-attach', attachment, '-metadata:s:t:0', f'mimetype={mime_type}', '-metadata:s:t:0', f'filename={final_attach_name}'])

        cmd.extend(['-disposition:a', 'none', '-disposition:a:0', 'default', '-c:v', 'copy', '-c:a', 'copy', '-y', outfile])

        LOGGER.info(f"Executing command: {' '.join(cmd)}")
        listener.suproc = await create_subprocess_exec(*cmd, stderr=PIPE)
        code = await listener.suproc.wait()
        
        if code != 0:
            error_message = await listener.suproc.stderr.read()
            LOGGER.error(f'FFmpeg failed: {error_message.decode().strip()}')
            await clean_target(outfile)
            return

        await clean_target(media_file) 
        listener.seed = False
        
        if ospath.dirname(outfile) != base_dir:
            await move(outfile, base_dir)

    except Exception as e:
        LOGGER.error(f"Error: {str(e)}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)       

# =============================
# EDIT SUBTITLE
# =============================
            
async def add_subtitles(listener, base_dir: str, media_file: str, outfile: str, subtitle: str):
    """
    Adds an external subtitle to a video file and sets it as the default subtitle.
    """
    # Determine subtitle codec based on file extension
    file_extension = media_file.split('.')[-1].lower()
    if file_extension == 'mp4':
        subtitle_codec = 'mov_text'
    elif file_extension == 'mkv':
        subtitle_codec = 'subrip'
    else:
        LOGGER.error(f"Unsupported video format: {file_extension}. Only MP4 and MKV are supported.")
        return

    # Check for existing subtitle streams
    probe_cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 's', '-show_entries',
        'stream=index', '-of', 'csv=p=0', media_file
    ]
    try:
        probe_proc = await create_subprocess_exec(*probe_cmd, stdout=PIPE, stderr=PIPE)
        stdout, _ = await probe_proc.communicate()
        existing_subtitle_count = len(stdout.decode().strip().splitlines())
    except Exception as e:
        LOGGER.error(f"Error probing subtitle streams for {media_file}: {str(e)}")
        return

    # Construct FFmpeg command
    cmd = [
        'ffmpeg', '-hide_banner', '-i', media_file,
        '-i', subtitle, '-c:v', 'copy', '-c:a', 'copy', '-c:s', subtitle_codec,
        '-map', '0:v',  # Map video streams
        '-map', '0:a?',  # Map audio streams (optional)
        '-map', '1:s:0',  # Map external subtitle as the first subtitle
    ]

    # Map existing subtitles and preserve metadata
    for i in range(existing_subtitle_count):
        cmd.extend(['-map', f'0:s:{i}'])

    # Set the external subtitle as default and assign English language
    cmd.extend([
        '-disposition:s:0', 'default',  # Make external subtitle default
        '-metadata:s:s:0', 'language=eng',
    ])

    # Overwrite output file
    cmd.append(outfile)




# =============================
# SMART AUDIO ADD (FINAL)
# =============================

# =============================
# HELPER FUNCTIONS (For Smart Sync)
# =============================

async def get_fps(file_path):
    cmd = [
        'ffprobe', '-v', 'error', 
        '-analyzeduration', '5000000', '-probesize', '5000000', # <--- ADDED THESE FLAGS
        '-select_streams', 'v:0',
        '-show_entries', 'stream=r_frame_rate',
        '-of', 'default=noprint_wrappers=1:nokey=1', file_path
    ]
    try:
        process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        stdout, _ = await process.communicate()
        fps_str = stdout.decode().strip()
        if '/' in fps_str:
            num, den = fps_str.split('/')
            return float(num) / float(den)
        return float(fps_str)
    except Exception:
        return 0.0

async def get_duration_float(file_path):
    cmd = [
        'ffprobe', '-v', 'error', 
        '-analyzeduration', '5000000', '-probesize', '5000000', # <--- ADDED THESE FLAGS
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', file_path
    ]
    try:
        process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        stdout, _ = await process.communicate()
        return float(stdout.decode().strip())
    except Exception:
        return 0.0

def sec_to_time(seconds):
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"



# =============================
# MAIN FUNCTION (HYBRID)
# =============================

async def add_audiofile(listener, base_dir: str, media_file: str, outfile: str, audiofile: str, smart_sync: bool = False):
    
    file_extension = media_file.split('.')[-1].lower()
    if file_extension not in ('mp4', 'mkv'):
        LOGGER.error(f"Unsupported format: {file_extension}. Only MP4 and MKV are supported.")
        return

    # --- COMMON DATA EXTRACTION ---
    # 1. Accurately count existing audio streams (so we don't overwrite Dual/Multi audio)
    try:
        p_cmd = ['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', media_file]
        p_proc = await create_subprocess_exec(*p_cmd, stdout=PIPE, stderr=PIPE)
        stdout, _ = await p_proc.communicate()
        existing_audio_count = len(stdout.decode().strip().splitlines())
    except Exception:
        existing_audio_count = 1

    # 2. Extract Bitrate of the external audio
    bitrate = None
    try:
        b_cmd = ['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=bit_rate', '-of', 'default=noprint_wrappers=1:nokey=1', audiofile]
        b_proc = await create_subprocess_exec(*b_cmd, stdout=PIPE, stderr=PIPE)
        out, _ = await b_proc.communicate()
        if out.decode().strip().isdigit():
            bitrate = int(out.decode().strip())
    except:
        pass

    # --------------------------------------------------------------------------------
    # ❌ MODE 1: OLD WORKING CODE (Smart Sync OFF)
    # --------------------------------------------------------------------------------
    if not smart_sync:
        LOGGER.info(f"⚡ Smart Sync OFF: Running Original Mux Code for {os.path.basename(media_file)}")

        cmd = [
            'ffmpeg', '-hide_banner', '-ignore_unknown', '-i', media_file,
            '-i', audiofile, 
            '-map', '0:v:0', '-map', '0:a?', '-map', '0:s?', '-map', '1:a:0',
            '-c:v', 'copy', '-c:a', 'copy', '-c:s', 'copy' # SAFELY COPIES ALL STREAMS
        ]  

        if bitrate:
            cmd.extend([f'-metadata:s:a:{existing_audio_count}', f'BPS={bitrate}'])

        cmd.extend(['-y', outfile])
        LOGGER.info(f"Running command: {' '.join(cmd)}")

        try:
            listener.suproc = await create_subprocess_exec(*cmd, stderr=PIPE)
            code = await listener.suproc.wait()
            if code == 0:
                LOGGER.info(f"Audio track added successfully to {media_file}")
                await clean_target(media_file)
                listener.seed = False
                await move(outfile, base_dir)
            else:
                stderr_output = await listener.suproc.stderr.read()
                LOGGER.error(f"Failed to add audio to {media_file}. Error: {stderr_output.decode().strip()}")
                await clean_target(outfile)
        except Exception as e:
            LOGGER.error(f"Error adding audio to {media_file}: {str(e)}")
        
        return 

    # --------------------------------------------------------------------------------
    # ✅ MODE 2: SMART SYNC ON (Analysis + Report + Fix)
    # --------------------------------------------------------------------------------
    import time
    start_time = time.time()
    LOGGER.info(f"⚙️ Smart Sync ON: Analyzing {os.path.basename(media_file)}...")
    
    vid_fps = await get_fps(media_file) or 0.0
    aud_fps = await get_fps(audiofile) or 0.0
    vid_dur = await get_duration_float(media_file)
    aud_dur = await get_duration_float(audiofile)
    
    offset_val = 0.0
    is_fps_drift = False
    filter_complex = []
    actions_report = []

    if vid_fps and aud_fps and abs(vid_fps - aud_fps) > 0.01:
        tempo = vid_fps / aud_fps
        if 0.5 < tempo < 2.0:
            is_fps_drift = True
            filter_complex.append(f"atempo={tempo}")
            actions_report.append(f"Fix FPS Drift ({aud_fps:.3f} ➔ {vid_fps:.3f})")
            actions_report.append("Re-encode Audio (AAC)")

    diff_val = abs(vid_dur - aud_dur)
    if diff_val > 0.5:
        if (vid_dur - aud_dur) > 0:
            offset_val = diff_val
            actions_report.append(f"Add Delay : {int(offset_val * 1000)} ms")
        else:
             actions_report.append(f"Audio is longer by {diff_val:.2f}s (No Action)")

    if not is_fps_drift and offset_val == 0:
        actions_report.append("Sync is Perfect (Copy Mode)")
    elif not is_fps_drift and offset_val > 0:
        actions_report.append("Untouched Offset (Container Fix)")

    try:
        vid_name = os.path.basename(media_file)
        from bot.helper.ext_utils.bot_utils import get_readable_file_size
        vid_size = get_readable_file_size(os.path.getsize(media_file))
        action_txt = "\n".join([f"   {i+1}️⃣ {act}" for i, act in enumerate(actions_report)])
        
        report = f"""
🎞 <b>SMART SYNC REPORT</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎬 <b>{vid_name}</b> ({vid_size})
   └─ Stream   : {vid_fps:.3f}  [{sec_to_time(vid_dur)}]

🎧 <b>External Audio</b>
   └─ Stream   : {aud_fps:.3f}  [{sec_to_time(aud_dur)}]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ <b>ACTION REQUIRED</b>
{action_txt}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        if listener.message: await listener.message.reply_text(report)
        else: LOGGER.info(report)
    except: pass

    # --- BUILD SMART COMMAND ---
    cmd = ['ffmpeg', '-hide_banner', '-ignore_unknown', '-i', media_file]

    # Apply Offset if Untouched Mode
    if offset_val > 0 and not is_fps_drift:
        cmd.extend(['-itsoffset', str(offset_val)])
    
    cmd.extend(['-i', audiofile])

    # Map Streams (Dynamically handles Single, Dual, or Multi-Audio movies safely)
    cmd.extend(['-map', '0:v:0', '-map', '0:a?', '-map', '0:s?', '-map', '1:a:0'])

    # Globally Copy Everything (Prevents Vorbis bug and Video Lag)
    cmd.extend(['-c:v', 'copy', '-c:a', 'copy', '-c:s', 'copy'])

    if is_fps_drift:
        # Override only the exact new stream if speed fix is needed
        new_idx = existing_audio_count
        if offset_val > 0:
            delay_ms = int(offset_val * 1000)
            delays = "|".join([str(delay_ms)] * 6)
            filter_complex.insert(0, f"adelay={delays}")
            
        filter_complex.append("aresample=async=1")
        cmd.extend([
            f'-filter:a:{new_idx}', ",".join(filter_complex), 
            f'-c:a:{new_idx}', 'aac', f'-b:a:{new_idx}', '256k',
            f'-metadata:s:a:{new_idx}', 'title=Synced Audio (Speed Fixed)'
        ])
    else:
        # Untouched Copy Mode - Just apply bitrate metadata
        if bitrate:
            cmd.extend([f'-metadata:s:a:{existing_audio_count}', f'BPS={bitrate}'])

    cmd.extend(['-y', outfile])
    LOGGER.info(f"Running Smart Command: {' '.join(cmd)}")
    
    try:
        listener.suproc = await create_subprocess_exec(*cmd, stderr=PIPE)
        code = await listener.suproc.wait()
        if code == 0:
            LOGGER.info(f"Smart Sync Successful: {media_file}")
            await clean_target(media_file)
            listener.seed = False
            await move(outfile, base_dir)
        else:
             stderr_output = await listener.suproc.stderr.read()
             LOGGER.error(f"Smart Sync Failed: {stderr_output.decode().strip()}")
             await clean_target(outfile)
    except Exception as e:
        LOGGER.error(f"Smart Sync Error: {e}")
        



        

###############################

async def edit_audiolanguage(listener, base_dir: str, media_file: str, outfile: str, audiolanguage: str = ''):
    try:
        audio_stream_count = await get_audio_stream_count(media_file)
    except Exception as e:
        LOGGER.error(f"❌ Unable to determine audio stream count for {media_file}: {str(e)}")
        return media_file

    language_keys = audiolanguage.split(',')

    if len(language_keys) > audio_stream_count:
        LOGGER.error(f"❌ More languages provided than available audio streams ({audio_stream_count}).")
        return media_file

    cmd = ['ffmpeg', '-hide_banner', '-i', media_file, '-map', '0:v:0']

    for audio_key in range(audio_stream_count):
        cmd.extend(['-map', f'0:a:{audio_key}'])
        if audio_key < len(language_keys) and language_keys[audio_key]:
            cmd.extend([f'-metadata:s:a:{audio_key}', f'language={language_keys[audio_key]}'])

    cmd.extend([
        '-c:v', 'copy', '-c:a', 'copy', '-map', '0:s?', '-c:s', 'copy', '-y', outfile
    ])

    listener.suproc = await create_subprocess_exec(*cmd, stderr=PIPE)
    code = await listener.suproc.wait()

    if code == 0:
        LOGGER.info(f"✅ Successfully updated audio language metadata: {outfile}")
        await clean_target(media_file)
        listener.seed = False
        await move(outfile, base_dir)
    else:
        error_msg = await listener.suproc.stderr.read()
        LOGGER.error(f"❌ Failed to update audio languages for {media_file}: {error_msg.decode().strip()}")
        await clean_target(outfile)


async def edit_audiochange(listener, base_dir: str, media_file: str, outfile: str, audiochange: str = ''): 
    try:
        audio_stream_count = await get_audio_stream_count(media_file)
    except Exception as e:
        LOGGER.error(f"❌ Unable to determine audio stream count for {media_file}: {str(e)}")
        return media_file

    audio_keys = [int(key) - 1 for key in audiochange.split(',') if key.isdigit()]

    if len(audio_keys) > audio_stream_count or any(key < 0 or key >= audio_stream_count for key in audio_keys):
        LOGGER.error(f"❌ Invalid audio selection: {audiochange}. Ensure all indices are within the range 1-{audio_stream_count}.")
        return media_file

    cmd = [
        'ffmpeg', '-hide_banner', '-i', media_file,
        '-map', '0:v:0',
    ]

    for audio_key in audio_keys:
        cmd.extend(['-map', f'0:a:{audio_key}'])
        
    cmd.extend([
        '-c:v', 'copy', '-c:a', 'copy', '-map', '0:s?', '-c:s', 'copy', '-y', outfile
    ])

    listener.suproc = await create_subprocess_exec(*cmd, stderr=PIPE)
    code = await listener.suproc.wait()

    if code == 0:
        LOGGER.info(f"✅ Audio modification successful: {outfile}")
        await clean_target(media_file)
        listener.seed = False
        await move(outfile, base_dir)
    else:
        error_msg = await listener.suproc.stderr.read()
        LOGGER.error(f"❌ Audio modification failed for {media_file}: {error_msg.decode().strip()}")
        await clean_target(outfile)


async def edit_audioremove(listener, base_dir: str, media_file: str, outfile: str, audioremove: str = ''):
    audio_keys = [int(key) - 1 for key in audioremove.split(',') if key.isdigit()]

    cmd = [
        'ffmpeg', '-hide_banner', '-i', media_file,
        '-map', '0:v:0', '-map', '0:a', '-map', '0:s?',
    ]

    for audio_key in audio_keys:
        cmd.extend(['-map', f'-0:a:{audio_key}'])

    cmd.extend([
        '-c:v', 'copy', '-c:a', 'copy', '-c:s', 'copy', '-y', outfile
    ])

    listener.suproc = await create_subprocess_exec(*cmd, stderr=PIPE)
    code = await listener.suproc.wait()

    if code == 0:
        LOGGER.info(f"✅ Successfully removed selected audio tracks: {outfile}")
        await clean_target(media_file)
        listener.seed = False
        await move(outfile, base_dir)
    else:
        error_msg = await listener.suproc.stderr.read()
        LOGGER.error(f"❌ Failed to remove audio from {media_file}: {error_msg.decode().strip()}")
        await clean_target(outfile)



async def remove_subtitles(listener, base_dir: str, media_file: str, outfile: str, remsub: str):
    try:
        # Convert "1,3" → [0,2]
        keep_indices = [int(i.strip()) - 1 for i in remsub.split(',') if i.strip().isdigit()]
    except ValueError:
        LOGGER.error("❌ Invalid subtitle index list. Use format like '1,3,4'.")
        return media_file

    try:
        subtitle_count = await get_subtitle_stream_count(media_file)
    except Exception as e:
        LOGGER.error(f"❌ Failed to count subtitle streams: {str(e)}")
        return media_file

    cmd = [
        'ffmpeg', '-hide_banner', '-i', media_file,
        '-map', '0:v', '-map', '0:a'
    ]

    # Add only the subtitle streams to keep
    for i in keep_indices:
        if 0 <= i < subtitle_count:
            cmd.extend(['-map', f'0:s:{i}'])

    # Codec copy for all
    cmd.extend(['-c:v', 'copy', '-c:a', 'copy', '-c:s', 'copy'])

    # Set the first kept subtitle (if any) as default
    if keep_indices:
        cmd.extend(['-disposition:s:0', 'default'])

    cmd.extend(['-y', outfile])

    listener.suproc = await create_subprocess_exec(*cmd, stderr=PIPE)
    code = await listener.suproc.wait()

    if code == 0:
        LOGGER.info(f"✅ Kept only selected subtitle streams in {media_file}")
        await clean_target(media_file)
        listener.seed = False
        await move(outfile, base_dir)
    else:
        error_msg = await listener.suproc.stderr.read()
        LOGGER.error(f"❌ FFmpeg subtitle keep failed: {error_msg.decode().strip()}")
        await clean_target(outfile)

async def change_audiobitrate(listener, base_dir: str, media_file: str, outfile: str, audiobitrate: str):
    try:
        audio_stream_count = await get_audio_stream_count(media_file)
    except Exception as e:
        LOGGER.error(f"❌ Failed to retrieve audio stream info for {media_file}: {str(e)}")
        return media_file

    bitrate_map = {}  # stream_index (0-based) → bitrate

    # Case 1: Global bitrate (e.g., "64k") → re-encode ALL audio streams
    if ':' not in audiobitrate:
        for i in range(audio_stream_count):
            bitrate_map[i] = audiobitrate.strip()

    # Case 2: Stream-specific bitrates (e.g., "1:128k,3:64k")
    else:
        for item in audiobitrate.split(','):
            try:
                stream_id, bitrate = item.split(':')
                stream_id = int(stream_id) - 1
                if stream_id < 0 or stream_id >= audio_stream_count:
                    raise ValueError(f"Invalid stream index: {stream_id + 1}")
                bitrate_map[stream_id] = bitrate.strip()
            except ValueError:
                LOGGER.error(f"❌ Invalid bitrate format: {item}. Use '64k' or '1:128k,3:64k'")
                return media_file

    clear_fields = [
        'BPS', 'Stream size', 'Bit rate', 'encoder', 'language', 'creation_time',
        'copyright', 'author', 'album', 'genre', 'publisher', 'encoded_by'
    ]

    cmd = [
        'ffmpeg', '-hide_banner', '-i', media_file,
        '-map', '0:v', '-map', '0:s?',
        '-map_metadata', '-1'
    ]

    out_audio_idx = 0
    for in_audio_idx in range(audio_stream_count):
        cmd += ['-map', f'0:a:{in_audio_idx}']

        if in_audio_idx in bitrate_map:
            bitrate = bitrate_map[in_audio_idx]
            cmd += [f'-c:a:{out_audio_idx}', 'aac', f'-b:a:{out_audio_idx}', bitrate, f'-ac:{out_audio_idx}', '2']
            for field in clear_fields:
                cmd += [f'-metadata:s:a:{out_audio_idx}', f'{field}=']
        else:
            cmd += [f'-c:a:{out_audio_idx}', 'copy']

        out_audio_idx += 1

    cmd += ['-c:v', 'copy', '-c:s', 'copy', '-y', outfile]

    LOGGER.debug(f"FFmpeg Command: {' '.join(cmd)}")
    listener.suproc = await create_subprocess_exec(*cmd, stderr=PIPE)
    code = await listener.suproc.wait()

    if code == 0:
        LOGGER.info(f"✅ Successfully processed audio bitrate changes for {media_file}")
        await clean_target(media_file)
        listener.seed = False
        await move(outfile, base_dir)
        return outfile
    else:
        error_msg = await listener.suproc.stderr.read()
        LOGGER.error(f"❌ FFmpeg failed for {media_file}: {error_msg.decode().strip()}")
        await clean_target(outfile)
        return media_file
        

async def remove_subtitles(listener, base_dir: str, media_file: str, outfile: str, remsub: str):
    try:
        # Convert "1,3" → [0,2]
        keep_indices = [int(i.strip()) - 1 for i in remsub.split(',') if i.strip().isdigit()]
    except ValueError:
        LOGGER.error("❌ Invalid subtitle index list. Use format like '1,3,4'.")
        return media_file

    try:
        subtitle_count = await get_subtitle_stream_count(media_file)
    except Exception as e:
        LOGGER.error(f"❌ Failed to count subtitle streams: {str(e)}")
        return media_file

    cmd = [
        'ffmpeg', '-hide_banner', '-i', media_file,
        '-map', '0:v', '-map', '0:a'
    ]

    # Add only the subtitle streams to keep
    for i in keep_indices:
        if 0 <= i < subtitle_count:
            cmd.extend(['-map', f'0:s:{i}'])

    # Codec copy for all
    cmd.extend(['-c:v', 'copy', '-c:a', 'copy', '-c:s', 'copy'])

    # Set the first kept subtitle (if any) as default
    if keep_indices:
        cmd.extend(['-disposition:s:0', 'default'])

    cmd.extend(['-y', outfile])

    listener.suproc = await create_subprocess_exec(*cmd, stderr=PIPE)
    code = await listener.suproc.wait()

    if code == 0:
        LOGGER.info(f"✅ Kept only selected subtitle streams in {media_file}")
        await clean_target(media_file)
        listener.seed = False
        await move(outfile, base_dir)
    else:
        error_msg = await listener.suproc.stderr.read()
        LOGGER.error(f"❌ FFmpeg subtitle keep failed: {error_msg.decode().strip()}")
        await clean_target(outfile)

async def subtitle_replace_text_v2(listener, base_dir: str, media_file: str, outfile: str, replacement_input: list):
    try:
        # 🛠 Parse replacement rules from input format: "old -> new"
        replacements = {}
        for rule in replacement_input:
            if '->' in rule:
                old, new = rule.split('->', 1)
                replacements[old.strip()] = new.strip()

        if not replacements:
            LOGGER.error("❌ No valid replacements found.")
            return

        LOGGER.info(f"🧠 Parsed Replacement Rules:\n{json.dumps(replacements, indent=2)}")

        # 🎯 ffprobe to get subtitle streams
        probe_cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 's',
            '-show_entries', 'stream=index:stream_tags=language',
            '-of', 'json', media_file
        ]

        listener.suproc = await create_subprocess_exec(*probe_cmd, stdout=PIPE, stderr=PIPE)
        stdout, stderr = await listener.suproc.communicate()

        raw_output = stdout.decode().strip()
        if not raw_output:
            LOGGER.error(f"❌ ffprobe returned empty output.\nstderr: {stderr.decode().strip()}")
            return

        try:
            probe_data = json.loads(raw_output)
        except json.JSONDecodeError as e:
            LOGGER.error(f"❌ Failed to parse ffprobe output as JSON: {e}\nOutput: {raw_output}")
            return

        subtitle_streams = probe_data.get("streams", [])
        temp_dir = tempfile.mkdtemp()
        input_args = ['-i', media_file]
        map_args = ['-map', '0:v?', '-map', '0:a?']
        metadata_args = []
        index_offset = 0
        found_any = False

        if subtitle_streams:
            for i, stream in enumerate(subtitle_streams):
                lang = stream.get("tags", {}).get("language", "und")
                sub_path = os.path.join(temp_dir, f"sub_{i}.srt")

                extract_cmd = [
                    'ffmpeg', '-hide_banner', '-y',
                    '-i', media_file,
                    '-map', f"0:s:{i}",
                    '-c:s', 'srt',
                    sub_path
                ]
                proc = await create_subprocess_exec(*extract_cmd, stderr=PIPE)
                await proc.wait()

                if not os.path.exists(sub_path):
                    LOGGER.warning(f"⚠️ Subtitle extraction failed for stream {i}")
                    continue

                LOGGER.info(f"📝 Processing subtitle stream {i} (language: {lang})")

                # Replace matching lines
                with open(sub_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

                changed = 0
                new_lines = []
                for line in lines:
                    original_line = line
                    for old_text, new_text in replacements.items():
                        if old_text in line:
                            line = line.replace(old_text, new_text)
                    if line != original_line:
                        LOGGER.debug(f"🔁 Changed line: {original_line.strip()} → {line.strip()}")
                        changed += 1
                        found_any = True
                    new_lines.append(line)

                if changed == 0:
                    LOGGER.warning(f"⚠️ No subtitle lines changed in stream {i}")
                else:
                    LOGGER.info(f"✅ {changed} subtitle lines replaced in stream {i}")

                with open(sub_path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)

                input_args.extend(['-i', sub_path])
                map_args.extend(['-map', f"{i + 1}:s:0"])
                metadata_args.extend([
                    f"-metadata:s:s:{index_offset}", f"language={lang}",
                    f"-disposition:s:{index_offset}", "default"
                ])
                index_offset += 1
        else:
            LOGGER.warning("⚠️ No subtitle streams found in the input file.")
            return

        if not found_any:
            LOGGER.warning("❌ No matching subtitle lines were found for replacement.")
            return

        subtitle_codec = 'mov_text' if media_file.endswith('.mp4') else 'subrip'

        remux_cmd = ['ffmpeg', '-hide_banner', '-y'] + input_args + [
            '-c:v', 'copy', '-c:a', 'copy', '-c:s', subtitle_codec
        ] + map_args + metadata_args + [outfile]

        LOGGER.info(f"🚀 Remuxing subtitles with replaced text into: {outfile}")
        listener.suproc = await create_subprocess_exec(*remux_cmd, stderr=PIPE)
        code = await listener.suproc.wait()

        if code == 0:
            LOGGER.info("🎉 Subtitle replacement and remuxing completed successfully.")
            await clean_target(media_file)
            listener.seed = False
            await move(outfile, base_dir)
        else:
            stderr_output = await listener.suproc.stderr.read()
            LOGGER.error(f"❌ Remux failed: {stderr_output.decode().strip()}")
            await clean_target(outfile)

    except Exception as e:
        LOGGER.error(f"❌ Error in subtitle_replace_contains_text_v2: {str(e)}")


def parse_cut_segments(segment_input: str) -> List[Tuple[str, str]]:
    """
    Parse a user-given cut input string into list of (start, end) tuples.

    Example:
      "00:00:00 00:00:30, 00:01:00 00:01:20"
      → [("00:00:00", "00:00:30"), ("00:01:00", "00:01:20")]
    """
    segments = []
    if not segment_input:
        return segments

    for seg in segment_input.split(','):
        times = seg.strip().split()
        if len(times) == 2:
            start, end = times
            segments.append((start.strip(), end.strip()))

    return segments
        

async def cut_video_segments(listener, base_dir: str, media_file: str, outfile: str, segments: List[Tuple[str, str]]):
    """
    Cuts multiple segments from a video file using FFmpeg.
    If multiple segments are provided, they are concatenated into one output file.
    """
    import tempfile

    if not segments:
        LOGGER.error("❌ No segments provided for cutting.")
        return

    temp_dir = tempfile.mkdtemp()
    segment_files = []

    try:
        for i, (start, end) in enumerate(segments, start=1):
            segment_path = os.path.join(temp_dir, f"segment_{i}.mp4")
            cmd = [
                'ffmpeg', '-hide_banner',
                '-ss', start, '-to', end,
                '-i', media_file,
                '-c', 'copy',
                '-avoid_negative_ts', 'make_zero',
                '-y', segment_path
            ]
            LOGGER.info(f"✂️ Cutting segment {i}: {start} → {end}")
            listener.suproc = await create_subprocess_exec(*cmd, stderr=PIPE)
            code = await listener.suproc.wait()

            if code == 0:
                segment_files.append(f"file '{segment_path}'")
                LOGGER.info(f"✅ Segment {i} created: {segment_path}")
            else:
                stderr_output = await listener.suproc.stderr.read()
                LOGGER.error(f"❌ Failed to cut segment {i}: {stderr_output.decode().strip()}")

        if not segment_files:
            LOGGER.error("❌ No valid segments were created.")
            return

        if len(segment_files) == 1:
            only_segment = segment_files[0].replace("file '", "").replace("'", "")
            os.replace(only_segment, outfile)
            LOGGER.info(f"✅ Single cut output saved: {outfile}")
        else:
            concat_file = os.path.join(temp_dir, "concat_list.txt")
            async with aiofiles.open(concat_file, 'w') as f:
                await f.write('\n'.join(segment_files))

            merge_cmd = [
                'ffmpeg', '-hide_banner',
                '-f', 'concat', '-safe', '0',
                '-i', concat_file,
                '-c', 'copy',
                '-y', outfile
            ]
            LOGGER.info(f"🔗 Merging {len(segment_files)} segments → {outfile}")
            listener.suproc = await create_subprocess_exec(*merge_cmd, stderr=PIPE)
            merge_code = await listener.suproc.wait()

            if merge_code == 0:
                LOGGER.info(f"✅ Final cut video created: {outfile}")
            else:
                stderr_output = await listener.suproc.stderr.read()
                LOGGER.error(f"❌ Failed to merge segments: {stderr_output.decode().strip()}")
                await clean_target(outfile)

        await clean_target(media_file)
        listener.seed = False
        await move(outfile, base_dir)

    except Exception as e:
        LOGGER.error(f"❌ Error in cut_video_segments: {str(e)}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def get_audio_sort_map(media_info, user_audio_sort, sort_mode='keep'):
    """
    Generates FFmpeg map args.
    sort_mode: 'keep' (default) or 'remove'
    """
    if not user_audio_sort: return []
    
    audio_streams = []
    for stream in media_info['streams']:
        if stream['codec_type'] == 'audio':
            lang = stream.get('tags', {}).get('language', 'und').lower()
            audio_streams.append({'index': stream['index'], 'lang': lang})
            
    if not audio_streams: return []

    new_order_indices = []
    
    # 1. Add preferred languages in order
    for pref_lang in user_audio_sort:
        matches = [s for s in audio_streams if s['lang'] == pref_lang]
        for match in matches:
            if match['index'] not in new_order_indices:
                new_order_indices.append(match['index'])
    
    # 2. Append remaining streams ONLY if mode is 'keep'
    if sort_mode == 'keep':
        for stream in audio_streams:
            if stream['index'] not in new_order_indices:
                new_order_indices.append(stream['index'])

    # If 'remove' mode was on and no preferred languages were found in the file,
    # we shouldn't return an empty map (which deletes ALL audio). 
    # Fallback: keep original audio if result would be silent.
    if not new_order_indices and sort_mode == 'remove':
        return [] # Returning empty list implies "do nothing/keep original" in main func

    ffmpeg_map_args = []
    for stream_idx in new_order_indices:
        ffmpeg_map_args.extend(['-map', f'0:{stream_idx}'])
        
    return ffmpeg_map_args

async def edit_audio_sort(listener, base_dir, media_file, outfile, audio_sort):
    # Fetch mode from user_dict, default to 'keep'
    sort_mode = listener.user_dict.get('audio_sort_mode', 'keep')

    probe_cmd = ['ffprobe', '-hide_banner', '-loglevel', 'error', '-print_format', 'json', '-show_streams', media_file]
    process = await create_subprocess_exec(*probe_cmd, stdout=PIPE, stderr=PIPE)
    stdout, _ = await process.communicate()
    try:
        media_info = json.loads(stdout)
    except:
        return 

    # Pass mode to logic function
    map_args = get_audio_sort_map(media_info, audio_sort, sort_mode)
    
    if not map_args:
        return

    cmd = [
        'ffmpeg', '-hide_banner', '-ignore_unknown', '-y',
        '-i', media_file,
        '-map', '0:v',   
        *map_args,       
        '-map', '0:s?',  
        '-map', '0:d?', 
        '-map', '0:t?', 
        '-c', 'copy',
        '-disposition:a', '0',          # Clears any old default flags
        '-disposition:a:0', 'default',  # Forces your #1 sorted language to be Default
        
        outfile
    ]

    LOGGER.info(f"Sorting Audio ({sort_mode}) for {media_file}...")
    
    listener.suproc = await create_subprocess_exec(*cmd, stderr=PIPE)
    code = await listener.suproc.wait()
    
    if code == 0:
        await clean_target(media_file)
        await move(outfile, base_dir)
        listener.seed = False
    else:
        LOGGER.error(f"Audio Sort Failed for {media_file}")
        await clean_target(outfile)


