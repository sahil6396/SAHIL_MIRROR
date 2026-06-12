from ast import literal_eval
from asyncio import Event, wait_for, wrap_future, gather
from functools import partial
from pyrogram.filters import regex, user, text
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import CallbackQuery, Message
from time import time

from bot import bot, VID_MODE, LOGGER
from bot.helper.ext_utils.bot_utils import new_thread, get_readable_file_size, get_readable_time, new_task
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.message_utils import sendMessage, editMessage, deleteMessage, sendCustomMsg


class ExtraSelect:
    def __init__(self, executor):
        self.executor = executor
        self.listener = executor.listener
        self.time = time()
        self.event = Event()
        self.message_event = Event()
        self.is_cancel = False
        self.is_delay_input = False
        self.extension: list[str] = [None, None, 'mkv']
        self.__reply = None
        self.stream_map = {}
        self.streams = []

    @new_thread
    async def __event_handler(self):
        pfunc = partial(cb_extra, obj=self)
        handler = self.listener.client.add_handler(
            CallbackQueryHandler(pfunc, filters=regex('^extra') & user(self.listener.user_id)),
            group=-1
        )
        try:
            await wait_for(self.event.wait(), timeout=180)
        except:
            LOGGER.warning(f"ExtraSelect timed out for user {self.listener.user_id}")
            self.event.set()
        finally:
            self.listener.client.remove_handler(*handler)

    @new_thread
    async def message_event_handler(self):
        pfunc = partial(message_handler_delay, obj=self)
        handler = self.listener.client.add_handler(
            MessageHandler(pfunc, filters=text & user(self.listener.user_id)),
            group=0
        )
        try:
            await wait_for(self.message_event.wait(), timeout=60)
        except:
            self.message_event.set()
        finally:
            self.listener.client.remove_handler(*handler)

    async def update_message(self, text: str, buttons):
        if not self.__reply:
            self.__reply = await sendCustomMsg(self.listener.message.chat.id, text, buttons)
        else:
            await editMessage(self.__reply, text, buttons)

    # ---------------- FIX DELAY UI ---------------- #

    async def fix_delay_select(self, streams: list):
        if not self.executor.data:
            self.executor.data = {}

        self.streams = streams
        buttons = ButtonMaker()
        has_audio = False

        for stream in streams:
            if stream.get('codec_type') == 'audio':
                has_audio = True
                index = stream.get('index')
                lang = stream.get('tags', {}).get('language', 'UND').upper()
                codec = stream.get('codec_name', 'UNK').upper()

                display_name = f"Audio ~ {lang} ({codec})"
                self.stream_map[index] = display_name

                current_delay = self.executor.data.get(index)
                if current_delay is not None:
                    display_name += f" [{current_delay}ms]"

                buttons.ibutton(display_name, f'extra fix_delay {index}')

        buttons.ibutton('Done', 'extra fix_delay done')
        buttons.ibutton('Cancel', 'extra cancel')

        if not has_audio:
            text = f'{self.listener.tag}, No Audio Streams Found!\n<code>{self.executor.name}</code>'
        else:
            text = (
                f'{self.listener.tag}, Select Audio to Sync.\n'
                f'<code>{self.executor.name}</code>\n'
                f'<i>Click stream → Enter delay in ms.</i>'
            )

        await self.update_message(text, buttons.build_menu(1))

    async def delay_confirmation(self, idx, val):
        buttons = ButtonMaker()
        buttons.ibutton('🔁 Change Delay', f'extra fix_delay {idx}')
        buttons.ibutton('⬅ Back / Done', 'extra fix_delay back')

        stream_name = self.stream_map.get(idx, f"Stream {idx}")
        filename = self.executor.name

        text = (
            f"✅ <b>Delay Set!</b>\n\n"
            f"<b>File:</b> <code>{filename}</code>\n"
            f"<b>Stream:</b> {stream_name}\n"
            f"<b>Value:</b> <code>{val} ms</code>\n\n"
            f"<i>You can change it or go back to finish.</i>"
        )

        await self.update_message(text, buttons.build_menu(1))

    # ---------------- MAIN ENTRY ---------------- #

    async def get_buttons(self, *args):
        try:
            future = self.__event_handler()
            if extra_mode := getattr(self, f'{self.executor.mode}_select', None):
                await extra_mode(*args)
            await wrap_future(future)
        finally:
            if self.executor:
                self.executor.event.set()

        if self.__reply:
            await deleteMessage(self.__reply)

        if self.is_cancel:
            self.listener.suproc = 'cancelled'
            await self.listener.onUploadError(f'{VID_MODE[self.executor.mode]} stopped by user!')


# ---------------- MESSAGE HANDLER FOR MS INPUT ---------------- #

async def message_handler_delay(_, message: Message, obj: ExtraSelect):
    if not obj.is_delay_input:
        return

    try:
        val = int(message.text.strip())
        idx = obj.executor.data.get('temp_key')
        if idx is not None:
            obj.executor.data[idx] = val
    except ValueError:
        await sendMessage(message, '❌ Invalid format! Send integer like 500 or -500.')
        return

    obj.is_delay_input = False
    obj.message_event.set()
    await deleteMessage(message)

    if idx is not None:
        await obj.delay_confirmation(idx, val)
    else:
        obj.event.set()


# ---------------- CALLBACK HANDLER ---------------- #

@new_task
async def cb_extra(_, query: CallbackQuery, obj: ExtraSelect):
    data = query.data.split()

    if data[1] == 'cancel':
        await query.answer()
        obj.is_cancel = obj.executor.is_cancel = True
        obj.executor.data = None
        obj.event.set()

    elif data[1] == 'fix_delay':
        if data[2] == 'done':
            if obj.executor.data and 'temp_key' in obj.executor.data:
                del obj.executor.data['temp_key']
            await query.answer()
            obj.event.set()

        elif data[2] == 'back':
            await query.answer()

            # Reset input state so we don't reopen ms input page
            obj.is_delay_input = False
            if obj.executor.data and 'temp_key' in obj.executor.data:
                del obj.executor.data['temp_key']

            # Go back to audio list with saved values
            await obj.fix_delay_select(obj.streams)

        else:
            await query.answer()
            idx = int(data[2])
            obj.executor.data['temp_key'] = idx
            obj.is_delay_input = True
            obj.message_event = Event()
            future = obj.message_event_handler()

            buttons = ButtonMaker()
            buttons.ibutton('⬅ Back', 'extra fix_delay back')

            stream_name = obj.stream_map.get(idx, f"Stream {idx}")
            text = (
                f"<b>Selected:</b> {stream_name}\n\n"
                "Send delay in milliseconds:\n"
                "<code>500</code> or <code>-500</code>\n\n"
                "➕ Positive = Audio delayed\n"
                "➖ Negative = Audio earlier"
            )

            await gather(obj.update_message(text, buttons.build_menu(1)), wrap_future(future))
            
    # --------------------------------
    elif data[1] == 'rmstream':
        ddict: dict = obj.executor.data
        if data[2] == 'reset':
            if sdata := ddict['sdata']:
                await query.answer()
                for mapindex in sdata:
                    info = ddict['stream'][mapindex]['info']
                    ddict['stream'][mapindex]['info'] = info.replace('✅ ', '')
                sdata.clear()
                await obj.update_message(*get_streams_buttons(obj))
            else:
                await query.answer('No selected stream to reset!', show_alert=True)
        elif data[2] == 'continue':
            if ddict['sdata']:
                await query.answer()
                obj.event.set()
            else:
                await query.answer('Please select at least one stream!', show_alert=True)
        elif data[2] in ['audio', 'subtitle']:
            await query.answer()
            obj.executor.data['key'] = data[2]
            obj.event.set()
        elif data[2] == 'reverse':
            if ddict['sdata']:
                await query.answer()
                new_sdata = [x for x in ddict['stream'] if x not in ddict['sdata'] and x != 0]
                for key, value in ddict['stream'].items():
                    info = value['info']
                    if key in new_sdata:
                        ddict['stream'][key]['info'] = f'✅ {info}'
                    else:
                        ddict['stream'][key]['info'] = info.replace('✅ ', '')
                ddict['sdata'] = new_sdata
                await obj.update_message(*get_streams_buttons(obj))
            else:
                await query.answer('No selected stream to revers!', show_alert=True)
        else:
            await query.answer()
            mapindex = int(data[2])
            info = ddict['stream'][mapindex]['info']
            if mapindex in ddict['sdata']:
                ddict['sdata'].remove(mapindex)
                ddict['stream'][mapindex]['info'] = info.replace('✅ ', '')
            else:
                ddict['sdata'].append(mapindex)
                ddict['stream'][mapindex]['info'] = f'✅ {info}'
            await obj.update_message(*get_streams_buttons(obj))
    elif data[1] == 'extract':
        if data[2] in ['extension', 'alt']:
            await query.answer()
            extension = obj.extension
            if data[3] == 'ass':
                extension[1] = 'srt'
            elif data[3] == 'srt':
                extension[1] = 'ass'
            elif data[3] == 'aac':
                extension[0] = 'ac3'
            elif data[3] == 'ac3':
                extension[0] = 'eac3'
            elif data[3] == 'eac3':
                extension[0] = 'm4a'
            elif data[3] == 'm4a':
                extension[0] = 'mka'
            elif data[3] == 'mka':
                extension[0] = 'wav'
            elif data[3] == 'wav':
                extension[0] = 'aac'
            elif data[3] == 'mp4':
                extension[2] = 'mkv'
            elif data[3] == 'mkv':
                extension[2] = 'mp4'
            if data[2] == 'alt':
                obj.executor.data['alt_mode'] = not literal_eval(data[3])
            await obj.update_message(*get_streams_buttons(obj))
        else:
            await query.answer()
            obj.executor.data.update({'key': int(data[2]) if data[2].isdigit() else data[2:], 'extension': obj.extension})
            obj.event.set()
