import requests
from time import time, monotonic
from datetime import datetime
from sys import executable
from os import execl as osexecl
from asyncio import create_subprocess_exec, gather, run as asyrun, sleep, create_task
from uuid import uuid4
from base64 import b64decode
from importlib import import_module, reload

from random import choice
from requests import get as rget
from pytz import timezone
from bs4 import BeautifulSoup
from signal import signal, SIGINT
from aiofiles.os import path as aiopath, remove as aioremove
from aiofiles import open as aiopen
from pyrogram import idle
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.filters import command, private, regex, new_chat_members, left_chat_member
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot import bot, user, bot_name, config_dict, user_data, botStartTime, LOGGER, Interval, DATABASE_URL, QbInterval, INCOMPLETE_TASK_NOTIFIER, scheduler, download_dict, OWNER_ID
from bot.version import get_version
from .helper.ext_utils.fs_utils import start_cleanup, clean_all, exit_clean_up, clean_target
from .helper.ext_utils.bot_utils import get_readable_time, cmd_exec, sync_to_async, new_task, set_commands, update_user_ldata, get_stats
from .helper.ext_utils.db_handler import DbManger
from .helper.telegram_helper.bot_commands import BotCommands
from .helper.telegram_helper.message_utils import sendMessage, editMessage, editReplyMarkup, sendFile, deleteMessage, delete_all_messages
from .helper.telegram_helper.filters import CustomFilters
from .helper.telegram_helper.button_build import ButtonMaker
from .helper.listeners.aria2_listener import start_aria2_listener
from .helper.themes import BotTheme
from .modules import authorize, clone, gd_count, gd_delete, gd_list, cancel_mirror, mirror_leech, status, torrent_search, torrent_select, ytdlp, \
                     rss, shell, eval, users_settings, bot_settings, speedtest, save_msg, images, imdb, anilist, mediainfo, mydramalist, gen_pyro_sess, \
                     gd_clean, broadcast, category_select, resume_task

# Global variable to track restart state
IN_RESTART_MODE = False

async def stats(client, message):
    msg, btns = await get_stats(message)
    await sendMessage(message, msg, btns, photo='IMAGES')

@new_task
async def start(client, message):
    buttons = ButtonMaker()
    buttons.ubutton(BotTheme('ST_BN1_NAME'), BotTheme('ST_BN1_URL'))
    buttons.ubutton(BotTheme('ST_BN2_NAME'), BotTheme('ST_BN2_URL'))
    reply_markup = buttons.build_menu(2)
    if len(message.command) > 1 and message.command[1] == "wzmlx":
        await deleteMessage(message)
    elif len(message.command) > 1 and config_dict['TOKEN_TIMEOUT']:
        userid = message.from_user.id
        encrypted_url = message.command[1]
        input_token, pre_uid = (b64decode(encrypted_url.encode()).decode()).split('&&')
        if int(pre_uid) != userid:
            return await sendMessage(message, BotTheme('OWN_TOKEN_GENERATE'))
        data = user_data.get(userid, {})
        if 'token' not in data or data['token'] != input_token:
            return await sendMessage(message, BotTheme('USED_TOKEN'))
        elif config_dict['LOGIN_PASS'] is not None and data['token'] == config_dict['LOGIN_PASS']:
            return await sendMessage(message, BotTheme('LOGGED_PASSWORD'))
        buttons.ibutton(BotTheme('ACTIVATE_BUTTON'), f'pass {input_token}', 'header')
        reply_markup = buttons.build_menu(2)
        msg = BotTheme('TOKEN_MSG', token=input_token, validity=get_readable_time(int(config_dict["TOKEN_TIMEOUT"])))
        return await sendMessage(message, msg, reply_markup)
    elif await CustomFilters.authorized(client, message):
        start_string = BotTheme('ST_MSG', help_command=f"/{BotCommands.HelpCommand}")
        await sendMessage(message, start_string, reply_markup, photo='IMAGES')
    elif config_dict['BOT_PM']:
        await sendMessage(message, BotTheme('ST_BOTPM'), reply_markup, photo='IMAGES')
    else:
        await sendMessage(message, BotTheme('ST_UNAUTH'), reply_markup, photo='IMAGES')
    await DbManger().update_pm_users(message.from_user.id)


async def token_callback(_, query):
    user_id = query.from_user.id
    input_token = query.data.split()[1]
    data = user_data.get(user_id, {})
    if 'token' not in data or data['token'] != input_token:
        return await query.answer('Already Used, Generate New One', show_alert=True)
    update_user_ldata(user_id, 'token', str(uuid4()))
    update_user_ldata(user_id, 'time', time())
    await query.answer('Activated Temporary Token!', show_alert=True)
    kb = query.message.reply_markup.inline_keyboard[1:]
    kb.insert(0, [InlineKeyboardButton(BotTheme('ACTIVATED'), callback_data='pass activated')])
    await editReplyMarkup(query.message, InlineKeyboardMarkup(kb))


async def login(_, message):
    if config_dict['LOGIN_PASS'] is None:
        return
    elif len(message.command) > 1:
        user_id = message.from_user.id
        input_pass = message.command[1]
        if user_data.get(user_id, {}).get('token', '') == config_dict['LOGIN_PASS']:
            return await sendMessage(message, BotTheme('LOGGED_IN'))
        if input_pass != config_dict['LOGIN_PASS']:
            return await sendMessage(message, BotTheme('INVALID_PASS'))
        update_user_ldata(user_id, 'token', config_dict['LOGIN_PASS'])
        return await sendMessage(message, BotTheme('PASS_LOGGED'))
    else:
        await sendMessage(message, BotTheme('LOGIN_USED'))


# --- Restart Logic Start ---

async def restart_bot(message):
    """Execution function to actually restart the bot."""
    # FIX: Use config_dict for global reliability
    config_dict['IS_RESTARTING'] = True
    
    restart_message = await sendMessage(message, BotTheme('RESTARTING'))
    if scheduler.running:
        scheduler.shutdown(wait=False)
    await delete_all_messages()
    for interval in [QbInterval, Interval]:
        if interval:
            interval[0].cancel()
    await sync_to_async(clean_all)
    proc1 = await create_subprocess_exec('pkill', '-9', '-f', 'gunicorn|aria2c|qbittorrent-nox|ffmpeg|rclone')
    proc2 = await create_subprocess_exec('python3', 'update.py')
    await gather(proc1.wait(), proc2.wait())
    async with aiopen(".restartmsg", "w") as f:
        await f.write(f"{restart_message.chat.id}\n{restart_message.id}\n")
    osexecl(executable, executable, "-m", "bot")

async def restart_wait_monitor(message):
    """Background task to wait for queue to empty."""
    msg = await sendMessage(message, f"<i>Restart queued! Waiting for {len(download_dict)} tasks to finish...</i>\n\n<b>New tasks should be ignored.</b>")
    
    while len(download_dict) > 0:
        await sleep(10)
        try:
            # Update message status every 10 seconds
            await editMessage(msg, f"<i>Restart queued! Waiting for {len(download_dict)} tasks to finish...</i>\n\n<b>New tasks should be ignored.</b>")
        except:
            pass
            
    await restart_bot(message)

async def restart_decision_callback(_, query):
    """Callback for restart decision buttons."""
    data = query.data.split()[1]
    user_id = query.from_user.id
    
    # Check authorization (Sudo or Owner)
    if not user_data.get(user_id, {}).get('is_sudo') and user_id != config_dict['OWNER_ID']:
        return await query.answer("You are not authorized!", show_alert=True)

    if data == "now":
        await query.answer("Restarting immediately...")
        await query.message.delete()
        await restart_bot(query.message)
    elif data == "wait":
        config_dict['IS_RESTARTING'] = True # Set flag here too just in case
        await query.answer("Bot will restart after tasks finish.")
        await query.message.delete()
        create_task(restart_wait_monitor(query.message))
    else:
        await query.answer("Restart cancelled.")
        await query.message.delete()

async def restart(client, message):
    """Restart command handler with check for active tasks."""
    if len(download_dict) > 0:
        buttons = ButtonMaker()
        buttons.ibutton('Restart Now', 'restart_decision now')
        buttons.ibutton('Wait for Tasks', 'restart_decision wait')
        buttons.ibutton('Cancel', 'restart_decision cancel')
        
        msg = f"<b>⚠️ Tasks are currently ongoing!</b>\n\nTotal Tasks: <code>{len(download_dict)}</code>\n\nDo you want to force restart or wait?"
        await sendMessage(message, msg, buttons.build_menu(2))
    else:
        await restart_bot(message)

# --- Restart Logic End ---


async def ping(_, message):
    start_time = monotonic()
    reply = await sendMessage(message, BotTheme('PING'))
    end_time = monotonic()
    await editMessage(reply, BotTheme('PING_VALUE', value=int((end_time - start_time) * 1000)))


async def log(_, message):
    buttons = ButtonMaker()
    buttons.ibutton(BotTheme('LOG_DISPLAY_BT'), f'wzmlx {message.from_user.id} logdisplay')
    buttons.ibutton(BotTheme('WEB_PASTE_BT'), f'wzmlx {message.from_user.id} webpaste')
    await sendFile(message, 'log.txt', buttons=buttons.build_menu(1))

async def new_member(_, message):
    buttons = ButtonMaker()
    buttons.ubutton(BotTheme('ST_BN1_NAME'), BotTheme('ST_BN1_URL'))
    buttons.ubutton(BotTheme('ST_BN2_NAME'), BotTheme('ST_BN2_URL'))

    for user in message.new_chat_members:
        try:
            if user.photo:
                image = await bot.download_media(user.photo.big_file_id, file_name=f'./{user.id}.png')
            else:
                image = choice(config_dict['WELCOME_IMAGES']) if config_dict['WELCOME_IMAGES'] else None
        except Exception as e:
            LOGGER.error(f"Error downloading user photo: {e}")
            image = choice(config_dict['WELCOME_IMAGES']) if config_dict['WELCOME_IMAGES'] else None

        try:
            chat = await bot.get_chat(message.chat.id)
            text = f'''
<b>Hello there {user.mention}, welcome to <b>{chat.title}</b> Group. Enjoy the mirror/leech party 😘</b>\n
<b>ID:</b> <code>{user.id}</code>
<b>First Name:</b> {user.first_name}
<b>Last Name:</b> {user.last_name or '~'}
<b>Username:</b> {f'@{user.username}' if user.username else '~'}
<b>Language:</b> {user.language_code.upper() if user.language_code else '~'}
<b>DC ID:</b> {getattr(user, 'dc_id', '~')}
<b>Premium User:</b> {'Yes' if getattr(user, 'is_premium', False) else 'No'}'''

            newmsg = await sendMessage(message, text, buttons.build_menu(2), image)

            if image and isinstance(image, str) and image.endswith(".png") and await aiopath.exists(image):
                await clean_target(image)

            await auto_delete_message(message, newmsg)
        except Exception as e:
            LOGGER.error(f"Failed to greet new member {user.id}: {e}")


async def leave_member(_, message):
    user = message.left_chat_member
    image = choice(config_dict['GOODBYE_IMAGES']) if config_dict.get('GOODBYE_IMAGES') else None

    text = f'Yeah... <b>{user.mention}, don\'t come back here! 😕😕</b>'

    try:
        leavemsg = await sendMessage(message, text, photo=image)
        await gather(
            sendCustomMsg(user.id, 'Yeah u leaved!'),
            auto_delete_message(message, leavemsg)
        )
    except Exception as e:
        LOGGER.error(f"Failed to send leave message for user {user.id}: {e}")

async def search_images():
    if not (query_list := config_dict['IMG_SEARCH']):
        return
    try:
        total_pages = config_dict['IMG_PAGE']
        base_url = "https://www.wallpaperflare.com/search"
        for query in query_list:
            query = query.strip().replace(" ", "+")
            for page in range(1, total_pages + 1):
                url = f"{base_url}?wallpaper={query}&width=1280&height=720&page={page}"
                r = rget(url)
                soup = BeautifulSoup(r.text, "html.parser")
                images = soup.select('img[data-src^="https://c4.wallpaperflare.com/wallpaper"]')
                if len(images) == 0:
                    LOGGER.info("Maybe Site is Blocked on your Server, Add Images Manually !!")
                for img in images:
                    img_url = img['data-src']
                    if img_url not in config_dict['IMAGES']:
                        config_dict['IMAGES'].append(img_url)
        if len(config_dict['IMAGES']) != 0:
            config_dict['STATUS_LIMIT'] = 2
        if DATABASE_URL:
            await DbManger().update_config({'IMAGES': config_dict['IMAGES'], 'STATUS_LIMIT': config_dict['STATUS_LIMIT']})
    except Exception as e:
        LOGGER.error(f"An error occurred: {e}")

@new_task
async def teleimage(client, message):
    IMGBB_API_KEY = "d4cc3d793cb68b2c6cdc2197588e895c"
    reply = message.reply_to_message
    
    if not reply or not reply.media:
        return await sendMessage(message, "Reply to a media to upload it to Cloud.")
    
    if reply.document and reply.document.file_size > 5 * 1024 * 1024:  # 5 MB
        return await sendMessage(message, "File size limit is 5 MB.")
        
    msg = await sendMessage(message, "Processing...")
    
    try:
        downloaded_media = await reply.download()
        
        if not downloaded_media:
            return await editMessage(msg, "Something went wrong during download.")

        def _upload_to_imgbb(path):
            with open(path, "rb") as f:
                return requests.post(
                    "https://api.imgbb.com/1/upload",
                    data={"key": IMGBB_API_KEY},
                    files={"image": f}
                )

        resp = await sync_to_async(_upload_to_imgbb, downloaded_media)
        
        await clean_target(downloaded_media)
        
        if resp.status_code == 200:
            result = resp.json()
            if result["success"]:
                await editMessage(msg, f'{result["data"]["url"]}')
            else:
                await editMessage(msg, "Something went wrong with ImgBB API.")
        else:
            await editMessage(msg, "Failed to upload. Please try again later.")

    except Exception as e:
        await editMessage(msg, f"Error: {str(e)}")
      

async def bot_help(client, message):
    buttons = ButtonMaker()
    user_id = message.from_user.id
    buttons.ibutton(BotTheme('BASIC_BT'), f'wzmlx {user_id} guide basic')
    buttons.ibutton(BotTheme('USER_BT'), f'wzmlx {user_id} guide users')
    buttons.ibutton(BotTheme('MICS_BT'), f'wzmlx {user_id} guide miscs')
    buttons.ibutton(BotTheme('O_S_BT'), f'wzmlx {user_id} guide admin')
    buttons.ibutton(BotTheme('CLOSE_BT'), f'wzmlx {user_id} close')
    await sendMessage(message, BotTheme('HELP_HEADER'), buttons.build_menu(2))


async def restart_notification():
    now = datetime.now(timezone(config_dict['TIMEZONE']))
    
    if await aiopath.isfile(".restartmsg"):
        with open(".restartmsg") as f:
            chat_id, msg_id = map(int, f)
    else:
        chat_id, msg_id = 0, 0

    async def send_incompelete_task_message(cid, msg, reply_markup=None):
        try:
            if msg.startswith("⌬ <b><i>Restarted Successfully!</i></b>"):
                await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=msg, disable_web_page_preview=True, reply_markup=reply_markup)
                await aioremove(".restartmsg")
            else:
                await bot.send_message(chat_id=cid, text=msg, disable_web_page_preview=True, disable_notification=True, reply_markup=reply_markup)
        except Exception as e:
            LOGGER.error(e)

    # --- Premium Check ---
    premium_message = ''
    try:
        if user and user.me.is_premium:
            premium_message = '\n\n<b><blockquotes>ᴘʀᴇᴍɪᴜᴍ ʟᴇᴇᴄʜ ᴇɴᴀʙʟᴇᴅ!</blockquotes></b> 💎'
    except Exception:
        pass
    # ---------------------

    if INCOMPLETE_TASK_NOTIFIER and DATABASE_URL:
        if notifier_dict := await DbManger().get_incomplete_tasks():
            buttons = ButtonMaker()
            buttons.ibutton('Resume Tasks', 'resume yes')
            buttons.ibutton('Clear Tasks', 'resume no')
            reply_markup = buttons.build_menu(2)
            
            for cid, data in notifier_dict.items():
                msg = BotTheme('RESTART_SUCCESS', time=now.strftime('%I:%M:%S %p'), date=now.strftime('%d/%m/%y'), timz=config_dict['TIMEZONE'], version=get_version()) if cid == chat_id else BotTheme('RESTARTED')
                msg += premium_message
                msg += "\n\n⌬ <b><i>Incomplete Tasks!</i></b>"
                
                for tag, links in data.items():
                    msg += f"\n➲ <b>User:</b> {tag}\n┖ <b>Tasks:</b>"
                    for index, link in enumerate(links, start=1):
                        msg_link, source = next(iter(link.items()))
                        await resume_task.set_incomplte_task(cid, msg_link)
                        msg += f" {index}. <a href='{source}'>S</a> ->  <a href='{msg_link}'>L</a> |"
                        
                        if len(msg.encode()) > 4000:
                            await send_incompelete_task_message(cid, msg, reply_markup)
                            msg = ''
                
                if msg:
                    await send_incompelete_task_message(cid, msg, reply_markup)

    # If the restart message hasn't been handled by the task loop above (e.g., no incomplete tasks), handle it here
    if await aiopath.isfile(".restartmsg"):
        try:
            restart_text = BotTheme('RESTART_SUCCESS', time=now.strftime('%I:%M:%S %p'), date=now.strftime('%d/%m/%y'), timz=config_dict['TIMEZONE'], version=get_version())
            restart_text += premium_message
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=restart_text)
        except Exception as e:
            LOGGER.error(e)
        await aioremove(".restartmsg")

    # Notify Auth users who are NOT the restart triggerer
    if user_data:
        for id_ in user_data:
            if user_data[id_].get('is_auth') or user_data[id_].get('is_sudo') or id_ == OWNER_ID:
                if id_ == chat_id:
                    continue
                try:
                    await bot.send_message(chat_id=id_, text=f'<b>Bot Restarted!</b>{premium_message}')
                except Exception:
                    pass


async def log_check():
    if config_dict['LEECH_LOG_ID']:
        for chat_id in config_dict['LEECH_LOG_ID'].split():
            chat_id, *topic_id = chat_id.split(":")
            try:
                try:
                    chat = await bot.get_chat(int(chat_id))
                except Exception:
                    LOGGER.error(f"Not Connected Chat ID : {chat_id}, Make sure the Bot is Added!")
                    continue
                if chat.type == ChatType.CHANNEL:
                    if not (await chat.get_member(bot.me.id)).privileges.can_post_messages:
                        LOGGER.error(f"Not Connected Chat ID : {chat_id}, Make the Bot is Admin in Channel to Connect!")
                        continue
                    if user and not (await chat.get_member(user.me.id)).privileges.can_post_messages:
                        LOGGER.error(f"Not Connected Chat ID : {chat_id}, Make the User is Admin in Channel to Connect!")
                        continue
                elif chat.type == ChatType.SUPERGROUP:
                    if not (await chat.get_member(bot.me.id)).status in [ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR]:
                        LOGGER.error(f"Not Connected Chat ID : {chat_id}, Make the Bot is Admin in Group to Connect!")
                        continue
                    if user and not (await chat.get_member(user.me.id)).status in [ChatMemberStatus.OWNER, ChatMasterStatus.ADMINISTRATOR]:
                        LOGGER.error(f"Not Connected Chat ID : {chat_id}, Make the User is Admin in Group to Connect!")
                        continue
                LOGGER.info(f"Connected Chat ID : {chat_id}")
            except Exception as e:
                LOGGER.error(f"Not Connected Chat ID : {chat_id}, ERROR: {e}")


async def main():
    await gather(start_cleanup(), torrent_search.initiate_search_tools(), restart_notification(), search_images(), set_commands(bot), log_check())
    await sync_to_async(start_aria2_listener, wait=False)

    bot.add_handler(MessageHandler(
        start, filters=command(BotCommands.StartCommand) & private))
    bot.add_handler(CallbackQueryHandler(
        token_callback, filters=regex(r'^pass')))
    bot.add_handler(MessageHandler(
        login, filters=command(BotCommands.LoginCommand) & private))
    bot.add_handler(MessageHandler(log, filters=command(
        BotCommands.LogCommand) & CustomFilters.owner))
    
    # New Handler for Restart Decision
    bot.add_handler(CallbackQueryHandler(restart_decision_callback, filters=regex(r'^restart_decision')))
    
    bot.add_handler(MessageHandler(restart, filters=command(
        BotCommands.RestartCommand) & CustomFilters.sudo))
    bot.add_handler(MessageHandler(ping, filters=command(
        BotCommands.PingCommand) & CustomFilters.authorized & ~CustomFilters.blacklisted))
    bot.add_handler(MessageHandler(bot_help, filters=command(
        BotCommands.HelpCommand) & CustomFilters.authorized & ~CustomFilters.blacklisted))
    bot.add_handler(MessageHandler(stats, filters=command(
        BotCommands.StatsCommand) & CustomFilters.authorized & ~CustomFilters.blacklisted))
    bot.add_handler(MessageHandler(teleimage, filters=command(
        BotCommands.TelegraphCommand) & CustomFilters.authorized))
    bot.add_handler(MessageHandler(new_member, filters=new_chat_members))
    bot.add_handler(MessageHandler(leave_member, filters=left_chat_member))
    LOGGER.info(f"WZML-X Bot [@{bot_name}] Started!")
    if user:
        LOGGER.info(f"WZ's User [@{user.me.username}] Ready!")
    signal(SIGINT, exit_clean_up)

async def stop_signals():
    if user:
        await gather(bot.stop(), user.stop())
    else:
        await bot.stop()


bot_run = bot.loop.run_until_complete
bot_run(main())
bot_run(idle())
bot_run(stop_signals())
