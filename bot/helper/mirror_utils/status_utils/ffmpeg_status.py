from time import time
from bot import LOGGER, VID_MODE
from bot.helper.ext_utils.bot_utils import get_readable_file_size, MirrorStatus, EngineStatus, get_readable_time

class FFMpegStatus:
    def __init__(self, name, size, gid, obj, listener, status):
        self.__name = name
        self.__gid = gid
        self.__size = size
        self.__obj = obj
        self.__listener = listener
        self.__status = status
        self.__time = time()
        self.message = listener.message
        # FIX: Added upload_details so bot_utils can read the mode without crashing
        self.upload_details = listener.upload_details

    def processed_bytes(self):
        return get_readable_file_size(self.__obj.processed_bytes)

    def gid(self):
        return self.__gid

    def progress(self):
        if self.__status != 'direct':
            return self.__obj.percentage
        try:
            progress_raw = self.__obj.processed_bytes / self.__size * 100
        except:
            progress_raw = 0
        return f'{round(progress_raw, 2)}%'

    def speed(self):
        return f'{get_readable_file_size(self.__obj.speed)}/s'

    def name(self):
        return self.__name

    def size(self):
        return get_readable_file_size(self.__size)

    def timeout(self):
        return get_readable_time(180 - (time()-self.__time))

    def eta(self):
        if self.__status != 'direct':
            return get_readable_time(self.__obj.eta)
        try:
            return get_readable_time((self.__size - self.__obj.processed_bytes) / self.__obj.speed)
        except:
            return '~'

    def status(self):
        if self.__status == 'wait':
            return getattr(MirrorStatus, 'STATUS_WAIT', 'Waiting')
            
        mode = self.__obj.mode
        
        if mode in ['vid_vid', 'vid_aud', 'vid_sub']:
            return getattr(MirrorStatus, 'STATUS_MERGING', 'Merging Files')
        if mode == 'convert':
            return getattr(MirrorStatus, 'STATUS_CONVERT', 'Convert')
        if mode == 'compress':
            return getattr(MirrorStatus, 'STATUS_COMPRESS', 'Compress')
        if mode == 'trim':
            return getattr(MirrorStatus, 'STATUS_TRIM', 'Trim')
        if mode == 'watermark':
            return getattr(MirrorStatus, 'STATUS_WATERMARK', 'Watermark')
        if mode == 'rmstream':
            return getattr(MirrorStatus, 'STATUS_RMSTREAM', 'RmStream')
        if mode == 'extract':
            return getattr(MirrorStatus, 'STATUS_EXTRACTING', 'Extract')
            
        return getattr(MirrorStatus, 'STATUS_EXTRACTING', 'Extract')

    def download(self):
        return self

    async def cancel_download(self):
        info = VID_MODE.get(self.__obj.mode, 'Process')
        LOGGER.info('Cancelling %s: %s', info, self.__name)
        if self.__listener.suproc:
            try:
                self.__listener.suproc.kill()
            except:
                pass
        else:
            self.__listener.suproc = 'cancelled'
        await self.__listener.onUploadError(f'{info} stopped by user!', self.__name)

    def eng(self):
        try:
            return EngineStatus().STATUS_SPLIT_MERGE
        except:
            return 'FFmpeg'
