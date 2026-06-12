from aiofiles.os import path as aiopath, makedirs
from asyncio import Event, wait_for, wrap_future, gather
from functools import partial
from os import path as ospath
from PIL import Image
from pyrogram import Client
from pyrogram.filters import regex, user, text, photo, document
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import Message, CallbackQuery
from re import match as re_match
from time import time

from bot import config_dict, VID_MODE, LOGGER
from bot.helper.ext_utils.bot_utils import new_task, new_thread, sync_to_async, is_media, get_readable_time
from bot.helper.ext_utils.fs_utils import clean_target
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.message_utils import sendMessage, editMessage, deleteMessage, sendCustomMsg


class SelectMode():
    def __init__(self, listener, isLink=False):
        self.listener = listener
        self._isLink = isLink
        self.__time = time()
        self.__reply = None
        self.is_rename = False
        self.mode = ''
        self.extra_data = {}
        self.newname = ''
        self.event = Event()
        self.message_event = Event()
        self.is_cancelled = False

    @new_thread
    async def __event_handler(self):
        pfunc = partial(cb_vidtools, obj=self)
        handler = self.listener.client.add_handler(CallbackQueryHandler(pfunc, filters=regex('^vidtool') & user(self.listener.user_id)), group=-1)
        try:
            await wait_for(self.event.wait(), timeout=60)
        except:
            LOGGER.warning(f"VidTools selection timed out for user {self.listener.user_id}")
            self.mode = 'Task has been cancelled, time out!'
            self.is_cancelled = True
            self.event.set()
        finally:
            self.listener.client.remove_handler(*handler)

    @new_thread
    async def message_event_handler(self, is_wm=None):
        pfunc = partial(message_handler, obj=self)
        # Group 2 for Pre-download inputs
        handler = self.listener.client.add_handler(MessageHandler(pfunc, filters=(document | photo) if is_wm else text & user(self.listener.user_id)), group=2)
        try:
            await wait_for(self.message_event.wait(), timeout=60)
        except:
            self.message_event.set()
        finally:
            self.listener.client.remove_handler(*handler)

    async def __send_message(self, text: str, message: Message, buttons):
        if not self.__reply:
            try:
                self.__reply = await sendCustomMsg(message.chat.id, text, buttons)
                LOGGER.info(f"VidTools menu sent to chat {message.chat.id}")
            except Exception as e:
                LOGGER.error(f"Failed to send VidTools menu: {e}")
                self.event.set() 
        else:
            await editMessage(self.__reply, text, buttons)

    def __captions(self, mode: str=None):
        msg = '<b>VIDEOS TOOL SETTINGS</b>'
        msg += f'\nMode: <b>{VID_MODE.get(self.mode, "")}</b>'
        msg += f'\nName: <b>{self.newname or "Default"}</b>'
        
        if self.mode == 'trim' and self.extra_data:
            msg += f'\nTrim Duration: <b>{self.extra_data.get("start_time")} - {self.extra_data.get("end_time")}</b>'
        
        if self.mode == 'watermark':
            msg += f'\nWM Position: <b>{self.extra_data.get("wmposition", "Default")}</b>'
            msg += f'\nWM Size: <b>{self.extra_data.get("wmsize", "Default")}</b>'
        
        if self.mode in ('compress', 'watermark') or self.extra_data.get('hardsub'):
             msg += f'\nQuality: <b>{self.extra_data.get("quality", "Default")}</b>'

        if self.extra_data.get('hardsub'):
            msg += f'\nHardSub: <b>Enabled</b>'
            if sub := self.extra_data.get('subfile'):
                msg += f'\nSub File: <b>{ospath.basename(sub)}</b>'

        if mode == 'rename':
            msg += '\n\n<i>Send valid name with extension...</i>'
        elif mode == 'watermark':
            msg += '\n\n<i>Send valid image to set as watermark...</i>'
        elif mode == 'subfile':
            msg += '\n\n<i>Send valid subtitle file (.srt/.ass)...</i>'
        elif mode == 'wmsize':
            msg += '\n\n<i>Choose watermark size</i>'
        elif mode == 'trim':
            msg += '\n\n<i>Send valid trim duration <b>hh:mm:ss hh:mm:ss</b></i>'
            
        msg += f'\n\n<i>Time Out: {get_readable_time(60 - (time()-self.__time))}</i>'
        return msg

    async def list_buttons(self, mode: str=None):
        buttons = ButtonMaker()
        if not mode:
            for key, value in VID_MODE.items():
                buttons.ibutton(f"{'✅ ' if self.mode == key else ''} {value}", f'vidtool {key}')
            buttons.ibutton('Rename', 'vidtool rename', 'header')
            buttons.ibutton('Cancel', 'vidtool cancel', 'footer')
            if self.mode:
                buttons.ibutton('Done', 'vidtool done', 'footer')
            
            if self.mode in ('vid_sub', 'watermark'):
                hardsub = self.extra_data.get('hardsub')
                buttons.ibutton(f"{'✅ ' if hardsub else ''}Hardsub", 'vidtool hardsub', 'header')
                if hardsub:
                    if self.mode == 'watermark':
                        buttons.ibutton(f"{'✅ ' if await aiopath.exists(self.extra_data.get('subfile', '')) else ''}Sub File", 'vidtool subfile', 'header')
                    buttons.ibutton('Font Style', 'vidtool fontstyle', 'header')

            if self.mode in ('compress', 'watermark') or self.extra_data.get('hardsub'):
                buttons.ibutton('Quality', 'vidtool quality', 'header')
            if self.mode == 'watermark':
                buttons.ibutton('Popup', 'vidtool popupwm', 'header')

        else:
            if mode == 'wmsize':
                for btn in [5, 10, 15, 20, 25, 30]:
                    buttons.ibutton(str(btn), f'vidtool wmsize {btn}')
            elif mode == 'wmposition':
                positions = {
                    '5:5': 'Top Left', 'main_w-overlay_w-5:5': 'Top Right',
                    '5:main_h-overlay_h-5': 'Bottom Left', 'main_w-overlay_w-5:main_h-overlay_h-5': 'Bottom Right'
                }
                for key, value in positions.items():
                    buttons.ibutton(f"{'✅ ' if self.extra_data.get('wmposition') == key else ''}{value}", f'vidtool wmposition {key}')
            elif mode == 'quality':
                for key in ['1080p', '720p', '540p', '480p', '360p']:
                    buttons.ibutton(f"{'✅ ' if self.extra_data.get('quality') == key else ''}{key}", f'vidtool quality {key}')
            elif mode == 'popupwm':
                buttons.ibutton('WM Position', 'vidtool wmposition')
                buttons.ibutton('WM Size', 'vidtool wmsize')
            else:
                buttons.ibutton('<<', 'vidtool back', 'footer')
                
        await self.__send_message(self.__captions(mode), self.listener.message, buttons.build_menu(2))

    async def get_buttons(self):
        future = self.__event_handler()
        await self.list_buttons()
        await wrap_future(future)
        if self.is_cancelled:
            if self.__reply:
                 await editMessage(self.__reply, self.mode)
            return
        if self.__reply:
            await deleteMessage(self.__reply)
        return [self.mode, self.newname, self.extra_data]


async def message_handler(_, message: Message, obj: SelectMode):
    data = None
    if obj.is_rename:
        obj.newname = message.text.strip()
        obj.is_rename = False
    elif obj.mode == 'watermark' and (media := is_media(message)):
        if message.document and 'image' not in getattr(media, 'mime_type', 'None'):
            await sendMessage(message, 'Only image document allowed!')
            return
        if not await aiopath.exists('watermark'):
            await makedirs('watermark')
        photo_dir = await message.download()
        await sync_to_async(Image.open(photo_dir).convert('RGB').save, ospath.join('watermark', f'{obj.listener.user_id}.png'), 'PNG')
        await clean_target(photo_dir)
        data = 'wmsize'
    elif obj.mode == 'trim':
        match = re_match(r'(\d{1,2}:\d{1,2}:\d{1,2})\s(\d{1,2}:\d{1,2}:\d{1,2})', message.text.strip())
        if match:
            obj.extra_data.update({'start_time': match.group(1), 'end_time': match.group(2)})
        else:
            await sendMessage(message, 'Invalid trim duration format! Use: hh:mm:ss hh:mm:ss')
            return
    elif is_media(message) and message.document:
         if message.document.file_name.endswith(('.srt', '.ass')):
            path = await message.download()
            obj.extra_data['subfile'] = path
         else:
            await sendMessage(message, 'Invalid subtitle format!')
            return

    obj.message_event.set()
    await obj.list_buttons(data)
    await deleteMessage(message)


@new_task
async def cb_vidtools(_, query: CallbackQuery, obj: SelectMode):
    data = query.data.split()
    if data[1] in config_dict.get('DISABLE_VIDTOOLS', []):
        await query.answer(f'{VID_MODE[data[1]]} has been disabled!', True)
        return
    await query.answer()
    if data[1] == obj.mode:
        return
        
    if data[1] == 'done':
        obj.event.set()
    elif data[1] == 'back':
        obj.message_event.set()
        await obj.list_buttons()
    elif data[1] == 'cancel':
        obj.mode = 'Task has been cancelled!'
        obj.is_cancelled = True
        obj.event.set()
    elif data[1] in ['wmsize', 'wmposition', 'quality']:
        if len(data) == 3:
            obj.extra_data[data[1]] = data[2]
            wmdata = 'wmposition' if data[1] == 'wmsize' else 'popupwm' if data[1] == 'wmposition' else None
            await obj.list_buttons(wmdata)
        else:
             await obj.list_buttons(data[1])
    elif data[1] == 'popupwm':
        await obj.list_buttons('popupwm')
    elif data[1] == 'hardsub':
        obj.extra_data['hardsub'] = not obj.extra_data.get('hardsub')
        await obj.list_buttons()
    elif data[1] == 'subfile':
        obj.message_event = Event()
        future = obj.message_event_handler('subfile')
        await gather(obj._send_message('Send valid subtitle file (srt/ass). Timeout: 60s', obj.listener.message, None), wrap_future(future))
    else:
        if data[1] == 'rename':
            obj.is_rename = True
        else:
            obj.mode = data[1]
            obj.extra_data = {}
            
        if data[1] in ['watermark', 'rename', 'trim']:
            obj.message_event = Event()
            future = obj.message_event_handler(data[1] == 'watermark')
            await obj.list_buttons(data[1])
            await wrap_future(future)
            return
            
        await obj.list_buttons()
