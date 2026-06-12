import re
import os
# ─── Auto Thumbnail Code ─────────────────────────────
import requests
from urllib.parse import quote_plus
from aiohttp import ClientSession
from aiofiles import open as aiopen

from asyncio import create_subprocess_exec, gather, Semaphore
from asyncio.subprocess import PIPE
from contextlib import suppress
from hashlib import md5
from os import path as ospath
from re import sub as re_sub, search as re_search
from shlex import split as ssplit
from time import strftime, gmtime, time

from aiofiles.os import remove as aioremove, path as aiopath, mkdir, makedirs, listdir
from aioshutil import rmtree as aiormtree
from langcodes import Language
from natsort import natsorted
from telegraph import upload_file

from bot import bot_cache, LOGGER, MAX_SPLIT_SIZE, config_dict, DATABASE_URL, user_data
from bot.helper.ext_utils.bot_utils import cmd_exec, sync_to_async, get_readable_file_size, get_readable_time
from bot.helper.ext_utils.fs_utils import ARCH_EXT, get_mime_type
from bot.helper.ext_utils.telegraph_helper import telegraph
from bot.modules.mediainfo import parseinfo

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TMDB_API_URL = "https://api.themoviedb.org/3/search/multi"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

async def is_multi_streams(path):
    try:
        result = await cmd_exec(["ffprobe", "-hide_banner", "-loglevel", "error", "-print_format",
                                 "json", "-show_streams", path])
        if res := result[1]:
            LOGGER.warning(f'Get Video Streams: {res}')
    except Exception as e:
        LOGGER.error(f'Get Video Streams: {e}. Mostly File not found!')
        return False
    fields = eval(result[0]).get('streams')
    if fields is None:
        LOGGER.error(f"get_video_streams: {result}")
        return False
    videos = 0
    audios = 0
    for stream in fields:
        if stream.get('codec_type') == 'video':
            videos += 1
        elif stream.get('codec_type') == 'audio':
            audios += 1
    return videos > 1 or audios > 1


async def get_media_info(path, metadata=False):
    try:
        result = await cmd_exec(["ffprobe", "-hide_banner", "-loglevel", "error", "-print_format",
                                 "json", "-show_format", "-show_streams", path])
        if res := result[1]:
            LOGGER.warning(f'Media Info FF: {res}')
    except Exception as e:
        LOGGER.error(f'Media Info: {e}. Mostly File not found!')
        return (0, "", "", "") if metadata else (0, None, None)
    ffresult = eval(result[0])
    fields = ffresult.get('format')
    if fields is None:
        LOGGER.error(f"Media Info Sections: {result}")
        return (0, "", "", "") if metadata else (0, None, None)
    duration = round(float(fields.get('duration', 0)))
    if metadata:
        lang, qual, stitles = "", "", ""
        if (streams := ffresult.get('streams')) and streams[0].get('codec_type') == 'video':
            qual = int(streams[0].get('height'))
            qual = f"{240 if qual <= 240 else 360 if qual <= 360 else 480 if qual <= 480 else 540 if qual <= 540 else 576 if qual <= 576 else 720 if qual <= 720 else 1080 if qual <= 1080 else 2160 if qual <= 2160 else 4320 if qual <= 4320 else 8640}p"
            for stream in streams:
                if stream.get('codec_type') == 'audio' and (lc := stream.get('tags', {}).get('language')):
                    with suppress(Exception):
                        lc = Language.get(lc).display_name()
                    if lc not in lang:
                        lang += f"{lc}, "
                if stream.get('codec_type') == 'subtitle' and (st := stream.get('tags', {}).get('language')):
                    with suppress(Exception):
                        st = Language.get(st).display_name()
                    if st not in stitles:
                        stitles += f"{st}, "
        return duration, qual, lang[:-2], stitles[:-2]
    tags = fields.get('tags', {})
    artist = tags.get('artist') or tags.get('ARTIST') or tags.get("Artist")
    title = tags.get('title') or tags.get('TITLE') or tags.get("Title")
    return duration, artist, title


async def get_document_type(path):
    is_video, is_audio, is_image = False, False, False
    if path.endswith(tuple(ARCH_EXT)) or re_search(r'.+(\.|_)(rar|7z|zip|bin)(\.0*\d+)?$', path):
        return is_video, is_audio, is_image
    mime_type = await sync_to_async(get_mime_type, path)
    if mime_type.startswith('audio'):
        return False, True, False
    if mime_type.startswith('image'):
        return False, False, True
    if not mime_type.startswith('video') and not mime_type.endswith('octet-stream'):
        return is_video, is_audio, is_image
    try:
        result = await cmd_exec(["ffprobe", "-hide_banner", "-loglevel", "error", "-print_format",
                                 "json", "-show_streams", path])
        if res := result[1]:
            LOGGER.warning(f'Get Document Type: {res}')
    except Exception as e:
        LOGGER.error(f'Get Document Type: {e}. Mostly File not found!')
        return is_video, is_audio, is_image
    fields = eval(result[0]).get('streams')
    if fields is None:
        LOGGER.error(f"get_document_type: {result}")
        return is_video, is_audio, is_image
    for stream in fields:
        if stream.get('codec_type') == 'video':
            is_video = True
        elif stream.get('codec_type') == 'audio':
            is_audio = True
    return is_video, is_audio, is_image


async def get_audio_thumb(audio_file):
    des_dir = 'Thumbnails'
    if not await aiopath.exists(des_dir):
        await mkdir(des_dir)
    des_dir = ospath.join(des_dir, f"{time()}.jpg")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
           "-i", audio_file, "-an", "-vcodec", "copy", des_dir]
    status = await create_subprocess_exec(*cmd, stderr=PIPE)
    if await status.wait() != 0 or not await aiopath.exists(des_dir):
        err = (await status.stderr.read()).decode().strip()
        LOGGER.error(
            f'Error while extracting thumbnail from audio. Name: {audio_file} stderr: {err}')
        return None
    return des_dir


async def take_ss(video_file, duration=None, total=1, gen_ss=False):
    des_dir = ospath.join('Thumbnails', f"{time()}")
    await makedirs(des_dir, exist_ok=True)
    if duration is None:
        duration = (await get_media_info(video_file))[0]
    if duration == 0:
        duration = 3
    duration = duration - (duration * 2 / 100)
    cmd = ['ffmpeg', "-hide_banner", "-loglevel", "error", "-ss", "",
           "-i", video_file, "-vf", "thumbnail", "-frames:v", "1", des_dir]
    tstamps = {}
    thumb_sem = Semaphore(3)

    async def extract_ss(eq_thumb):
        async with thumb_sem:
            cmd[5] = str((duration // total) * eq_thumb)
            tstamps[f"wz_thumb_{eq_thumb}.jpg"] = strftime("%H:%M:%S", gmtime(float(cmd[5])))
            cmd[-1] = ospath.join(des_dir, f"wz_thumb_{eq_thumb}.jpg")
            task = await create_subprocess_exec(*cmd, stderr=PIPE)
            return (task, await task.wait(), eq_thumb)

    tasks = [extract_ss(eq_thumb) for eq_thumb in range(1, total+1)]
    status = await gather(*tasks)

    for task, rtype, eq_thumb in status:
        if rtype != 0 or not await aiopath.exists(ospath.join(des_dir, f"wz_thumb_{eq_thumb}.jpg")):
            err = (await task.stderr.read()).decode().strip()
            LOGGER.error(f'Error while extracting thumbnail no. {eq_thumb} from video. Name: {video_file} stderr: {err}')
            await aiormtree(des_dir)
            return None
    return (des_dir, tstamps) if gen_ss else ospath.join(des_dir, "wz_thumb_1.jpg")


async def split_file(path, size, file_, dirpath, split_size, listener, start_time=0, i=1, inLoop=False, multi_streams=True):
    if listener.suproc == 'cancelled' or listener.suproc is not None and listener.suproc.returncode == -9:
        return False
    if listener.seed and not listener.newDir:
        dirpath = f"{dirpath}/splited_files_mltb"
        if not await aiopath.exists(dirpath):
            await mkdir(dirpath)
    user_id = listener.message.from_user.id
    user_dict = user_data.get(user_id, {})
    leech_split_size = user_dict.get(
        'split_size') or config_dict['LEECH_SPLIT_SIZE']
    parts = -(-size // leech_split_size)
    if (user_dict.get('equal_splits') or config_dict['EQUAL_SPLITS'] and 'equal_splits' not in user_dict) and not inLoop:
        split_size = ((size + parts - 1) // parts) + 1000
    if (await get_document_type(path))[0]:
        if multi_streams:
            multi_streams = await is_multi_streams(path)
        duration = (await get_media_info(path))[0]
        base_name, extension = ospath.splitext(file_)
        split_size -= 5000000
        while i <= parts or start_time < duration - 4:
            parted_name = f"{base_name}.part{i:03}{extension}"
            out_path = ospath.join(dirpath, parted_name)
            cmd =  ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(start_time), "-i", path,
                   "-fs", str(split_size), "-map", "0", "-map_chapters", "-1", "-async", "1", "-strict",
                   "-2", "-c", "copy", out_path]
            if not multi_streams:
                del cmd[10]
                del cmd[10]
            if listener.suproc == 'cancelled' or listener.suproc is not None and listener.suproc.returncode == -9:
                return False
            listener.suproc = await create_subprocess_exec(*cmd, stderr=PIPE)
            code = await listener.suproc.wait()
            if code == -9:
                return False
            elif code != 0:
                err = (await listener.suproc.stderr.read()).decode().strip()
                try:
                    await aioremove(out_path)
                except Exception:
                    pass
                if multi_streams:
                    LOGGER.warning(
                        f"{err}. Retrying without map, -map 0 not working in all situations. Path: {path}")
                    return await split_file(path, size, file_, dirpath, split_size, listener, start_time, i, True, False)
                else:
                    LOGGER.warning(
                        f"{err}. Unable to split this video, if it's size less than {MAX_SPLIT_SIZE} will be uploaded as it is. Path: {path}")
                return "errored"
            out_size = await aiopath.getsize(out_path)
            if out_size > MAX_SPLIT_SIZE:
                dif = out_size - MAX_SPLIT_SIZE
                split_size -= dif + 5000000
                await aioremove(out_path)
                return await split_file(path, size, file_, dirpath, split_size, listener, start_time, i, True, )
            lpd = (await get_media_info(out_path))[0]
            if lpd == 0:
                LOGGER.error(
                    f'Something went wrong while splitting, mostly file is corrupted. Path: {path}')
                break
            elif duration == lpd:
                LOGGER.warning(
                    f"This file has been splitted with default stream and audio, so you will only see one part with less size from orginal one because it doesn't have all streams and audios. This happens mostly with MKV videos. Path: {path}")
                break
            elif lpd <= 3:
                await aioremove(out_path)
                break
            start_time += lpd - 3
            i += 1
    else:
        out_path = ospath.join(dirpath, f"{file_}.")
        listener.suproc = await create_subprocess_exec("split", "--numeric-suffixes=1", "--suffix-length=3",
                                                       f"--bytes={split_size}", path, out_path, stderr=PIPE)
        code = await listener.suproc.wait()
        if code == -9:
            return False
        elif code != 0:
            err = (await listener.suproc.stderr.read()).decode().strip()
            LOGGER.error(err)
    return True

# ─── Auto Thumbnail & Attachment Functions ───────────────────────

async def save_url_thumb(url: str, user_id: int):
    if not await aiopath.exists("Thumbnails"):
        await mkdir("Thumbnails")

    async with ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                content = await resp.read()
                thumb_path = f"Thumbnails/{user_id}.jpg"
                async with aiopen(thumb_path, "wb") as f:
                    await f.write(content)
                return thumb_path
    return None


def fetch_tmdb_poster(title: str, year: str = None):
    if not TMDB_API_KEY:
        return None
    try:
        params = {"api_key": TMDB_API_KEY, "query": title}
        if year:
            params["year"] = year

        response = requests.get(TMDB_API_URL, params=params)

        if response.status_code != 200:
            LOGGER.warning(
                f"[AutoThumb] TMDB API error: {response.status_code} - {response.text}"
            )
            return None

        data = response.json()
        results = data.get("results")
        if not results:
            return None

        # ✅ Fuzzy match: compare title with TMDB result
        from difflib import SequenceMatcher

        def similarity(a, b):
            return SequenceMatcher(None, a.lower(), b.lower()).ratio()

        best_match = max(
            results,
            key=lambda r: similarity(title, r.get("title") or r.get("name", "")),
        )
        match_title = best_match.get("title") or best_match.get("name")

        # ✅ Accept only if similarity is high
        if similarity(title, match_title) >= 0.6:
            poster_path = best_match.get("backdrop_path") or best_match.get(
                "poster_path"
            )
            if poster_path:
                return f"{TMDB_IMAGE_BASE}{poster_path}"
        else:
            LOGGER.warning(
                f'[AutoThumb] TMDB best match "{match_title}" doesn\'t match "{title}" enough'
            )
    except Exception as e:
        LOGGER.warning(f"TMDB Poster Fetch Error: {e}")
    return None


async def get_tmdb_lookup(filename: str):
    """
    Cleans filename and fetches poster URL from TMDB.
    Returns URL or None.
    Used for both Auto Thumbnail and Auto Attachment.
    """
    try:
        raw_name = ospath.splitext(filename)[0]

        # ✅ FIX: Aggressively remove websites and spam tags BEFORE splitting words
        clean_name = re_sub(r'(?:www\S+|https?:\S+|@\w+|\[[^\]]+\])', '', raw_name, flags=re.IGNORECASE)

        # Now replace dots/underscores
        clean_name = re_sub(r"[_\.]", " ", clean_name)
        
        # Remove Resolution/Codecs
        clean_name = re_sub(
            r"\b(480p|720p|1080p|2160p|4k|8k|web[- ]?dl|hq hdrip|bluray|webrip|hdrip|dvdrip|x264|x265|hevc|aac|dd5?\.?1|5\.1|dual|multi|subs?|dts|atm|repack|remux|uncut)\b",
            "",
            clean_name,
            flags=re.IGNORECASE,
        )
        clean_name = re_sub(r"\s+", " ", clean_name).strip()
        
        title_guess, year = None, None
        year_match = re_search(r"\b(19|20)\d{2}\b", clean_name)
        if year_match:
            year = year_match.group(0)
        series_match = re_search(r"(.+?S\d{2})", clean_name, re.IGNORECASE)
        if series_match:
            title_guess = series_match.group(1).strip()
            title_guess = re_sub(
                r"S\d{2}.*", "", title_guess, flags=re.IGNORECASE
            ).strip()
            year = None
        else:
            movie_match = re_search(r"(.+?)\b(19|20)\d{2}\b", clean_name)
            if movie_match:
                title_guess = movie_match.group(1).strip()
                title_guess = re_sub(r"\s+[\(\[\{]+$", "", title_guess).strip()
            else:
                title_guess = clean_name.strip()

        if title_guess:
            LOGGER.info(f"[TMDB Lookup] Title: {title_guess} | Year: {year}")
            return fetch_tmdb_poster(title_guess, year)
    except Exception as e:
        LOGGER.warning(f"TMDB Lookup Error for {filename}: {e}")
    return None

async def format_filename(file_, user_id, dirpath=None, isMirror=False, for_metadata=False):
    user_dict = user_data.get(user_id, {})
    ftag, ctag = ('m', 'MIRROR') if isMirror else ('l', 'LEECH')

    # Get user-specific or config values
    def get_user_value(key, default):
        return config_dict[default] if (val := user_dict.get(f'{ftag}{key}', '')) == '' else val

    prefix = get_user_value('prefix', f'{ctag}_FILENAME_PREFIX')
    remname = get_user_value('remname', f'{ctag}_FILENAME_REMNAME')
    suffix = get_user_value('suffix', f'{ctag}_FILENAME_SUFFIX')
    autorename = get_user_value('autorename', f'{ctag}_FILENAME_AUTORENAME')
    lcaption = config_dict['LEECH_FILENAME_CAPTION'] if (val := user_dict.get('lcaption', '')) == '' else val

    # ✅ ADDED: Caption Replace Config
    caption_replace = user_dict.get('lcaption_replace', config_dict.get('LEECH_CAPTION_REPLACE', ''))

    prefile_ = file_
    file_cleaned = re_sub(r"^[w]{1,4}\S+\s*[-_]*\s*", "", file_)
    file_ = file_cleaned

    # ✅ ADDED: Season Extraction
    season = "Unknown"
    season_patterns = [
        re.compile(r"S(\d+)(?:E|EP)", re.IGNORECASE),
        re.compile(r"S(\d+)\s*(?:E|EP)", re.IGNORECASE),
        re.compile(r"Season\s*(\d+)", re.IGNORECASE),
        re.compile(r"S(\d+)\b", re.IGNORECASE),
    ]
    for pattern in season_patterns:
        match = pattern.search(file_cleaned)
        if match:
            season = f"S{match.group(1).zfill(2)}"
            break

    # Extract episode (Modified to track index for Title extraction)
    episode = 'Unknown'
    episode_end_index = 0  # Track position
    for pattern in [
        re.compile(r'S(\d+)(?:E|EP)(\d+)', re.IGNORECASE),
        re.compile(r'S(\d+)\s*(?:E|EP|-\s*EP)(\d+)', re.IGNORECASE),
        re.compile(r'(?:[([<{]?\s*(?:E|EP)\s*(\d+)\s*[)\]>}]?)', re.IGNORECASE),
        re.compile(r'(?:\s*-\s*(\d+)\s*)', re.IGNORECASE),
        re.compile(r'S(\d+)[^\d]*(\d+)', re.IGNORECASE),
        re.compile(r'(\d+)', re.IGNORECASE)
    ]:
        match = pattern.search(file_cleaned)
        if match:
            groups = match.groups()
            episode_num = groups[-1].zfill(2)  # Zero pad to 2 digits
            episode = f"EP{episode_num}"
            episode_end_index = match.end()  # Save the end position
            break

    # Extract quality (Modified to track index for Title extraction)
    aquality = 'Unknown'
    quality_start_index = len(file_cleaned) # Default to end
    quality_patterns = [
        re.compile(r'\b(?:\d{3,4}[^\dp]*p|4k|2k|hd|sd|WEB-DL|WEBRip|HDTV|BluRay|BRRip|DvDRip|HQ HDRip|HDRip|H\.264|H\.265|x264|x265|HEVC|H264|H265|xvid|rip|bluray|dvdrip|[0-9]+MB|[0-9]+GB|bdrip|hdtv)\b', re.IGNORECASE)
    ]
    for pattern in quality_patterns:
        match = pattern.search(file_cleaned)
        if match:
            aquality = match.group(0)
            quality_start_index = match.start() # Save the start position
            break

    # ✅ ADDED: Episode Title Extraction
    eptitle = ""
    if episode != "Unknown" and episode_end_index > 0:
        end_cut = quality_start_index if quality_start_index > episode_end_index else len(ospath.splitext(file_cleaned)[0])
        raw_title = file_cleaned[episode_end_index:end_cut]
        cleaned_title = re_sub(r"[._\-\[\](){}]", " ", raw_title).strip()
        cleaned_title = re_sub(r"\s+", " ", cleaned_title)
        if len(cleaned_title) > 1:
            eptitle = cleaned_title

    up_path = ospath.join(dirpath, prefile_) if dirpath else None
    try:
        file_size = get_readable_file_size(await aiopath.getsize(up_path)) if up_path else ''
    except Exception:
        file_size = ''

    # Apply remname replacements early on cleaned filename
    if remname:
        if not remname.startswith('|'):
            remname = f"|{remname}"
        remname = remname.replace(r'\s', ' ')
        parts = remname.split('|')
        base_name = ospath.splitext(file_cleaned)[0]
        for part in parts[1:]:
            args = part.split(':')
            if len(args) == 3:
                base_name = re.sub(args[0], args[1], base_name, int(args[2]))
            elif len(args) == 2:
                base_name = re.sub(args[0], args[1], base_name)
            elif len(args) == 1:
                base_name = re.sub(args[0], '', base_name)
        file_cleaned = base_name + ospath.splitext(file_cleaned)[1]
        LOGGER.info(f"Remname applied result: {file_cleaned}")

    # Apply autorename if enabled, on file_cleaned
    if autorename:
        name_only, ext = ospath.splitext(file_cleaned)
        file_renamed = autorename.format(
            season=season if season != "Unknown" else "",   # ✅
            episode=episode if episode != 'Unknown' else '',
            eptitle=eptitle if eptitle else "",             # ✅
            aquality=aquality if aquality != 'Unknown' else '',
            filename=name_only,
            size=file_size or ''
        ) + ext
    else:
        file_renamed = file_cleaned

    # Save filename for caption BEFORE prefix and suffix are applied
    filename_for_caption = file_renamed

    # Return early if only the clean filename for metadata is needed
    if for_metadata:
        return file_renamed, ""

    # ✅ ADDED: Caption Replace Logic
    if caption_replace:
        if not caption_replace.startswith("|"):
            caption_replace = f"|{caption_replace}"
        caption_replace = caption_replace.replace(r"\s", " ")
        parts = caption_replace.split("|")
        temp_filename = filename_for_caption
        for part in parts[1:]:
            args = part.split(":")
            if len(args) == 2:
                find_pattern = r"\b" + re.escape(args[0]) + r"\b"
                temp_filename = re_sub(find_pattern, args[1], temp_filename)
            elif len(args) == 1:
                find_pattern = r"\b" + re.escape(args[0]) + r"\b"
                temp_filename = re_sub(find_pattern, "", temp_filename)
        filename_for_caption = temp_filename

    # Apply prefix
    if prefix:
        prefix = prefix.replace(r'\s', ' ')
        if not file_renamed.lower().startswith(prefix.lower()):
            file_renamed = f"{prefix}{file_renamed}"

    # ✅ FULL SUFFIX LOGIC RESTORED
    if suffix and not isMirror:
        suffix = suffix.replace(r'\s', ' ')
        suf_len = len(suffix)
        file_parts = file_renamed.split('.')
        ext_len = 1 + len(file_parts[-1])
        name_only_part = '.'.join(file_parts[:-1]).replace('.', ' ').replace('-', ' ')
        new_name = f"{name_only_part}{suffix}.{file_parts[-1]}"
        if len(name_only_part) > (64 - (suf_len + ext_len)):
            new_name = name_only_part[:64 - (suf_len + ext_len)] + f"{suffix}.{file_parts[-1]}"
        file_renamed = new_name
    elif suffix:
        suffix = suffix.replace(r'\s', ' ')
        if '.' in file_renamed:
            file_renamed = f"{ospath.splitext(file_renamed)[0]}{suffix}{ospath.splitext(file_renamed)[1]}"
        else:
            file_renamed = f"{file_renamed}{suffix}"

    # Generate caption
    cap_mono = filename_for_caption
    if lcaption and dirpath and not isMirror:
        def lowerVars(match):
            return f"{{{match.group(1).lower()}}}"

        lcaption_tmp = lcaption.replace(r'\|', '%%').replace(r'\{', '&%&').replace(r'\}', '$%$').replace(r'\s', ' ')
        slit = lcaption_tmp.split("|")
        slit[0] = re.sub(r'\{([^}]+)\}', lowerVars, slit[0])
        try:
            dur, qual, lang, subs = await get_media_info(up_path, True)
        except Exception:
            dur, qual, lang, subs = '', '', '', ''

        cap_mono = slit[0].format(
            filename=filename_for_caption,
            oldname = prefile_,
            size=file_size,
            duration=get_readable_time(dur),
            quality=qual,
            languages=lang,
            subtitles=subs,
            md5_hash=get_md5_hash(up_path),
            season=season,    # ✅
            episode=episode,
            eptitle=eptitle,  # ✅
            aquality=aquality
        )

        if len(slit) > 1:
            for rep in range(1, len(slit)):
                args = slit[rep].split(":")
                if len(args) == 3:
                    cap_mono = cap_mono.replace(args[0], args[1], int(args[2]))
                elif len(args) == 2:
                    cap_mono = cap_mono.replace(args[0], args[1])
                elif len(args) == 1:
                    cap_mono = cap_mono.replace(args[0], '')

        cap_mono = cap_mono.replace('%%', '|').replace('&%&', '{').replace('$%$', '}')

    # Apply caption font tag if configured
    if config_dict.get('CAP_FONT'):
        cap_mono = f"<{config_dict['CAP_FONT']}>{cap_mono}</{config_dict['CAP_FONT']}>"

     # ✅ Auto TMDB Thumbnail logic
    if user_dict.get("auto_thumbnail", False) and not isMirror and dirpath:
        try:
            # 1. Start with the original filename, remove extension
            raw_name = ospath.splitext(prefile_)[0]

            # 2. ✅ FIX: Aggressively remove 'www' links and spam tags FIRST
            clean_name = re_sub(r'(?:www\S+|https?:\S+|@\w+|\[[^\]]+\])', '', raw_name, flags=re.IGNORECASE)

            # 3. Replace dots/underscores with spaces
            clean_name = re_sub(r'[_\.]', ' ', clean_name)

            # 4. Remove Resolution/Quality tags
            clean_name = re_sub(r'\b(480p|720p|1080p|2160p|4k|8k|web[- ]?dl|hq hdrip|bluray|webrip|hdrip|dvdrip|x264|x265|hevc|aac|dd5?\.?1|5\.1|dual|multi|subs?|dts|atm|repack|remux|uncut)\b', '', clean_name, flags=re.IGNORECASE)
            
            # 5. Clean up extra spaces
            clean_name = re_sub(r'\s+', ' ', clean_name).strip()

            title_guess, year = None, None

            # 6. Extract Year
            year_match = re.search(r'\b(19|20)\d{2}\b', clean_name)
            if year_match:
                year = year_match.group(0)

            # 7. Extract Title
            series_match = re.search(r'(.+?S\d{2})', clean_name, re.IGNORECASE)
            if series_match:
                title_guess = series_match.group(1).strip()
                title_guess = re.sub(r'S\d{2}.*', '', title_guess, flags=re.IGNORECASE).strip()
                year = None
            else:
                movie_match = re.search(r'(.+?)\b(19|20)\d{2}\b', clean_name)
                if movie_match:
                    title_guess = movie_match.group(1).strip()
                    title_guess = re.sub(r'\s+[\(\[\{]+$', '', title_guess).strip()
                else:
                    title_guess = clean_name.strip()

            LOGGER.info(f"[AutoThumb] TMDB Title Guess: '{title_guess}' Year: '{year}'")

            poster_url = fetch_tmdb_poster(title_guess, year)
            if poster_url:
                LOGGER.info(f"[AutoThumb] TMDB Poster URL: {poster_url}")
                thumb_path = await save_url_thumb(poster_url, user_id)
                if thumb_path:
                    LOGGER.info(f"[AutoThumb] Thumbnail Saved to: {thumb_path}")
                    if DATABASE_URL:
                        from bot.helper.ext_utils.db_handler import DbManger
                        await DbManger().update_user_data(user_id)
                    LOGGER.info(f"[AutoThumb] Thumb set in DB: {user_data[user_id].get('thumb')}")
        except Exception as e:
            LOGGER.warning(f"Auto thumbnail failed: {e}")

    return file_renamed, cap_mono

async def get_ss(up_path, ss_no):
    thumbs_path, tstamps = await take_ss(up_path, total=min(ss_no, 250), gen_ss=True)
    th_html = f"📌 <h4>{ospath.basename(up_path)}</h4><br>📇 <b>Total Screenshots:</b> {ss_no}<br><br>"
    up_sem = Semaphore(25)
    async def telefile(thumb):
        async with up_sem:
            tele_id = await sync_to_async(upload_file, ospath.join(thumbs_path, thumb))
            return tele_id[0], tstamps[thumb]
    tasks = [telefile(thumb) for thumb in natsorted(await listdir(thumbs_path))]
    results = await gather(*tasks)
    th_html += ''.join(f'<img src="https://graph.org{tele_id}"><br><pre>Screenshot at {stamp}</pre>' for tele_id, stamp in results)
    await aiormtree(thumbs_path)
    link_id = (await telegraph.create_page(title="ScreenShots X", content=th_html))["path"]
    return f"https://graph.org/{link_id}"


async def get_mediainfo_link(up_path):
    stdout, __, _ = await cmd_exec(ssplit(f'mediainfo "{up_path}"'))
    tc = f"📌 <h4>{ospath.basename(up_path)}</h4><br><br>"
    if len(stdout) != 0:
        tc += parseinfo(stdout)
    link_id = (await telegraph.create_page(title="MediaInfo X", content=tc))["path"]
    return f"https://graph.org/{link_id}"


def get_md5_hash(up_path):
    md5_hash = md5()
    with open(up_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            md5_hash.update(byte_block)
        return md5_hash.hexdigest()
