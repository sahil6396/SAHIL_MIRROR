#!/usr/bin/env python3
from datetime import datetime
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.filters import command, regex, create
from aiofiles import open as aiopen
from aiofiles.os import remove as aioremove, path as aiopath, mkdir, rename as aiorename
from langcodes import Language
from os import path as ospath, getcwd
from PIL import Image
from time import time
from functools import partial
from html import escape
from io import BytesIO
from asyncio import sleep
from cryptography.fernet import Fernet
from math import ceil

from bot import OWNER_ID, LOGGER, bot, user_data, config_dict, categories_dict, DATABASE_URL, IS_PREMIUM_USER, MAX_SPLIT_SIZE
from bot.helper.telegram_helper.message_utils import sendMessage, sendCustomMsg, editMessage, deleteMessage, sendFile, chat_info, user_info
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.mirror_utils.upload_utils.gdriveTools import GoogleDriveHelper
from bot.helper.ext_utils.db_handler import DbManger
from bot.helper.ext_utils.bot_utils import getdailytasks, update_user_ldata, get_readable_file_size, sync_to_async, new_thread, is_gdrive_link
from bot.helper.mirror_utils.upload_utils.ddlserver.gofile import Gofile
from bot.helper.themes import BotTheme

# --- GLOBAL CONFIGURATIONS ---

# ✅ UPDATED: Contains ALL settings now (Universal, DDL, Merge, etc.)
PROFILE_KEYS = [
    # Leech
    'lprefix', 'lsuffix', 'lremname', 'lautorename', 'lcaption', 'ldump', 'thumb', 'split_size',
    'as_doc', 'media_group', 'equal_splits', 'lcaption_replace', 'auto_thumbnail',
    
    # Mirror & DDL
    'mprefix', 'msuffix', 'mremname', 'mautorename', 'rclone', 'user_tds', 'ddl_servers', 'td_mode',
    
    # Universal / General
    'merge_vid', 'keepsource', 'yt_opt', 'usess', 'bot_pm', 'mediainfo', 'save_mode',
    
    # FFmpeg & Metadata
    'general_metadata', 'video_metadata', 'audio_metadata', 'subtitle_metadata', 'metadata_mode',
    'attachment', 'attachment_name', 'auto_attachment',
    'audio_sort', 'audio_sort_mode', 'subtitle', 'introsub', 'audioremove', 
    'audiochange', 'audiolanguage', 'audiofile', 'audiobitrate', 'remsub', 'cut',
    'intro_font', 'intro_colour' , 'smart_sync'
]

FONT_MAP = {
    'Arial': 'Arial',
    'Times New Roman': 'Times New Roman',
    'Courier New': 'Courier New',
    'Verdana': 'Verdana',
    'Tahoma': 'Tahoma',
    'Comic Sans MS': 'Comic Sans MS',
    'Impact': 'Impact',
    'Georgia': 'Georgia',
    'Trebuchet MS': 'Trebuchet MS',
    'Helvetica': 'Helvetica'
}

COLOUR_MAP = {
    '#FFFFFF': 'White',
    '#FF0000': 'Red',
    '#00FF00': 'Green',
    '#0000FF': 'Blue',
    '#FFFF00': 'Yellow',
    '#000000': 'Black',
    '#00FFFF': 'Cyan',
    '#FF00FF': 'Magenta',
    '#FFA500': 'Orange',
    '#800080': 'Purple'
}

LANG_MAP = {
    'mal': 'Malayalam', 'tam': 'Tamil', 'tel': 'Telugu', 'kan': 'Kannada', 'hin': 'Hindi',
    'ben': 'Bengali', 'mar': 'Marathi', 'guj': 'Gujarati', 'pan': 'Punjabi', 'urd': 'Urdu',
    'eng': 'English', 'kor': 'Korean', 'jpn': 'Japanese', 'chi': 'Chinese',
    'spa': 'Spanish', 'fre': 'French', 'ger': 'German', 'rus': 'Russian', 'ara': 'Arabic',
    'por': 'Portuguese', 'ind': 'Indonesian', 'vie': 'Vietnamese', 'tha': 'Thai', 'tur': 'Turkish',
    'ita': 'Italian', 'per': 'Persian', 'pol': 'Polish', 'dut': 'Dutch'
}

handler_dict = {}
desp_dict = {
    'rcc': ['RClone is a command-line program to sync files and directories to and from different cloud storage providers like GDrive, OneDrive...', 'Send rclone.conf. \n<b>Timeout:</b> 60 sec'],
    'lprefix': ['Leech Filename Prefix is the Front Part attacted with the Filename of the Leech Files.', 'Send Leech Filename Prefix. Documentation Here : <a href="https://t.me/WZML_X/77">Click Me</a> \n<b>Timeout:</b> 60 sec'],
    'lsuffix': ['Leech Filename Suffix is the End Part attached with the Filename of the Leech Files', 'Send Leech Filename Suffix. Documentation Here : <a href="https://t.me/WZML_X/77">Click Me</a> \n<b>Timeout:</b> 60 sec'],
    'lremname': ['Leech Filename Remname is combination of Regex(s) used for removing or manipulating Filename of the Leech Files', 'Send Leech Filename Remname. Documentation Here : <a href="https://t.me/WZML_X/77">Click Me</a> \n<b>Timeout:</b> 60 sec'],
    'lautorename': ['Leech Autorename is the Custom rename on the Leech Files Uploaded by the bot', 'Send Leech AutoRename Format.\n\n<b>Placeholders:</b>\n{season}, {episode}, {eptitle}, {aquality}, {size}\n\n<b>Example:</b>\n<code>MySeries {season} {episode} {eptitle} [{aquality}] {size}</code>\n<b>Timeout:</b> 60 sec'],
    'lcaption': ['Leech Caption is the Custom Caption on the Leech Files Uploaded by the bot', 'Send Leech Caption. You can add HTML tags. Documentation Here : <a href="https://t.me/WZML_X/77">Click Me</a> \n<b>Timeout:</b> 60 sec'],
    'lcaption_replace': ['Words to find and replace in the final leech caption. Rules are separated by \'|\'.','Send caption replacement rules in one line, separated by a pipe (`|`). Format: `old:new` to replace, `word` to delete. Example: `unwanted word|1080p:FullHD`. Timeout: 60 sec'],  
    'ldump': ['Leech Files User Dump for Personal Use as a Storage.', 'Send Leech Dump Channel ID\n➲ <b>Format:</b> \ntitle chat_id/@username\ntitle2 chat_id2/@username2. \n\n<b>NOTE:</b>Make Bot Admin in the Channel else it will not accept\n<b>Timeout:</b> 60 sec'],
    'mprefix': ['Mirror Filename Prefix is the Front Part attacted with the Filename of the Mirrored/Cloned Files.', 'Send Mirror Filename Prefix. \n<b>Timeout:</b> 60 sec'],
    'msuffix': ['Mirror Filename Suffix is the End Part attached with the Filename of the Mirrored/Cloned Files', 'Send Mirror Filename Suffix. \n<b>Timeout:</b> 60 sec'],
    'mremname': ['Mirror Filename Remname is combination of Regex(s) used for removing or manipulating Filename of the Mirrored/Cloned Files', 'Send Mirror Filename Remname. \n<b>Timeout:</b> 60 sec'],
    'mautorename': ['Mirror Autorename is the Custom rename on the Leech Files Uploaded by the bot', 'Send Mirror AutoRename Format.\n\n<b>Placeholders:</b>\n{season}, {episode}, {eptitle}, {aquality}, {size}\n\n<b>Example:</b>\n<code>MySeries {season} {episode} {eptitle} [{aquality}] {size}</code>\n<b>Timeout:</b> 60 sec'],
    'general_metadata': ['Main file metadata.', 'Send the metadata for the main file title. Supports key=value pairs (e.g., "title=@Retro_Bots -{file name}|comment=Encoded by @Retro_Bots"). \n<b>Timeout:</b> 60 sec'],
    'video_metadata': ['Video track metadata.', 'Send video track title.\n<b>Placeholders:</b> {video_codec}\n\n<b>Example:</b>\n<code>@Retro_Bots {video_codec}</code>\n<b>Timeout:</b> 60 sec'],
    'audio_metadata': ['Audio track metadata.', 'Send the metadata for audio tracks.\n\n<b>Variables:</b>\n• <code>{codec_info}</code> : Adds codec info (e.g., [DDP 5.1])\n• <code>{language}</code> : Adds regional language name (e.g., తెలుగు, தமிழ்)\n\n<i>Example:</i> <code>MyFile {language} - {codec_info}</code>\n<b>Timeout:</b> 60 sec'],
    'subtitle_metadata': ['Subtitle track metadata.', 'Send subtitle track title.\n\n<b>Example:</b>\n<code> @Retro_Bots - {sub_lang}</code>\n<b>Timeout:</b> 60 sec'],
    'attachment': ['Attachment url, it will added in mkv as thumbnail or cover photo or embed thumb, whetever you say.', 'Send photo url. \n\n<b>Timeout:</b> 60 sec'],
    'attachment_name': ['Custom filename for the attachment.', 'Send the desired filename for the attachment (without extension). \n\n<b>Timeout:</b> 60 sec'],
    'auto_attachment': ['Auto Attachment will automatically fetch the cover/poster from TMDB based on filename and add it to the MKV file.', 'Enable or Disable Auto Attachment.'],
    'audioremove': ['Audio Removal is the process that removing specified audio.', 'Example :\n\nDefault audio : audio : 0, audio : 1, audio : 2\n\nSpecified audio : 0,2\n\n<b>Timeout:</b> 60 sec'],
    'audiochange': ['Audio Swaping is the process that modifies the order or Arrangement of audio', 'Example :\n\nDefault : audio : 0, audio : 1, audio 2, audio 3\n\nNew Arrangment : 2,1,3,0\n\n<b>Timeout:</b> 60 sec'],
    'audiobitrate': ['Audio bitrate changes the quality of the audio track. You must provide bitrate for each stream or a global one.', 'Example: <code>64k</code> for all, or <code>1:192k,2:128k</code> for individual streams.\n\n<b>Timeout:</b> 60 sec'],  
    'audiolanguage': ['Audio Language is the process that modifies the order or Lnaguage of audio is Wrong', 'Example :\n\nFor Tamil audio use tam, For Malayalam audio use Mal,Hindi audio hin etc... \n\nask admin for other doubts\n\n<b>Timeout:</b> 60 sec'],
    'audiofile': ['add new audio to media ', 'Send audio Url. \n\n<b>Timeout:</b> 60 sec'],
    'remsub': ['Removes all subtitle tracks except the ones you specify.','Send subtitle stream numbers to keep. Example: <code>1</code> keeps only the first subtitle.\n\n<b>Timeout:</b> 60 sec'], 
    'subtitle': ['Subtile is the process that add subtile if the file or media does not have subtitle', 'Send SRT Url. \n\n<b>Timeout:</b> 60 sec'],
    'introsub': ['Adds a custom intro text in subtitle.', 'Send Custom Text to add to the intro subtitle. \n\n<b>Timeout:</b> 60 sec'],
    'thumb': ['Custom Thumbnail to appear on the Leeched files uploaded by the bot', 'Send a photo to save it as custom thumbnail. \n<b>Alternatively: </b><code>/cmd [photo] -s thumb</code> \n<b>Timeout:</b> 60 sec'],
    'autothumb': ['Set a custom or automatic thumbnail for files uploaded by the bot.','<b>Auto Thumbnail:</b> Automatically fetches poster from TMDB/IMDB based on the filename (movie/series).\n <b>Timeout:</b> 60 seconds'],
    'yt_opt': ['YT-DLP Options is the Custom Quality for the extraction of videos from the yt-dlp supported sites.', 'Send YT-DLP Options. Timeout: 60 sec\nFormat: key:value|key:value|key:value.\nExample: format:bv*+mergeall[vcodec=none]|nocheckcertificate:True\nCheck all yt-dlp api options from this <a href="https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py#L184">FILE</a> to convert cli arguments to api options.'],
    'usess': [f'User Session is Telegram Session used to Download Private Contents from Private Channels with no compromise in Privacy, Build with Encryption.\n{"<b>Warning:</b> This Bot is not secured. We recommend asking the group owner to set the Upstream repo to the Official repo. If it is not the official repo, then WZML-X is not responsible for any issues that may occur in your account." if config_dict["UPSTREAM_REPO"] != "https://github.com/weebzone/WZML-X" else "Bot is Secure. You can use the session securely."}', 'Send your Session String.\n<b>Timeout:</b> 60 sec'],
    'split_size': ['Leech Splits Size is the size to split the Leeched File before uploading', f'Send Leech split size in any comfortable size, like 2Gb, 500MB or 1.46gB. \n<b>PREMIUM ACTIVE:</b> {IS_PREMIUM_USER}. \n<b>Timeout:</b> 60 sec'],
    'ddl_servers': ['DDL Servers which uploads your File to their Specific Hosting', ''],
    'user_tds': [f'UserTD helps to Upload files via Bot to your Custom Drive Destination via Global SA mail\n\n➲ <b>SA Mail :</b> {"Not Specified" if "USER_TD_SA" not in config_dict else config_dict["USER_TD_SA"]}', 'Send User TD details for Use while Mirror/Clone\n➲ <b>Format:</b>\nname id/link index(optional)\nname2 link2/id2 index(optional)\n\n<b>NOTE:</b>\n<i>1. Drive ID must be valid, then only it will accept\n2. Names can have spaces\n3. All UserTDs are updated on every change\n4. To delete specific UserTD, give Name(s) separated by each line</i>\n\n<b>Timeout:</b> 60 sec'],
    'gofile': ['Gofile is a free file sharing and storage platform. You can store and share your content without any limit.', "Send GoFile's API Key. Get it on https://gofile.io/myProfile, It will not be Accepted if the API Key is Invalid !!\n<b>Timeout:</b> 60 sec"],
    'streamtape': ['Streamtape is free Video Streaming & sharing Hoster', "Send StreamTape's Login and Key\n<b>Format:</b> <code>user_login:pass_key</code>\n<b>Timeout:</b> 60 sec"],
    'cut': ['Trim & Merge Use For Cutting any mkv format manualy', "Send format in below format:\n\n00:00:00 00:00:30 for 30sec video. \n<b>Timeout:</b> 60 sec"],
    'audio_sort' : ['Sort audio tracks based on your language preference. The bot will reorder tracks to match your list.', 'Select languages to add to your priority list. Use Next/Prev to browse.'],
}

fname_dict = {'rcc': 'RClone',
             'lprefix': 'Prefix',
             'lsuffix': 'Suffix',
             'lremname': 'Remname',
             'lautorename': 'Autorename',
             'lcaption_replace': 'Caption Replace',
             'mprefix': 'Prefix',
             'msuffix': 'Suffix',
             'mremname': 'Remname',
             'mautorename': 'Autorename',
             'general_metadata': 'General Metadata',
             'video_metadata': 'Video Metadata',
             'audio_metadata': 'Audio Metadata',
             'subtitle_metadata': 'Subtitle Metadata',
             'attachment': 'Attachment URL',
             'attachment_name': 'Attachment Name',
             'auto_attachment': 'Auto Attachment',
             'audioremove': 'Audio Remove',
             'audiochange': 'Audio Change',
             'audiobitrate': 'Audio Bitrate',
             'audiolanguage': 'Audio Language',
             'audiofile': 'Audio Mux',
             'remsub': 'Remove subtitle',
             'subtitle' : 'Add Subtitle',
             'introsub' : 'Intro Sub',
             'ldump': 'User Dump',
             'lcaption': 'Caption',
             'thumb': 'Thumbnail',
             'autothumb': 'Auto Thumbnail',
             'yt_opt': 'YT-DLP Options',
             'usess': 'User Session',
             'split_size': 'Leech Splits',
             'ddl_servers': 'DDL Servers',
             'user_tds': 'User Custom TDs',
             'gofile': 'GoFile',
             'streamtape': 'StreamTape',
             'cut': 'Trim & Merge',
             'audio_sort': 'Audio Sorting'
             }

async def swap_user_profile(user_id):
    user_dict = user_data.get(user_id, {})
    is_secondary = user_dict.get('is_secondary_profile', False)
    
    # Define Storage Keys
    save_to = 'main_storage' if not is_secondary else 'sec_storage'
    load_from = 'sec_storage' if not is_secondary else 'main_storage'
    
    # --- 1. Swap Physical Files (Thumbnails & Rclone) ---
    thumb_active = f"Thumbnails/{user_id}.jpg"
    thumb_main   = f"Thumbnails/{user_id}_main.jpg"
    thumb_sec    = f"Thumbnails/{user_id}_sec.jpg"
    
    rclone_active = f"wcl/{user_id}.conf"
    rclone_main   = f"wcl/{user_id}_main.conf"
    rclone_sec    = f"wcl/{user_id}_sec.conf"

    if not is_secondary:
        # Switching Main -> Secondary
        if await aiopath.exists(thumb_active):
            await aiorename(thumb_active, thumb_main)
        if await aiopath.exists(rclone_active):
            await aiorename(rclone_active, rclone_main)
            
        if await aiopath.exists(thumb_sec):
            await aiorename(thumb_sec, thumb_active)
        if await aiopath.exists(rclone_sec):
            await aiorename(rclone_sec, rclone_active)
    else:
        # Switching Secondary -> Main
        if await aiopath.exists(thumb_active):
            await aiorename(thumb_active, thumb_sec)
        if await aiopath.exists(rclone_active):
            await aiorename(rclone_active, rclone_sec)
            
        if await aiopath.exists(thumb_main):
            await aiorename(thumb_main, thumb_active)
        if await aiopath.exists(rclone_main):
            await aiorename(rclone_main, rclone_active)

    # --- 2. Swap Text Settings ---
    storage_data = {}
    for key in PROFILE_KEYS:
        if key in user_dict:
            storage_data[key] = user_dict[key]
    update_user_ldata(user_id, save_to, storage_data)
    
    for key in PROFILE_KEYS:
        if key in user_dict:
            del user_dict[key]
            
    target_data = user_dict.get(load_from, {})
    for key, value in target_data.items():
        user_dict[key] = value
        
    update_user_ldata(user_id, 'is_secondary_profile', not is_secondary)
    
    if DATABASE_URL:
        await DbManger().update_user_data(user_id)
        await DbManger().update_user_doc(user_id, 'thumb') 
        await DbManger().update_user_doc(user_id, 'rclone')
        
    return not is_secondary

async def get_user_settings(from_user, key=None, edit_type=None, edit_mode=None):
    user_id = from_user.id
    name = from_user.mention(style="html")
    buttons = ButtonMaker()
    thumbpath = f"Thumbnails/{user_id}.jpg"
    rclone_path = f'wcl/{user_id}.conf'
    user_dict = user_data.get(user_id, {})
    
    if key is None:
        is_sec = user_dict.get('is_secondary_profile', False)
        profile_name = "Secondary 2️⃣" if is_sec else "Main 1️⃣"
        buttons.ibutton(f"👤 Profile: {profile_name}", f"userset {user_id} switch_profile")
        
        buttons.ibutton("Universal Settings", f"userset {user_id} universal")
        buttons.ibutton("Mirror Settings", f"userset {user_id} mirror")
        buttons.ibutton("Leech Settings", f"userset {user_id} leech")
        buttons.ibutton("FFmpeg Settings", f"userset {user_id} ffmpeg") 
        if user_dict and any(key in user_dict for key in list(fname_dict.keys())):
            buttons.ibutton("Reset Setting", f"userset {user_id} reset_all")
        buttons.ibutton("Close", f"userset {user_id} close")

        text = BotTheme('USER_SETTING', NAME=name, ID=user_id, USERNAME=f'@{from_user.username}', LANG=Language.get(lc).display_name() if (lc := from_user.language_code) else "N/A", DC=from_user.dc_id)
        button = buttons.build_menu(1)
        
    elif key == 'universal':
        merge_vid = "Enabled" if user_dict.get('merge_vid') else "Disabled"
        buttons.ibutton('Merge Enabled ✅' if merge_vid == 'Enabled' else 'Merge Disabled', f"userset {user_id} merge_vid", 'header')
        keep_source = "Enabled" if user_dict.get('keepsource') else "Disabled"
        buttons.ibutton('Keep Source Enabled ✅' if keep_source == 'Enabled' else 'Keep Source Disabled', f"userset {user_id} keepsource", 'header')
        
        ytopt = 'Not Exists' if (val:=user_dict.get('yt_opt', config_dict.get('YT_DLP_OPTIONS', ''))) == '' else val
        buttons.ibutton(f"{'✅️' if ytopt != 'Not Exists' else ''} YT-DLP Options", f"userset {user_id} yt_opt")
        u_sess = 'Exists' if user_dict.get('usess', False) else 'Not Exists'
        buttons.ibutton(f"{'✅️' if u_sess != 'Not Exists' else ''} User Session", f"userset {user_id} usess")
        
        bot_pm = "Enabled" if user_dict.get('bot_pm', config_dict['BOT_PM']) else "Disabled"
        buttons.ibutton('Disable Bot PM' if bot_pm == 'Enabled' else 'Enable Bot PM', f"userset {user_id} bot_pm")
        if config_dict['BOT_PM']: bot_pm = "Force Enabled"
        
        mediainfo = "Enabled" if user_dict.get('mediainfo', config_dict['SHOW_MEDIAINFO']) else "Disabled"
        buttons.ibutton('Disable MediaInfo' if mediainfo == 'Enabled' else 'Enable MediaInfo', f"userset {user_id} mediainfo")
        if config_dict['SHOW_MEDIAINFO']: mediainfo = "Force Enabled"
        
        save_mode = "Save As Dump" if user_dict.get('save_mode') else "Save As BotPM"
        buttons.ibutton('Save As BotPM' if save_mode == 'Save As Dump' else 'Save As Dump', f"userset {user_id} save_mode")
        
        dailytl = config_dict['DAILY_TASK_LIMIT'] or "∞"
        dailytas = user_dict.get('dly_tasks')[1] if user_dict and user_dict.get('dly_tasks') and user_id != OWNER_ID and config_dict['DAILY_TASK_LIMIT'] else config_dict['DAILY_TASK_LIMIT'] or "️∞" if user_id != OWNER_ID else "∞"
        if user_dict.get('dly_tasks', False):
            t = str(datetime.now() - user_dict['dly_tasks'][0]).split(':')
            lastused = f"{t[0]}h {t[1]}m {t[2].split('.')[0]}s ago"
        else: lastused = "Bot Not Used yet.."

        text = BotTheme('UNIVERSAL', NAME=name, MERGE_VID=merge_vid, KEEP_SOURCE=keep_source, YT=escape(ytopt), DT=f"{dailytas} / {dailytl}", LAST_USED=lastused, BOT_PM=bot_pm, MEDIAINFO=mediainfo, SAVE_MODE=save_mode, USESS=u_sess)
        buttons.ibutton("Back", f"userset {user_id} back", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)
        
    elif key == 'mirror':
        buttons.ibutton("RClone", f"userset {user_id} rcc")
        rccmsg = "Exists" if await aiopath.exists(rclone_path) else "Not Exists"
        dailytlup = get_readable_file_size(config_dict['DAILY_MIRROR_LIMIT'] * 1024**3) if config_dict['DAILY_MIRROR_LIMIT'] else "∞"
        dailyup = get_readable_file_size(await getdailytasks(user_id, check_mirror=True)) if config_dict['DAILY_MIRROR_LIMIT'] and user_id != OWNER_ID else "️∞"
        
        buttons.ibutton("Mirror Prefix", f"userset {user_id} mprefix")
        mprefix = 'Not Exists' if (val:=user_dict.get('mprefix', config_dict.get('MIRROR_FILENAME_PREFIX', ''))) == '' else val
        buttons.ibutton("Mirror Suffix", f"userset {user_id} msuffix")
        msuffix = 'Not Exists' if (val:=user_dict.get('msuffix', config_dict.get('MIRROR_FILENAME_SUFFIX', ''))) == '' else val
        buttons.ibutton("Mirror Remname", f"userset {user_id} mremname")
        mremname = 'Not Exists' if (val:=user_dict.get('mremname', config_dict.get('MIRROR_FILENAME_REMNAME', ''))) == '' else val
        buttons.ibutton("Mirror Autorename", f"userset {user_id} mautorename")
        mautorename = 'Not Exists' if (val:=user_dict.get('mautorename', config_dict.get('MIRROR_FILENAME_AUTORENAME', ''))) == '' else val

        ddl_serv = len(val) if (val := user_dict.get('ddl_servers', False)) else 0
        buttons.ibutton("DDL Servers", f"userset {user_id} ddl_servers")

        tds_mode = "Enabled" if user_dict.get('td_mode', False) else "Disabled"
        if not config_dict['USER_TD_MODE']: tds_mode = "Force Disabled"

        user_tds = len(val) if (val := user_dict.get('user_tds', False)) else 0
        buttons.ibutton("User TDs", f"userset {user_id} user_tds")

        text = BotTheme('MIRROR', NAME=name, RCLONE=rccmsg, DDL_SERVER=ddl_serv, DM=f"{dailyup} / {dailytlup}", MREMNAME=escape(mremname), MPREFIX=escape(mprefix),
                MSUFFIX=escape(msuffix),  MAUTORENAME=escape(mautorename), TMODE=tds_mode, USERTD=user_tds)
        buttons.ibutton("Back", f"userset {user_id} back", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)
        
    elif key == 'leech':
        if user_dict.get('as_doc', False) or 'as_doc' not in user_dict and config_dict['AS_DOCUMENT']:
            ltype = "DOCUMENT"
            buttons.ibutton("Send As Media", f"userset {user_id} doc")
        else:
            ltype = "MEDIA"
            buttons.ibutton("Send As Document", f"userset {user_id} doc")

        dailytlle = get_readable_file_size(config_dict['DAILY_LEECH_LIMIT'] * 1024**3) if config_dict['DAILY_LEECH_LIMIT'] else "️∞"
        dailyll = get_readable_file_size(await getdailytasks(user_id, check_leech=True)) if config_dict['DAILY_LEECH_LIMIT'] and user_id != OWNER_ID else "∞"

        thumbmsg = "Exists" if await aiopath.exists(thumbpath) else "Not Exists"
        buttons.ibutton(f"{'✅️' if thumbmsg == 'Exists' else ''} Thumbnail", f"userset {user_id} thumb")
        autothumb = "Enabled" if user_dict.get("auto_thumbnail", False) else "Disabled"
        buttons.ibutton(f"{'✅️' if autothumb == 'Enabled' else ''} Auto Thumbnail", f"userset {user_id} autothumb")
        
        split_size = get_readable_file_size(config_dict['LEECH_SPLIT_SIZE']) + ' (Default)' if user_dict.get('split_size', '') == '' else get_readable_file_size(user_dict['split_size'])
        equal_splits = 'Enabled' if user_dict.get('equal_splits', config_dict.get('EQUAL_SPLITS')) else 'Disabled'
        media_group = 'Enabled' if user_dict.get('media_group', config_dict.get('MEDIA_GROUP')) else 'Disabled'
        buttons.ibutton(f"{'✅️' if user_dict.get('split_size') else ''} Leech Splits", f"userset {user_id} split_size")

        lcaption = 'Not Exists' if (val:=user_dict.get('lcaption', config_dict.get('LEECH_FILENAME_CAPTION', ''))) == '' else val
        buttons.ibutton(f"{'✅️' if lcaption != 'Not Exists' else ''} Leech Caption", f"userset {user_id} lcaption")
        lprefix = 'Not Exists' if (val:=user_dict.get('lprefix', config_dict.get('LEECH_FILENAME_PREFIX', ''))) == '' else val
        buttons.ibutton(f"{'✅️' if lprefix != 'Not Exists' else ''} Leech Prefix", f"userset {user_id} lprefix")
        lsuffix = 'Not Exists' if (val:=user_dict.get('lsuffix', config_dict.get('LEECH_FILENAME_SUFFIX', ''))) == '' else val
        buttons.ibutton(f"{'✅️' if lsuffix != 'Not Exists' else ''} Leech Suffix", f"userset {user_id} lsuffix")
        lremname = 'Not Exists' if (val:=user_dict.get('lremname', config_dict.get('LEECH_FILENAME_REMNAME', ''))) == '' else val
        buttons.ibutton(f"{'✅️' if lremname != 'Not Exists' else ''} Leech Remname", f"userset {user_id} lremname")
        lautorename = 'Not Exists' if (val:=user_dict.get('lautorename', config_dict.get('LEECH_FILENAME_AUTORENAME', ''))) == '' else val
        buttons.ibutton(f"{'✅️' if lautorename != 'Not Exists' else ''} Leech Autorename", f"userset {user_id} lautorename")
        lcaption_replace = 'Not Exists' if (val:=user_dict.get('lcaption_replace', config_dict.get('LEECH_CAPTION_REPLACE', ''))) == '' else val
        buttons.ibutton(f"{'✅️' if lcaption_replace != 'Not Exists' else ''} Leech Caption Replace", f"userset {user_id} lcaption_replace")
        
        buttons.ibutton("Leech Dump", f"userset {user_id} ldump")
        ldump = 'Not Exists' if (val:=user_dict.get('ldump', '')) == '' else len(val)
        
        text = BotTheme('LEECH', NAME=name, DL=f"{dailyll} / {dailytlle}",
                LTYPE=ltype, THUMB=thumbmsg, SPLIT_SIZE=split_size,
                EQUAL_SPLIT=equal_splits, MEDIA_GROUP=media_group,
                LCAPTION=escape(lcaption), LPREFIX=escape(lprefix), LCAPTION_REPLACE=escape(lcaption_replace),
                LSUFFIX=escape(lsuffix), LDUMP=ldump, LREMNAME=escape(lremname),
                LAUTORENAME=escape(lautorename), AUTOTHUMB=autothumb)
        buttons.ibutton("Back", f"userset {user_id} back", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)

    elif key == 'ffmpeg':
        metadata_mode = "Enabled" if user_dict.get('metadata_mode', config_dict.get('METADATA_MODE', False)) else "Disabled"
        buttons.ibutton(f"Metadata Enabled ✅" if metadata_mode == 'Enabled' else "Metadata Disabled", f"userset {user_id} metadata_mode", "header")
        
        has_metadata = any(user_dict.get(key) for key in ['general_metadata', 'video_metadata', 'audio_metadata', 'subtitle_metadata'])
        metadata_status = "Exists" if has_metadata else "Not Exists"
        buttons.ibutton(f"{'✅' if has_metadata else ''} Metadata Settings", f"userset {user_id} metadata")
        
        has_attachment_settings = any(user_dict.get(key) for key in ['attachment', 'attachment_name', 'auto_attachment'])
        attachment_status = "Exists" if has_attachment_settings else "Not Exists"
        buttons.ibutton(f"{'✅' if has_attachment_settings else ''} Attachment Settings", f"userset {user_id} attachment_settings")

        subtitle = user_dict.get('subtitle', config_dict['SUBTITLE']) or 'Not Exists'
        buttons.ibutton(f"{'✅' if subtitle != 'Not Exists' else ''} Add Subtitle", f"userset {user_id} subtitle")

        introsub = user_dict.get('introsub', config_dict['INTROSUB']) or 'Not Exists'
        buttons.ibutton(f"{'✅' if introsub != 'Not Exists' else ''} Intro Sub", f"userset {user_id} introsub")

        audiolanguage = user_dict.get('audiolanguage', config_dict['AUDIOLANGUAGE']) or 'Not Exists'
        buttons.ibutton(f"{'✅' if audiolanguage != 'Not Exists' else ''} Audio Language", f"userset {user_id} audiolanguage")
        
        audioremove = user_dict.get('audioremove', config_dict['AUDIOREMOVE']) or 'Not Exists'
        buttons.ibutton(f"{'✅' if audioremove != 'Not Exists' else ''} Audio Remove", f"userset {user_id} audioremove")
        
        audiochange = user_dict.get('audiochange', config_dict['AUDIOCHANGE']) or 'Not Exists'
        buttons.ibutton(f"{'✅' if audiochange != 'Not Exists' else ''} Audio Change", f"userset {user_id} audiochange")

        audiofile = user_dict.get('audiofile', config_dict['AUDIOFILE']) or 'Not Exists'
        buttons.ibutton(f"{'✅' if audiofile != 'Not Exists' else ''} Audio Mux", f"userset {user_id} audiofile")

        smart_sync = user_dict.get('smart_sync', False)
        buttons.ibutton(f"Smart Delay: {'ON ✅' if smart_sync else 'OFF ❌'}", f"userset {user_id} smart_sync")
        
        audiobitrate = user_dict.get('audiobitrate', config_dict['AUDIOBITRATE']) or 'Not Exists'
        buttons.ibutton(f"{'✅' if audiobitrate != 'Not Exists' else ''} Audio Bitrate", f"userset {user_id} audiobitrate")

        remsub = user_dict.get('remsub', config_dict['REMSUB']) or 'Not Exists'
        buttons.ibutton(f"{'✅' if remsub != 'Not Exists' else ''} Select Subtitle", f"userset {user_id} remsub")

        cut = user_dict.get('cut', config_dict['CUT']) or 'Not Exists'
        buttons.ibutton(f"{'✅' if cut != 'Not Exists' else ''} Trim & Merge", f"userset {user_id} cut")

        audio_sort = "Set" if user_dict.get('audio_sort') else "Not Exists"
        buttons.ibutton(f"{'✅' if audio_sort == 'Set' else ''} Audio Auto-Sort", f"userset {user_id} audio_sort")

        text = BotTheme('FFMPEG_SETTINGS', NAME=name,
                METADATA_MODE=metadata_mode,
                AUDIOREMOVE=escape(audioremove), AUDIOCHANGE=escape(audiochange), 
                AUDIOBITRATE=escape(audiobitrate), AUDIOLANGUAGE=escape(audiolanguage), 
                REMSUB=escape(remsub), AUDIOFILE=escape(audiofile), 
                SUBTITLE=escape(subtitle), INTROSUB=escape(introsub), CUT=escape(cut),
                METADATA=metadata_status, ATTACHMENT_SETTINGS=attachment_status)

        buttons.ibutton("Back", f"userset {user_id} back", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)
        
    elif key == "ddl_servers":
        ddl_serv, serv_list = 0, []
        if (ddl_dict := user_dict.get('ddl_servers', False)):
            for serv, (enabled, _) in ddl_dict.items():
                if enabled:
                    serv_list.append(serv)
                    ddl_serv += 1
        text = f"㊂ <b><u>{fname_dict[key]} Settings :</u></b>\n\n" \
               f"➲ <b>Enabled DDL Server(s) :</b> <i>{ddl_serv}</i>\n\n" \
               f"➲ <b>Description :</b> <i>{desp_dict[key][0]}</i>"
        for btn in ['gofile', 'streamtape']:
            buttons.ibutton(f"{'✅️' if btn in serv_list else ''} {fname_dict[btn]}", f"userset {user_id} {btn}")
        buttons.ibutton("Back", f"userset {user_id} back mirror", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)
    elif key == 'metadata':
        general_meta = 'Not Exists' if (val := user_dict.get('general_metadata', config_dict.get('GENERAL_METADATA', ''))) == '' else val
        video_meta = 'Not Exists' if (val := user_dict.get('video_metadata', config_dict.get('VIDEO_METADATA', ''))) == '' else val
        audio_meta = 'Not Exists' if (val := user_dict.get('audio_metadata', config_dict.get('AUDIO_METADATA', ''))) == '' else val
        subtitle_meta = 'Not Exists' if (val := user_dict.get('subtitle_metadata', config_dict.get('SUBTITLE_METADATA', ''))) == '' else val

        buttons.ibutton(f"{'✅' if general_meta != 'Not Exists' else ''} General Metadata", f"userset {user_id} general_metadata")
        buttons.ibutton(f"{'✅' if video_meta != 'Not Exists' else ''} Video Metadata", f"userset {user_id} video_metadata")
        buttons.ibutton(f"{'✅' if audio_meta != 'Not Exists' else ''} Audio Metadata", f"userset {user_id} audio_metadata")
        buttons.ibutton(f"{'✅' if subtitle_meta != 'Not Exists' else ''} Subtitle Metadata", f"userset {user_id} subtitle_metadata")

        text = BotTheme('METADATA_MENU',
                        NAME=name,
                        GENERAL_META=escape(general_meta),
                        VIDEO_META=escape(video_meta),
                        AUDIO_META=escape(audio_meta),
                        SUBTITLE_META=escape(subtitle_meta))

        if general_meta != 'Not Exists' or video_meta != 'Not Exists' or audio_meta != 'Not Exists' or subtitle_meta != 'Not Exists':
            buttons.ibutton("↻ Delete All", f"userset {user_id} dmetadata")

        buttons.ibutton("Back", f"userset {user_id} back ffmpeg", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(1)
    
    elif key == 'attachment_settings':
        attachment_url = 'Not Exists' if (val := user_dict.get('attachment', config_dict.get('ATTACHMENT', ''))) == '' else val
        attachment_name = 'Not Exists' if (val := user_dict.get('attachment_name', config_dict.get('ATTACHMENT_NAME', ''))) == '' else val
        auto_attach = "Enabled" if user_dict.get("auto_attachment", False) else "Disabled"

        buttons.ibutton(f"{'✅' if attachment_url != 'Not Exists' else ''} Attachment URL", f"userset {user_id} attachment")
        buttons.ibutton(f"{'✅' if attachment_name != 'Not Exists' else ''} Attachment Name", f"userset {user_id} attachment_name")
        buttons.ibutton(f"{'✅' if auto_attach == 'Enabled' else ''} Auto Attachment", f"userset {user_id} auto_attachment")

        text = BotTheme('ATTACHMENT_MENU',
                        ATTACHMENT_URL=escape(attachment_url),
                        ATTACHMENT_NAME=escape(attachment_name),
                        AUTO_ATTACH=escape(auto_attach))

        if attachment_url != 'Not Exists' or attachment_name != 'Not Exists':
            buttons.ibutton("↻ Delete All", f"userset {user_id} dattachment_settings")
        buttons.ibutton("Back", f"userset {user_id} back ffmpeg", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(1)

    elif key == 'audio_sort':
        current_sort = user_dict.get('audio_sort', [])
        sort_mode = user_dict.get('audio_sort_mode', 'keep') 
        try: page = int(edit_mode)
        except: page = 0
        ITEMS_PER_PAGE = 10
        all_lang_keys = list(LANG_MAP.keys())
        total_items = len(all_lang_keys)
        total_pages = ceil(total_items / ITEMS_PER_PAGE)
        if page >= total_pages: page = max(0, total_pages - 1)
        start_idx = page * ITEMS_PER_PAGE
        page_langs = all_lang_keys[start_idx : start_idx + ITEMS_PER_PAGE]

        text = "㊂ <b><u>Audio Sorting Preferences</u></b>\n\n"
        mode_text = "Keep Unselected" if sort_mode == 'keep' else "Remove Unselected"
        text += f"➲ <b>Mode:</b> <u>{mode_text}</u>\n"
        
        if current_sort:
            text += "<b>Priority Order:</b>\n"
            for i, lang_code in enumerate(current_sort, 1):
                lang_name = LANG_MAP.get(lang_code, lang_code)
                text += f"<b>{i}. {lang_name}</b>\n"
            text += "\n"
        else:
            text += "<i>No priority set. Default file order used.</i>\n\n"
            
        text += f"➲ <b>Toggle Languages (Page {page + 1}/{max(1, total_pages)})</b>"

        for i in range(0, len(page_langs), 2):
            lang_1 = page_langs[i]
            name_1 = f"✅ {LANG_MAP[lang_1]}" if lang_1 in current_sort else LANG_MAP[lang_1]
            buttons.ibutton(name_1, f"userset {user_id} asort_toggle {lang_1} {page}")
            if i + 1 < len(page_langs):
                lang_2 = page_langs[i + 1]
                name_2 = f"✅ {LANG_MAP[lang_2]}" if lang_2 in current_sort else LANG_MAP[lang_2]
                buttons.ibutton(name_2, f"userset {user_id} asort_toggle {lang_2} {page}")
        
        if page > 0:
            buttons.ibutton("<<", f"userset {user_id} audio_sort {page - 1}")
        if page < total_pages - 1:
            buttons.ibutton(">>", f"userset {user_id} audio_sort {page + 1}")
        
        mode_btn = "🗑 Mode: Remove" if sort_mode == 'keep' else "📂 Mode: Keep"
        target_mode = 'remove' if sort_mode == 'keep' else 'keep'
        buttons.ibutton(mode_btn, f"userset {user_id} asort_mode {target_mode} {page}", "header")
        if current_sort:
            buttons.ibutton("↻ Reset List", f"userset {user_id} asort_reset {page}", "header")

        buttons.ibutton("Back", f"userset {user_id} back ffmpeg", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)

    elif key == 'introsub':
        current_text = user_dict.get('introsub', '')
        is_set = current_text and current_text != 'Not Set'

        if edit_mode:
            text = f"㊂ <b><u>Intro Subtitle</u></b>\n\n"
            text += desp_dict['introsub'][1]
            buttons.ibutton("Stop Change", f"userset {user_id} introsub")
        else:
            current_font = user_dict.get('intro_font', 'Arial')
            current_colour_code = user_dict.get('intro_colour', '#FFFFFF')
            current_colour_name = COLOUR_MAP.get(current_colour_code, 'White')

            text = f"㊂ <b><u>Intro Subtitle Settings</u></b>\n\n"
            if is_set:
                text += f"➲ <b>Text:</b> {escape(current_text)}\n"
                text += f"➲ <b>Font:</b> {current_font}\n"
                text += f"➲ <b>Colour:</b> {current_colour_name}\n\n"
                text += "<i>Select an option below to modify.</i>"
                buttons.ibutton("📝 Edit Text", f"userset {user_id} introsub edit")
                buttons.ibutton("🅰️ Change Font", f"userset {user_id} intro_font")
                buttons.ibutton("🎨 Change Colour", f"userset {user_id} intro_colour")
                buttons.ibutton("↻ Delete Intro", f"userset {user_id} dintrosub")
            else:
                text += "➲ <b>Text:</b> Not Set\n\n"
                text += "<i>You have not added an intro subtitle yet. Click below to add one.</i>"
                buttons.ibutton("➕ Add Intro Subtitle", f"userset {user_id} introsub edit")

            buttons.ibutton("Back", f"userset {user_id} back ffmpeg", "footer")
            buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)

    elif key == 'intro_font':
        try: page = int(edit_mode)
        except: page = 0
        ITEMS_PER_PAGE = 5
        font_list = list(FONT_MAP.keys())
        total_pages = ceil(len(font_list) / ITEMS_PER_PAGE)
        if page >= total_pages: page = max(0, total_pages - 1)
        start_idx = page * ITEMS_PER_PAGE
        page_fonts = font_list[start_idx : start_idx + ITEMS_PER_PAGE]
        current_font = user_dict.get('intro_font', 'Arial')

        text = f"㊂ <b><u>Select Intro Font</u></b>\n"
        text += f"Page {page + 1}/{total_pages}\n"
        for font in page_fonts:
            btn_text = f"✅ {font}" if font == current_font else font
            buttons.ibutton(btn_text, f"userset {user_id} set_ifont {font} {page}")
        if page > 0:
            buttons.ibutton("<<", f"userset {user_id} intro_font {page - 1}")
        if page < total_pages - 1:
            buttons.ibutton(">>", f"userset {user_id} intro_font {page + 1}")
        buttons.ibutton("Back", f"userset {user_id} back introsub", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(1)

    elif key == 'intro_colour':
        try: page = int(edit_mode)
        except: page = 0
        ITEMS_PER_PAGE = 5
        colour_list = list(COLOUR_MAP.items()) 
        total_pages = ceil(len(colour_list) / ITEMS_PER_PAGE)
        if page >= total_pages: page = max(0, total_pages - 1)
        start_idx = page * ITEMS_PER_PAGE
        page_colours = colour_list[start_idx : start_idx + ITEMS_PER_PAGE]
        current_code = user_dict.get('intro_colour', '#FFFFFF')

        text = f"㊂ <b><u>Select Intro Colour</u></b>\n"
        text += f"Page {page + 1}/{total_pages}\n"
        for code, name in page_colours:
            btn_text = f"✅ {name}" if code == current_code else name
            buttons.ibutton(btn_text, f"userset {user_id} set_icolour {code} {page}")
        if page > 0:
            buttons.ibutton("<<", f"userset {user_id} intro_colour {page - 1}")
        if page < total_pages - 1:
            buttons.ibutton(">>", f"userset {user_id} intro_colour {page + 1}")
        buttons.ibutton("Back", f"userset {user_id} back introsub", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(1)

    elif key == 'ldump' and not edit_mode:
        user_dumps = user_dict.get('ldump', {})
        dump_all = user_dict.get('dump_all', False)
        dump_selection = user_dict.get('dump_selection', [])

        if user_dumps:
            buttons.ibutton(f'Dump All: {"Enabled ✅" if dump_all else "Disabled ❌"}', f"userset {user_id} dump_all_toggle", "header")
            for name, _ in user_dumps.items():
                is_selected = name in dump_selection if dump_selection else True
                btn_text = f"✅ {name}" if is_selected else f"{name}"
                buttons.ibutton(btn_text, f"userset {user_id} sel_dump {name}")

        buttons.ibutton("➕ Add", f"userset {user_id} ldump edit")
        if user_dumps:
            buttons.ibutton("🗑 Delete", f"userset {user_id} dldump")

        text = f"㊂ <b><u>Leech Dump Settings</u></b>\n\n"
        text += f"➲ <b>Dump All Mode:</b> {dump_all}\n"
        text += f"➲ <b>Total Dumps:</b> {len(user_dumps)}\n"

        if user_dumps:
            text += "\n<b><u>Saved Dumps List:</u></b>\n"
            for i, (name, chat_id) in enumerate(user_dumps.items(), start=1):
                text += f"{i}. <b>{name}</b>: <code>{chat_id}</code>\n"

        if dump_all:
            active_dumps = dump_selection if dump_selection else list(user_dumps.keys())
            text += f"\n➲ <b>Active Dumps:</b> <code>{', '.join(active_dumps)}</code>\n\n"
            text += "<i>Click dump names to include/exclude them from Batch Upload. If none selected, ALL are used.</i>"
        else:
            if user_dumps:
                text += "\n<i>Enable 'Dump All' to auto-upload to these chats without asking.</i>"
            else:
                text += "\n<i>No dumps configured. Click Add to setup.</i>"

        buttons.ibutton("Back", f"userset {user_id} back leech", "footer")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)
    elif edit_type:
        text = f"㊂ <b><u>{fname_dict[key]} Settings :</u></b>\n\n"
        if key == 'rcc':
            set_exist = await aiopath.exists(rclone_path)
            text += f"➲ <b>RClone.Conf File :</b> <i>{'' if set_exist else 'Not'} Exists</i>\n\n"
        elif key == 'thumb':
            set_exist = await aiopath.exists(thumbpath)
            text += f"➲ <b>Custom Thumbnail :</b> <i>{'' if set_exist else 'Not'} Exists</i>\n\n"
        elif key == 'yt_opt':
            set_exist = 'Not Exists' if (val:=user_dict.get('yt_opt', config_dict.get('YT_DLP_OPTIONS', ''))) == '' else val
            text += f"➲ <b>YT-DLP Options :</b> <code>{escape(set_exist)}</code>\n\n"
        elif key == 'usess':
            set_exist = 'Exists' if user_dict.get('usess') else 'Not Exists'
            text += f"➲ <b>{fname_dict[key]} :</b> <code>{set_exist}</code>\n➲ <b>Encryption :</b> {'🔐' if set_exist else '🔓'}\n\n"
        elif key == 'split_size':
            set_exist = get_readable_file_size(config_dict['LEECH_SPLIT_SIZE']) + ' (Default)' if user_dict.get('split_size', '') == '' else get_readable_file_size(user_dict['split_size'])
            text += f"➲ <b>Leech Split Size :</b> <i>{set_exist}</i>\n\n"
            if user_dict.get('equal_splits', False) or ('equal_splits' not in user_dict and config_dict['EQUAL_SPLITS']):
                buttons.ibutton("Disable Equal Splits", f"userset {user_id} esplits", "header")
            else:
                buttons.ibutton("Enable Equal Splits", f"userset {user_id} esplits", "header")
            if user_dict.get('media_group', False) or ('media_group' not in user_dict and config_dict['MEDIA_GROUP']):
                buttons.ibutton("Disable Media Group", f"userset {user_id} mgroup", "header")
            else:
                buttons.ibutton("Enable Media Group", f"userset {user_id} mgroup", "header")
        elif key == 'autothumb':
            set_exist = 'Enabled' if user_dict.get("auto_thumbnail", False) else 'Disabled'
            text += f"➲ <b>Auto Thumbnail :</b> <i>{set_exist}</i>\n\n"
            buttons.ibutton("Disable AutoThumb" if set_exist == "Enabled" else "Enable AutoThumb", f"userset {user_id} autothumb", "header")
        
        elif key in ['lprefix', 'lremname', 'lautorename', 'lcaption_replace', 'cut', 'general_metadata', 'video_metadata', 'audio_metadata', 'subtitle_metadata', 'attachment', 'attachment_name', 'subtitle', 'audioremove', 'audiochange', 'audiolanguage', 'audiofile',  'audiobitrate', 'remsub', 'lsuffix', 'lcaption', 'ldump']:
            if key in ['attachment', 'subtitle', 'audioremove', 'audiochange', 'audiolanguage', 'audiofile', 'remsub', 'audiobitrate','cut']:
                 set_exist = 'Not Exists' if (val:=user_dict.get(key, config_dict.get(key.upper(), ''))) == '' else val
            elif key.startswith('l'):
                 set_exist = 'Not Exists' if (val:=user_dict.get(key, config_dict.get(f'LEECH_FILENAME_{key[1:].upper()}', ''))) == '' else val
            else:
                 set_exist = 'Not Exists' if (val:=user_dict.get(key, '')) == '' else val
            
            if set_exist != 'Not Exists' and key == "ldump":
                set_exist = '\n\n' + '\n'.join([f"{index}. <b>{dump}</b> : <code>{ids}</code>" for index, (dump, ids) in enumerate(val.items(), start=1)])
            
            if key.startswith('l') and key not in ['lcaption', 'ldump']:
                 text += f"➲ <b>Leech Filename {fname_dict[key]} :</b> {set_exist}\n\n"
            else:
                 text += f"➲ <b>{fname_dict[key]} :</b> {set_exist}\n\n"

        elif key in ['mprefix', 'mremname', 'msuffix' , 'mautorename']:
            set_exist = 'Not Exists' if (val:=user_dict.get(key, config_dict.get(f'MIRROR_FILENAME_{key[1:].upper()}', ''))) == '' else val
            text += f"➲ <b>Mirror Filename {fname_dict[key]} :</b> {set_exist}\n\n"
        elif key in ['gofile', 'streamtape']:
            set_exist = 'Exists' if key in (ddl_dict:=user_dict.get('ddl_servers', {})) and ddl_dict[key][1] and ddl_dict[key][1] != '' else 'Not Exists'
            ddl_mode = 'Enabled' if key in (ddl_dict:=user_dict.get('ddl_servers', {})) and ddl_dict[key][0] else 'Disabled'
            text = f"➲ <b>Upload {fname_dict[key]} :</b> {ddl_mode}\n" \
                   f"➲ <b>{fname_dict[key]}'s API Key :</b> {set_exist}\n\n"
            buttons.ibutton('Disable DDL' if ddl_mode == 'Enabled' else 'Enable DDL', f"userset {user_id} s{key}", "header")
        elif key == 'user_tds':
            set_exist = len(val) if (val:=user_dict.get(key, False)) else 'Not Exists'
            tds_mode = "Enabled" if user_dict.get('td_mode', False) else "Disabled"
            buttons.ibutton('Disable UserTDs' if tds_mode == 'Enabled' else 'Enable UserTDs', f"userset {user_id} td_mode", "header")
            if not config_dict['USER_TD_MODE']:
                tds_mode = "Force Disabled"
            text += f"➲ <b>User TD Mode :</b> {tds_mode}\n"
            text += f"➲ <b>{fname_dict[key]} :</b> {set_exist}\n\n"
        else: 
            return
        text += f"➲ <b>Description :</b> <i>{desp_dict[key][0]}</i>"
        if not edit_mode:
            buttons.ibutton(f"Change {fname_dict[key]}" if set_exist and set_exist != 'Not Exists' and (set_exist != get_readable_file_size(config_dict['LEECH_SPLIT_SIZE']) + ' (Default)') else f"Set {fname_dict[key]}", f"userset {user_id} {key} edit")
        else:
            text += '\n\n' + desp_dict[key][1]
            buttons.ibutton("Stop Change", f"userset {user_id} {key}")
        if set_exist and set_exist != 'Not Exists' and (set_exist != get_readable_file_size(config_dict['LEECH_SPLIT_SIZE']) + ' (Default)'):
            if key == 'thumb':
                buttons.ibutton("View Thumbnail", f"userset {user_id} vthumb", "header")
            elif key == 'user_tds':
                buttons.ibutton('Show UserTDs', f"userset {user_id} show_tds", "header")
            buttons.ibutton("↻ Delete", f"userset {user_id} d{key}")

        if edit_type == 'metadata':
             back_key = 'metadata'
        elif edit_type == 'attachment_settings':
             back_key = 'attachment_settings'
        elif edit_type == 'ldump':
             back_key = 'ldump'
        elif edit_type == 'ffmpeg': 
             back_key = 'ffmpeg'
        else:
             back_key = edit_type
        buttons.ibutton("Back", f"userset {user_id} back {back_key}", "footer")

        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        button = buttons.build_menu(2)
    return text, button

async def update_user_settings(query, key=None, edit_type=None, edit_mode=None, msg=None, sdirect=False):
    msg, button = await get_user_settings(msg.from_user if sdirect else query.from_user, key, edit_type, edit_mode)
    await editMessage(query if sdirect else query.message, msg, button)

async def user_settings(client, message):
    if len(message.command) > 1 and (message.command[1] == '-s' or message.command[1] == '-set'):
        set_arg = message.command[2].strip() if len(message.command) > 2 else None
        msg = await sendMessage(message, '<i>Fetching Settings...</i>', photo='IMAGES')
        if set_arg and (reply_to := message.reply_to_message):
            if message.from_user.id != reply_to.from_user.id:
                return await editMessage(msg, '<i>Reply to Your Own Message for Setting via Args Directly</i>')
            if set_arg in ['lprefix', 'lsuffix', 'lremname', 'lautorename', 'lcaption_replace', 'lcaption', 'ldump', 'yt_opt'] and reply_to.text:
                return await set_custom(client, reply_to, msg, set_arg, True)
            elif set_arg == 'thumb' and reply_to.media:
                return await set_thumb(client, reply_to, msg, set_arg, True)
        await editMessage(msg, '''㊂ <b><u>Available Flags :</u></b>
>> Reply to the Value with appropriate arg respectively to set directly without opening USet.

➲ <b>Custom Thumbnail :</b>
    /cmd -s thumb
➲ <b>Leech Filename Prefix :</b>
    /cmd -s lprefix
➲ <b>Leech Filename Suffix :</b>
    /cmd -s lsuffix
➲ <b>Leech Filename Remname :</b>
    /cmd -s lremname
➲ <b>Leech Filename Autorename :</b>
    /cmd -s lautorename
➲ <b>Leech Filename Caption :</b>
    /cmd -s lcaption
➲ <b>YT-DLP Options :</b>
    /cmd -s yt_opt
➲ <b>Leech User Dump :</b>
    /cmd -s ldump''')
    else:
        from_user = message.from_user
        handler_dict[from_user.id] = False
        msg, button = await get_user_settings(from_user)
        await sendMessage(message, msg, button, 'IMAGES')
                
async def set_custom(client, message, pre_event, key, direct=False):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    value = message.text
    return_key = 'leech'
    if key.endswith('_metadata'):
        return_key = 'metadata'
    if key in ['attachment', 'attachment_name']:
        return_key = 'attachment_settings'
    if key == 'ldump':
        return_key = 'ldump'
    if key in ['cut', 'subtitle', 'introsub', 'audioremove', 'audiochange', 'audiolanguage', 'audiofile', 'audiobitrate', 'remsub']:
        return_key = 'ffmpeg'

    n_key = key
    user_dict = user_data.get(user_id, {})
    if key in ['gofile', 'streamtape']:
        ddl_dict = user_dict.get('ddl_servers', {})
        mode, api = ddl_dict.get(key, [False, ""])
        if key == "gofile" and not await Gofile.is_goapi(value):
            value = ""
        ddl_dict[key] = [mode, value]
        value = ddl_dict
        n_key = 'ddl_servers'
        return_key = 'ddl_servers'
    elif key == 'user_tds':
        user_tds = user_dict.get(key, {})
        for td_item in value.split('\n'):
            if td_item == '':
                continue
            split_ck = td_item.split()
            td_details = td_item.rsplit(maxsplit=(2 if split_ck[-1].startswith('http') and not is_gdrive_link(split_ck[-1]) else 1 if len(split_ck[-1]) > 15 else 0))
            if td_details[0] in list(categories_dict.keys()):
                continue
            for title in list(user_tds.keys()):
                if td_details[0].casefold() == title.casefold():
                    del user_tds[title]
            if len(td_details) > 1:
                if is_gdrive_link(td_details[1].strip()):
                    td_details[1] = GoogleDriveHelper.getIdFromUrl(td_details[1])
                if await sync_to_async(GoogleDriveHelper().getFolderData, td_details[1]):
                    user_tds[td_details[0]] = {'drive_id': td_details[1],'index_link': td_details[2].rstrip('/') if len(td_details) > 2 else ''}
        value = user_tds
        return_key = 'mirror'
    elif key == 'ldump':
        ldumps = user_dict.get(key, {})
        for dump_item in value.split('\n'):
            if dump_item == '':
                continue
            dump_info = dump_item.rsplit(maxsplit=(1 if dump_item.split()[-1].startswith(('-100', '@')) else 0))
            if dump_info[0] in list(ldumps.keys()):
                continue
            for title in list(ldumps.keys()):
                if dump_info[0].casefold() == title.casefold():
                    del ldumps[title]
            if len(dump_info) > 1 and (dump_chat := await chat_info(dump_info[1])):
                ldumps[dump_info[0]] = dump_chat.id
        value = ldumps
    elif key in ['yt_opt', 'usess']:
        if key == 'usess':
            password = Fernet.generate_key()
            try:
                await deleteMessage(await (await sendCustomMsg(message.from_user.id, f"<u><b>Decryption Key:</b></u> \n┃\n┃ <code>{password.decode()}</code>\n┃\n┖ <b>Note:</b> <i>Keep this Key Securely, this is not Stored in Bot and Access Key to use your Session...</i>")).pin(both_sides=True))
                encrypt_sess = Fernet(password).encrypt(value.encode())
                value = encrypt_sess.decode()
            except Exception:
                value = ""
        return_key = 'universal'
    # --- INTRO SUB HANDLER (Generic text input) ---
    elif key == 'introsub':
        return_key = 'introsub'
        value = message.text # Direct text assignment
        
    update_user_ldata(user_id, n_key, value)
    await deleteMessage(message)
    await update_user_settings(pre_event, key, return_key, msg=message, sdirect=direct)
    if DATABASE_URL:
        await DbManger().update_user_data(user_id)

async def set_thumb(client, message, pre_event, key, direct=False):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    path = "Thumbnails/"
    if not await aiopath.isdir(path):
        await mkdir(path)
    photo_dir = await message.download()
    des_dir = ospath.join(path, f'{user_id}.jpg')
    await sync_to_async(Image.open(photo_dir).convert("RGB").save, des_dir, "JPEG")
    await aioremove(photo_dir)
    update_user_ldata(user_id, 'thumb', des_dir)
    await deleteMessage(message)
    await update_user_settings(pre_event, key, 'leech', msg=message, sdirect=direct)
    if DATABASE_URL:
        await DbManger().update_user_doc(user_id, 'thumb', des_dir)

async def add_rclone(client, message, pre_event):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    path = f'{getcwd()}/wcl/'
    if not await aiopath.isdir(path):
        await mkdir(path)
    des_dir = ospath.join(path, f'{user_id}.conf')
    await message.download(file_name=des_dir)
    update_user_ldata(user_id, 'rclone', f'wcl/{user_id}.conf')
    await deleteMessage(message)
    await update_user_settings(pre_event, 'rcc', 'mirror')
    if DATABASE_URL:
        await DbManger().update_user_doc(user_id, 'rclone', des_dir)

async def leech_split_size(client, message, pre_event):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    sdic = ['b', 'kb', 'mb', 'gb']
    value = message.text.strip()
    slice = -2 if value[-2].lower() in ['k', 'm', 'g'] else -1
    out = value[slice:].strip().lower()
    if out in sdic:
        value = min((float(value[:slice].strip()) * 1024**sdic.index(out)), MAX_SPLIT_SIZE)
    update_user_ldata(user_id, 'split_size', int(round(value)))
    await deleteMessage(message)
    await update_user_settings(pre_event, 'split_size', 'leech')
    if DATABASE_URL:
        await DbManger().update_user_data(user_id)

async def event_handler(client, query, pfunc, rfunc, photo=False, document=False):
    user_id = query.from_user.id
    handler_dict[user_id] = True
    start_time = time()

    async def event_filter(_, __, event):
        if photo:
            mtype = event.photo
        elif document:
            mtype = event.document
        else:
            mtype = event.text
        user = event.from_user or event.sender_chat
        return bool(user.id == user_id and event.chat.id == query.message.chat.id and mtype)
        
    handler = client.add_handler(MessageHandler(
        pfunc, filters=create(event_filter)), group=-1)
    while handler_dict[user_id]:
        await sleep(0.5)
        if time() - start_time > 60:
            handler_dict[user_id] = False
            await rfunc()
    client.remove_handler(*handler)

@new_thread
async def edit_user_settings(client, query):
    from_user = query.from_user
    user_id = from_user.id
    message = query.message
    data = query.data.split()
    thumb_path = f'Thumbnails/{user_id}.jpg'
    rclone_path = f'wcl/{user_id}.conf'
    user_dict = user_data.get(user_id, {})
    if user_id != int(data[1]):
        await query.answer("Not Yours!", show_alert=True)
    elif data[2] == 'switch_profile':
        handler_dict[user_id] = False
        new_state = await swap_user_profile(user_id)
        state_name = "Secondary" if new_state else "Main"
        await query.answer(f"Switched to {state_name} Profile!", show_alert=True)
        await update_user_settings(query)
    # ----------------------
    elif data[2] in ['universal', 'mirror', 'leech', 'ffmpeg']:
        await query.answer()
        await update_user_settings(query, data[2])
    elif data[2] == "doc":
        update_user_ldata(user_id, 'as_doc', not user_dict.get('as_doc', False))
        await query.answer()
        await update_user_settings(query, 'leech')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == 'metadata_mode':
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, 'metadata_mode', not user_dict.get('metadata_mode', False))
        await update_user_settings(query, 'ffmpeg')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    # --- ADD THIS BLOCK FOR SMART SYNC ---
    elif data[2] == 'smart_sync':
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, 'smart_sync', not user_dict.get('smart_sync', False))
        await update_user_settings(query, 'ffmpeg')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    # -------------------------------------
            
    elif data[2] in ['intro_font', 'intro_colour']:
        handler_dict[user_id] = False
        await query.answer()
        page = int(data[3]) if len(data) > 3 else 0
        await update_user_settings(query, data[2], edit_mode=page)

    # Set Font Logic
    elif data[2] == 'set_ifont':
        handler_dict[user_id] = False
        font_name = data[3]
        page = int(data[4]) if len(data) > 4 else 0
        
        update_user_ldata(user_id, 'intro_font', font_name)
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
            
        await query.answer(f"Font set to {font_name}")
        await update_user_settings(query, 'intro_font', edit_mode=page)

    # Set Colour Logic
    elif data[2] == 'set_icolour':
        handler_dict[user_id] = False
        colour_code = data[3]
        page = int(data[4]) if len(data) > 4 else 0
        
        update_user_ldata(user_id, 'intro_colour', colour_code)
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
            
        colour_name = COLOUR_MAP.get(colour_code, 'Custom')
        await query.answer(f"Colour set to {colour_name}")
        await update_user_settings(query, 'intro_colour', edit_mode=page)
        
    elif data[2] == 'vthumb':
        handler_dict[user_id] = False
        await query.answer()
        buttons = ButtonMaker()
        buttons.ibutton('Cʟᴏsᴇ', f'wzmlx {user_id} close')
        await sendMessage(message, from_user.mention, buttons.build_menu(1), thumb_path)
        await update_user_settings(query, 'thumb', 'leech')
    elif data[2] == 'show_tds':
        handler_dict[user_id] = False
        user_tds = user_dict.get('user_tds', {})
        msg = f'➲ <b><u>User TD(s) Details</u></b>\n\n<b>Total UserTD(s) :</b> {len(user_tds)}\n\n'
        for index_no, (drive_name, drive_dict) in enumerate(user_tds.items(), start=1):
            msg += f'{index_no}: <b>Name:</b> <code>{drive_name}</code>\n'
            msg += f"  <b>Drive ID:</b> <code>{drive_dict['drive_id']}</code>\n"
            msg += f"  <b>Index Link:</b> <code>{ind_url if (ind_url := drive_dict['index_link']) else 'Not Provided'}</code>\n\n"
        try:
            await sendCustomMsg(user_id, msg)
            await query.answer('User TDs Successfully Send in your PM', show_alert=True)
        except Exception:
            await query.answer('Start the Bot in PM (Private) and Try Again', show_alert=True)
        await update_user_settings(query, 'user_tds', 'mirror')
    elif data[2] == "dthumb":
        handler_dict[user_id] = False
        if await aiopath.exists(thumb_path):
            await query.answer()
            await aioremove(thumb_path)
            update_user_ldata(user_id, 'thumb', '')
            await update_user_settings(query, 'thumb', 'leech')
            if DATABASE_URL:
                await DbManger().update_user_doc(user_id, 'thumb')
        else:
            await query.answer("Old Settings", show_alert=True)
            await update_user_settings(query, 'leech')
    elif data[2] == 'thumb':
        await query.answer()
        edit_mode = len(data) == 4
        await update_user_settings(query, data[2], 'leech', edit_mode)
        if not edit_mode: return
        pfunc = partial(set_thumb, pre_event=query, key=data[2])
        rfunc = partial(update_user_settings, query, data[2], 'leech')
        await event_handler(client, query, pfunc, rfunc, True)
    elif data[2] == "autothumb":
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, "auto_thumbnail", not user_dict.get("auto_thumbnail", False))
        await update_user_settings(query, "leech")
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == "auto_attachment":
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, "auto_attachment", not user_dict.get("auto_attachment", False))
        await update_user_settings(query, "attachment_settings")
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == "auto_attachment":
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, "auto_attachment", not user_dict.get("auto_attachment", False))
        await update_user_settings(query, "attachment_settings")
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
            
    # --- PASTE THIS IN edit_user_settings ---
    elif data[2] == 'dintrosub':
        handler_dict[user_id] = False
        update_user_ldata(user_id, 'introsub', '') # Clear value
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
        await query.answer("Intro Subtitle deleted!", show_alert=True)
        await update_user_settings(query, 'introsub')
    
    elif data[2] == 'audio_sort':
        handler_dict[user_id] = False
        await query.answer()
        page = int(data[3]) if len(data) > 3 else 0
        await update_user_settings(query, 'audio_sort', edit_mode=page)

    elif data[2] == 'asort_toggle':
        handler_dict[user_id] = False
        lang_code = data[3]
        page = int(data[4]) if len(data) > 4 else 0
        current_sort = user_dict.get('audio_sort', [])
        
        if lang_code in current_sort:
            current_sort.remove(lang_code)
            msg = "Removed from list"
        else:
            current_sort.append(lang_code)
            msg = "Added to list"
            
        update_user_ldata(user_id, 'audio_sort', current_sort)
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
        
        await query.answer(msg)
        await update_user_settings(query, 'audio_sort', edit_mode=page)

    elif data[2] == 'asort_mode':
        handler_dict[user_id] = False
        new_mode = data[3]
        page = int(data[4]) if len(data) > 4 else 0
        
        update_user_ldata(user_id, 'audio_sort_mode', new_mode)
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
            
        await query.answer(f"Mode set to: {new_mode.capitalize()} Others")
        await update_user_settings(query, 'audio_sort', edit_mode=page)

    elif data[2] == 'asort_reset':
        handler_dict[user_id] = False
        page = int(data[3]) if len(data) > 3 else 0
        update_user_ldata(user_id, 'audio_sort', [])
        update_user_ldata(user_id, 'audio_sort_mode', 'keep')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
        await query.answer("List cleared!")
        await update_user_settings(query, 'audio_sort', edit_mode=page)
    
    # --- INTRO SUB INPUT TRIGGER ---
    elif data[2] == 'introsub':
        handler_dict[user_id] = False
        await query.answer()
        edit_mode = len(data) == 4
        await update_user_settings(query, 'introsub', edit_mode=edit_mode)
        if edit_mode:
            pfunc = partial(set_custom, pre_event=query, key='introsub')
            rfunc = partial(update_user_settings, query, 'introsub')
            await event_handler(client, query, pfunc, rfunc)

    elif data[2] in ['yt_opt', 'usess']:
        await query.answer()
        edit_mode = len(data) == 4
        await update_user_settings(query, data[2], 'universal', edit_mode)
        if not edit_mode: return
        pfunc = partial(set_custom, pre_event=query, key=data[2])
        rfunc = partial(update_user_settings, query, data[2], 'universal')
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] in ['dyt_opt', 'dusess']:
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, data[2][1:], '')
        await update_user_settings(query, data[2][1:], 'universal')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] in ['bot_pm', 'mediainfo', 'save_mode', 'td_mode']:
        handler_dict[user_id] = False
        if data[2] == 'save_mode' and not user_dict.get(data[2], False) and not user_dict.get('ldump'):
            return await query.answer("Set User Dump first to Change Save Msg Mode !", show_alert=True)
        elif data[2] == 'bot_pm' and (config_dict['BOT_PM'] or config_dict['SAFE_MODE']) or data[2] == 'mediainfo' and config_dict['SHOW_MEDIAINFO'] or data[2] == 'td_mode' and not config_dict['USER_TD_MODE']:
            mode_up = "Disabled" if data[2] == 'td_mode' else "Enabled"
            return await query.answer(f"Force {mode_up}! Can't Alter Settings", show_alert=True)
        if data[2] == 'td_mode' and not user_dict.get('user_tds', False):
            return await query.answer("Set UserTD first to Enable User TD Mode !", show_alert=True)
        await query.answer()
        update_user_ldata(user_id, data[2], not user_dict.get(data[2], False))
        if data[2] in ['td_mode']:
            await update_user_settings(query, 'user_tds', 'mirror')
        else:
            await update_user_settings(query, 'universal')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == 'split_size':
        await query.answer()
        edit_mode = len(data) == 4
        await update_user_settings(query, data[2], 'leech', edit_mode)
        if not edit_mode: return
        pfunc = partial(leech_split_size, pre_event=query)
        rfunc = partial(update_user_settings, query, data[2], 'leech')
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] == 'dsplit_size':
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, 'split_size', '')
        await update_user_settings(query, 'split_size', 'leech')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == 'esplits':
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, 'equal_splits', not user_dict.get('equal_splits', False))
        await update_user_settings(query, 'leech')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == 'mgroup':
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, 'media_group', not user_dict.get('media_group', False))
        await update_user_settings(query, 'leech')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] in ['sgofile', 'sstreamtape', 'dgofile', 'dstreamtape']:
        handler_dict[user_id] = False
        ddl_dict = user_dict.get('ddl_servers', {})
        key = data[2][1:]
        mode, api = ddl_dict.get(key, [False, ""])
        if data[2][0] == 's':
            if not mode and api == '':
                return await query.answer('Set API to Enable DDL Server', show_alert=True)
            ddl_dict[key] = [not mode, api]
        elif data[2][0] == 'd':
            ddl_dict[key] = [mode, '']
        await query.answer()
        update_user_ldata(user_id, 'ddl_servers', ddl_dict)
        await update_user_settings(query, key, 'ddl_servers')

    elif data[2] == 'dump_all_toggle':
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, 'dump_all', not user_dict.get('dump_all', False))
        await update_user_settings(query, 'ldump')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)

    elif data[2] == 'sel_dump':
        handler_dict[user_id] = False
        dump_name = data[3]
        current_selection = user_dict.get('dump_selection', [])
        
        all_dumps = list(user_dict.get('ldump', {}).keys())
        if not current_selection and all_dumps:
            current_selection = all_dumps.copy()

        if dump_name in current_selection:
            current_selection.remove(dump_name)
        else:
            current_selection.append(dump_name)
        
        await query.answer()
        update_user_ldata(user_id, 'dump_selection', current_selection)
        await update_user_settings(query, 'ldump')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)

    elif data[2] in ['merge_vid', 'keepsource']:
        handler_dict[user_id] = False
        if data[2] == user_dict.get('merge_vid'):
            mode_up = "Disabled" if data[2] == 'merge_vid' else "Enabled"
            return await query.answer(f"Force {mode_up}! Can't Alter Settings", show_alert=True)
        await query.answer()
        update_user_ldata(user_id, data[2], not user_dict.get(data[2], False))
        await update_user_settings(query, 'universal')              
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
                    
    elif data[2] == 'rcc':
        await query.answer()
        edit_mode = len(data) == 4
        await update_user_settings(query, data[2], 'mirror', edit_mode)
        if not edit_mode: return
        pfunc = partial(add_rclone, pre_event=query)
        rfunc = partial(update_user_settings, query, data[2], 'mirror')
        await event_handler(client, query, pfunc, rfunc, document=True)
    elif data[2] == 'drcc':
        handler_dict[user_id] = False
        if await aiopath.exists(rclone_path):
            await query.answer()
            await aioremove(rclone_path)
            update_user_ldata(user_id, 'rclone', '')
            await update_user_settings(query, 'rcc', 'mirror')
            if DATABASE_URL:
                await DbManger().update_user_doc(user_id, 'rclone')
        else:
            await query.answer("Old Settings", show_alert=True)
            await update_user_settings(query)
    elif data[2] in ['ddl_servers', 'user_tds', 'gofile', 'streamtape']:
        handler_dict[user_id] = False
        await query.answer()
        edit_mode = len(data) == 4
        await update_user_settings(query, data[2], 'mirror' if data[2] in ['ddl_servers', 'user_tds'] else 'ddl_servers', edit_mode)
        if not edit_mode: return
        pfunc = partial(set_custom, pre_event=query, key=data[2])
        rfunc = partial(update_user_settings, query, data[2], 'mirror' if data[2] in ['ddl_servers', 'user_tds'] else "ddl_servers")
        await event_handler(client, query, pfunc, rfunc)
    elif data[2] == 'metadata':
        handler_dict[user_id] = False
        await query.answer()
        await update_user_settings(query, 'metadata')
    
    elif data[2] == 'attachment_settings':
        handler_dict[user_id] = False
        await query.answer()
        await update_user_settings(query, 'attachment_settings')

    elif data[2] in ['lprefix', 'lsuffix', 'lremname', 'lautorename', 'lcaption_replace', 'cut', 'general_metadata', 'video_metadata', 'audio_metadata', 'subtitle_metadata', 'attachment', 'attachment_name', 'subtitle', 'audioremove', 'audiochange', 'audiolanguage', 'audiofile', 'audiobitrate', 'remsub', 'lcaption', 'ldump', 'mprefix', 'msuffix', 'mremname', 'mautorename']:
        handler_dict[user_id] = False
        await query.answer()
        edit_mode = len(data) == 4
        if data[2].endswith('_metadata'):
            return_key = 'metadata'
        elif data[2] in ['attachment', 'attachment_name']:
            return_key = 'attachment_settings'
        elif data[2] == 'ldump':
            return_key = 'ldump'
        elif data[2] in ['cut', 'subtitle', 'introsub', 'audioremove', 'audiochange', 'audiolanguage', 'audiofile', 'audiobitrate', 'remsub']:
            return_key = 'ffmpeg'
        else:
            return_key = 'mirror' if data[2].startswith('m') else 'leech'
            
        await update_user_settings(query, data[2], return_key, edit_mode)
        if not edit_mode: return
        pfunc = partial(set_custom, pre_event=query, key=data[2])
        rfunc = partial(update_user_settings, query, data[2], return_key)
        await event_handler(client, query, pfunc, rfunc)

    elif data[2] in ['dlprefix', 'dlsuffix', 'dlremname', 'dlautorename', 'dlcaption_replace', 'dcut', 'dgeneral_metadata', 'dvideo_metadata', 'daudio_metadata', 'dsubtitle_metadata', 'dattachment', 'dattachment_name', 'dsubtitle', 'daudioremove', 'daudiochange', 'daudiolanguage', 'daudiofile', 'daudiobitrate', 'dremsub', 'dlcaption', 'dldump']:
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, data[2][1:], {} if data[2] == 'dldump' else '')
        if data[2][1:].endswith('_metadata'):
            return_key = 'metadata'
        elif data[2][1:] in ['attachment', 'attachment_name']:
            return_key = 'attachment_settings'
        elif data[2] == 'dldump':
            return_key = 'ldump'
        elif data[2][1:] in ['cut', 'subtitle', 'introsub', 'audioremove', 'audiochange', 'audiolanguage', 'audiofile', 'audiobitrate', 'remsub']:
            return_key = 'ffmpeg'
        else:
            return_key = 'leech'
        await update_user_settings(query, data[2][1:], return_key)
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)

    elif data[2] == 'dmetadata':
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, 'general_metadata', '')
        update_user_ldata(user_id, 'video_metadata', '')
        update_user_ldata(user_id, 'audio_metadata', '')
        update_user_ldata(user_id, 'subtitle_metadata', '')
        await update_user_settings(query, 'metadata')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    
    elif data[2] == 'dattachment_settings':
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, 'attachment', '')
        update_user_ldata(user_id, 'attachment_name', '')
        await update_user_settings(query, 'attachment_settings')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)

    elif data[2] in ['dmprefix', 'dmsuffix', 'dmremname', 'dmautorename', 'duser_tds']:
        handler_dict[user_id] = False
        await query.answer()
        update_user_ldata(user_id, data[2][1:], {} if data[2] == 'duser_tds' else '')
        if data[2] == 'duser_tds':
            update_user_ldata(user_id, 'td_mode', False)
        await update_user_settings(query, data[2][1:], 'mirror')
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
    elif data[2] == 'back':
        handler_dict[user_id] = False
        await query.answer()
        setting = data[3] if len(data) == 4 else None
        await update_user_settings(query, setting)
    elif data[2] == 'reset_all':
        handler_dict[user_id] = False
        await query.answer()
        buttons = ButtonMaker()
        buttons.ibutton('Yes', f"userset {user_id} reset_now y")
        buttons.ibutton('No', f"userset {user_id} reset_now n")
        buttons.ibutton("Close", f"userset {user_id} close", "footer")
        await editMessage(message, 'Do you want to Reset Settings ?', buttons.build_menu(2))
    elif data[2] == 'reset_now':
        handler_dict[user_id] = False
        if data[3] == 'n':
            return await update_user_settings(query)

        # --- NEW SAFE RESET LOGIC ---
        current_id = user_dict.get('current_profile_id', 1)
        
        for key in PROFILE_KEYS:
            if key in user_dict:
                del user_dict[key]
        
        storage_key = f'profile_{current_id}_data'
        if storage_key in user_dict:
            del user_dict[storage_key]

        thumb_path = f"Thumbnails/{user_id}.jpg"
        rclone_path = f"wcl/{user_id}.conf"

        if await aiopath.exists(thumb_path):
            await aioremove(thumb_path)
        if await aiopath.exists(rclone_path):
            await aioremove(rclone_path)

        thumb_backup = f"Thumbnails/{user_id}_p{current_id}.jpg"
        rclone_backup = f"wcl/{user_id}_p{current_id}.conf"

        if await aiopath.exists(thumb_backup):
            await aioremove(thumb_backup)
        if await aiopath.exists(rclone_backup):
            await aioremove(rclone_backup)

        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
            await DbManger().update_user_doc(user_id, 'thumb')
            await DbManger().update_user_doc(user_id, 'rclone')
            
        await query.answer(f"Profile {current_id} Reset Successfully!", show_alert=True)
        await update_user_settings(query)
    elif data[2] == 'user_del':
        user_id = int(data[3])
        await query.answer()
        thumb_path = f'Thumbnails/{user_id}.jpg'
        rclone_path = f'wcl/{user_id}.conf'
        if await aiopath.exists(thumb_path):
            await aioremove(thumb_path)
        if await aiopath.exists(rclone_path):
            await aioremove(rclone_path)
        update_user_ldata(user_id, None, None)
        if DATABASE_URL:
            await DbManger().update_user_data(user_id)
            await DbManger().update_user_doc(user_id, 'thumb')
            await DbManger().update_user_doc(user_id, 'rclone')
        await editMessage(message, f'Data Reset for {user_id}')
    else:
        handler_dict[user_id] = False
        await query.answer()
        await deleteMessage(message.reply_to_message)
        await deleteMessage(message)

async def send_users_settings(client, message):
    text = message.text.split(maxsplit=1)
    userid = text[1] if len(text) > 1 else None
    if userid and not userid.isdigit():
        userid = None
    elif (reply_to := message.reply_to_message) and reply_to.from_user and not reply_to.from_user.is_bot:
        userid = reply_to.from_user.id
    if not userid:
        msg = f'<u><b>Total Users / Chats Data Saved :</b> {len(user_data)}</u>'
        buttons = ButtonMaker()
        buttons.ibutton("Close", f"userset {message.from_user.id} close")
        button = buttons.build_menu(1)
        for user, data in user_data.items():
            msg += f'\n\n<code>{user}</code>:'
            if data:
                for key, value in data.items():
                    if key in ['token', 'time', 'ddl_servers', 'usess']:
                        continue
                    msg += f'\n<b>{key}</b>: <code>{escape(str(value))}</code>'
            else:
                msg += "\nUser's Data is Empty!"
        if len(msg.encode()) > 4000:
            with BytesIO(str.encode(msg)) as ofile:
                ofile.name = 'users_settings.txt'
                await sendFile(message, ofile)
        else:
            await sendMessage(message, msg, button)
    elif int(userid) in user_data:
        msg = f'{(await user_info(userid)).mention(style="html")} ( <code>{userid}</code> ):'
        if data := user_data[int(userid)]:
            buttons = ButtonMaker()
            buttons.ibutton("Delete Data", f"userset {message.from_user.id} user_del {userid}")
            buttons.ibutton("Close", f"userset {message.from_user.id} close")
            button = buttons.build_menu(1)
            for key, value in data.items():
                if key in ['token', 'time', 'ddl_servers', 'usess']:
                    continue
                msg += f'\n<b>{key}</b>: <code>{escape(str(value))}</code>'
        else:
            msg += '\nThis User has not Saved anything.'
            button = None
        await sendMessage(message, msg, button)
    else:
        await sendMessage(message, f'{userid} have not saved anything..')


bot.add_handler(MessageHandler(send_users_settings, filters=command(
    BotCommands.UsersCommand) & CustomFilters.sudo))
bot.add_handler(MessageHandler(user_settings, filters=command(
    BotCommands.UserSetCommand) & CustomFilters.authorized_uset))
bot.add_handler(CallbackQueryHandler(edit_user_settings, filters=regex("^userset")))
