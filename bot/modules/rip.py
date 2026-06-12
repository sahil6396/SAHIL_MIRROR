import os
import re
import asyncio
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.filters import command, regex
from pyrogram import filters
from pyrogram.types import ForceReply
from asyncio.subprocess import PIPE
from asyncio import create_subprocess_exec
import time

from bot import bot, LOGGER, DOWNLOAD_DIR
from bot.helper.telegram_helper.message_utils import sendMessage, editMessage
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.telegram_helper.filters import CustomFilters

# Store active rip sessions
rip_sessions = {}

@new_task
async def rip_init(_, message):
    user_id = message.from_user.id
    text = message.text.split(maxsplit=1)
    
    if len(text) == 1:
        await sendMessage(message, "⚠️ **Usage:** `/rip {link} -n {filename}`")
        return

    # Parse Link and Name
    args = text[1].split('-n')
    link = args[0].strip()
    filename = args[1].strip() if len(args) > 1 else "Ripped_Video"
    
    # Initialize Session
    rip_sessions[user_id] = {
        'link': link,
        'name': filename,
        'keys': [],
        'video': 'best',
        'audio': 'best',
        'subs': 'all',
        'message': message
    }

    # Step 1: Ask for Keys
    buttons = ButtonMaker()
    buttons.ibutton("0 Keys (No DRM)", f"rip_{user_id}_keys_0")
    buttons.ibutton("1 Key", f"rip_{user_id}_keys_1")
    buttons.ibutton("2 Keys", f"rip_{user_id}_keys_2")
    buttons.ibutton("3 Keys", f"rip_{user_id}_keys_3")
    
    await sendMessage(message, f"🎬 **Rip Setup: {filename}**\n\nHow many DRM Keys are required?", buttons.build_menu(2))

@new_task
async def rip_callback(_, query):
    data = query.data.split('_')
    user_id = int(data[1])
    action = data[2]
    
    if query.from_user.id != user_id:
        await query.answer("This is not your task!", show_alert=True)
        return
        
    session = rip_sessions.get(user_id)
    if not session:
        await query.answer("Session expired. Send /rip again.", show_alert=True)
        return

    # --- KEYS SELECTION ---
    if action == "keys":
        key_count = int(data[3])
        if key_count == 0:
            await build_quality_menu(query.message, user_id, session)
        else:
            session['expected_keys'] = key_count
            msg = await query.message.edit(f"🔑 **Please REPLY to this message** with your {key_count} keys.\n\nFormat: `KID:KEY` (separate multiple keys with a space or new line).", reply_markup=ForceReply(selective=True))
            session['reply_msg_id'] = msg.id

    # --- VIDEO SELECTION ---
    elif action == "vid":
        session['video'] = data[3]
        await build_quality_menu(query.message, user_id, session)

    # --- AUDIO SELECTION ---
    elif action == "aud":
        session['audio'] = data[3]
        await build_quality_menu(query.message, user_id, session)

    # --- SUBTITLE SELECTION ---
    elif action == "sub":
        session['subs'] = data[3]
        await build_quality_menu(query.message, user_id, session)

    # --- EXECUTE RIP ---
    elif action == "start":
        await query.message.edit("🚀 **Initializing Rip Engine...**")
        await execute_rip(_, user_id)

@new_task
async def key_listener(_, message):
    user_id = message.from_user.id
    session = rip_sessions.get(user_id)
    
    if session and message.reply_to_message and message.reply_to_message.id == session.get('reply_msg_id'):
        keys = re.findall(r'[a-fA-F0-9]{32}:[a-fA-F0-9]{32}', message.text)
        if len(keys) > 0:
            session['keys'] = keys
            try:
                await message.reply_to_message.delete()
            except: pass
            status = await sendMessage(message, "✅ **Keys saved!** Loading menu...")
            await build_quality_menu(status, user_id, session)
        else:
            await sendMessage(message, "❌ **Invalid Key Format!** Must be `KID:KEY`. Try again.")

async def build_quality_menu(message, user_id, session):
    buttons = ButtonMaker()
    v, a, s = session['video'], session['audio'], session['subs']

    # Video Row
    buttons.ibutton(f"Video: Best {'💚' if v == 'best' else ''}", f"rip_{user_id}_vid_best")
    buttons.ibutton(f"1080p {'💚' if v == '1080' else ''}", f"rip_{user_id}_vid_1080")
    buttons.ibutton(f"720p {'💚' if v == '720' else ''}", f"rip_{user_id}_vid_720")

    # Audio Row
    buttons.ibutton(f"Audio: Best {'💚' if a == 'best' else ''}", f"rip_{user_id}_aud_best")
    buttons.ibutton(f"All Audio {'💚' if a == 'all' else ''}", f"rip_{user_id}_aud_all")

    # Sub Row
    buttons.ibutton(f"Subs: All {'💚' if s == 'all' else ''}", f"rip_{user_id}_sub_all")
    buttons.ibutton(f"No Subs {'💚' if s == 'none' else ''}", f"rip_{user_id}_sub_none")

    # Start Button
    buttons.ibutton("🚀 START RIP 🚀", f"rip_{user_id}_start", 'footer')

    msg_text = f"⚙️ **Configure Rip: {session['name']}**\n\n🔑 Keys Loaded: {len(session['keys'])}\nSelect your preferences, then click Start."
    await editMessage(message, msg_text, buttons.build_menu(3))


async def execute_rip(client, user_id):
    # LAZY IMPORT TO PREVENT CIRCULAR IMPORTS!
    from bot.helper.listeners.tasks_listener import MirrorLeechListener
    
    session = rip_sessions.pop(user_id)
    url = session['link']
    name = session['name']
    
    dl_dir = f"{DOWNLOAD_DIR}{session['message'].id}"
    os.makedirs(dl_dir, exist_ok=True)

    status_msg = await sendMessage(session['message'], f"📥 **Starting Download:** `{name}`\n\n_Reading stream data..._")

    cmd = ['N_m3u8DL-RE', url, '--save-dir', dl_dir, '--save-name', name, '--mp4-real-time-decryption']

    if session['video'] == 'best': cmd.extend(['--select-video', 'best'])
    else: cmd.extend(['--select-video', f"res='*{session['video']}*'"])
    
    if session['audio'] == 'best': cmd.extend(['--select-audio', 'best'])
    else: cmd.extend(['--select-audio', 'all'])
    
    if session['subs'] == 'all': cmd.extend(['--select-subtitle', 'all'])
    else: cmd.extend(['--drop-subtitle'])

    for key in session['keys']:
        cmd.extend(['--key', key])

    LOGGER.info(f"Running Rip: {' '.join(cmd)}")

    try:
        process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        
        last_update = time.time()
        while True:
            line = await process.stdout.readline()
            if not line: break
            line = line.decode('utf-8', errors='ignore').strip()
            
            match = re.search(r'(\d+\.\d+)%', line)
            if match:
                percent = match.group(1)
                if time.time() - last_update > 5:
                    await editMessage(status_msg, f"📥 **Ripping:** `{name}`\n\n⚡ **Progress:** {percent}%\n⏳ _Downloading segments..._")
                    last_update = time.time()

        await process.wait()
        
        if process.returncode == 0:
            await editMessage(status_msg, "✅ **Rip Complete! Muxing and Uploading to GDrive...**")
            listener = MirrorLeechListener(session['message'], isLeech=False, upPath='gd')
            await listener.onDownloadComplete()
            
        else:
            stderr = await process.stderr.read()
            await editMessage(status_msg, f"❌ **Rip Failed!**\n`{stderr.decode('utf-8', errors='ignore').strip()[-200:]}`")
            
    except Exception as e:
        await editMessage(status_msg, f"❌ **Fatal Error:** `{e}`")

# Register Handlers
bot.add_handler(MessageHandler(rip_init, filters=command(BotCommands.RipCommand) & CustomFilters.authorized & ~CustomFilters.blacklisted))
bot.add_handler(CallbackQueryHandler(rip_callback, filters=regex(r"^rip_")))
bot.add_handler(MessageHandler(key_listener, filters=filters.reply & CustomFilters.authorized & ~CustomFilters.blacklisted))
    
