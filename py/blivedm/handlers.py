# -*- coding: utf-8 -*-
import logging
from typing import *

from .clients import ws_base
from .models import web as web_models, open_live as open_models

__all__ = (
    'HandlerInterface',
    'BaseHandler',
)

logger = logging.getLogger('blivedm')

logged_unknown_cmds = {
    'COMBO_SEND',
    'ENTRY_EFFECT',
    'HOT_RANK_CHANGED',
    'HOT_RANK_CHANGED_V2',
    'LIVE',
    'LIVE_INTERACTIVE_GAME',
    'NOTICE_MSG',
    'ONLINE_RANK_COUNT',
    'ONLINE_RANK_TOP3',
    'ONLINE_RANK_V2',
    'PK_BATTLE_END',
    'PK_BATTLE_FINAL_PROCESS',
    'PK_BATTLE_PROCESS',
    'PK_BATTLE_PROCESS_NEW',
    'PK_BATTLE_SETTLE',
    'PK_BATTLE_SETTLE_USER',
    'PK_BATTLE_SETTLE_V2',
    'PREPARING',
    'ROOM_REAL_TIME_MESSAGE_UPDATE',
    'STOP_LIVE_ROOM_LIST',
    'SUPER_CHAT_MESSAGE_JPN',
    'USER_TOAST_MSG',
    'WIDGET_BANNER',
}
"""Unknown cmds that have already been logged"""


class HandlerInterface:
    """
    Live message handler interface
    """

    def handle(self, client: ws_base.WebSocketClientBase, command: dict):
        raise NotImplementedError

    def on_client_stopped(self, client: ws_base.WebSocketClientBase, exception: Optional[Exception]):
        """
        Called when the client stops. Can close or restart here.
        """


def _make_msg_callback(method_name, message_cls):
    def callback(self: 'BaseHandler', client: ws_base.WebSocketClientBase, command: dict):
        method = getattr(self, method_name)
        return method(client, message_cls.from_command(command['data']))
    return callback


class BaseHandler(HandlerInterface):
    """
    A simple message handler implementation with message dispatch and message type conversion.
    Inherit and override _on_xxx methods to implement your own handler.
    """

    def __danmu_msg_callback(self, client: ws_base.WebSocketClientBase, command: dict):
        return self._on_danmaku(client, web_models.DanmakuMessage.from_command(command['info']))

    _CMD_CALLBACK_DICT: Dict[
        str,
        Optional[Callable[
            ['BaseHandler', ws_base.WebSocketClientBase, dict],
            Any
        ]]
    ]
    """cmd -> processing callback"""
    _CMD_CALLBACK_DICT = {
        # Received heartbeat packet, this is a blivedm-created message, original heartbeat format is different
        '_HEARTBEAT': _make_msg_callback('_on_heartbeat', web_models.HeartbeatMessage),
        # Danmaku (bullet comment)
        # go-common\app\service\live\live-dm\service\v1\send.go
        'DANMU_MSG': __danmu_msg_callback,
        # Gift
        'SEND_GIFT': _make_msg_callback('_on_gift', web_models.GiftMessage),
        # Guard purchase (captain)
        'GUARD_BUY': _make_msg_callback('_on_buy_guard', web_models.GuardBuyMessage),
        # Another guard purchase message
        'USER_TOAST_MSG_V2': _make_msg_callback('_on_user_toast_v2', web_models.UserToastV2Message),
        # Super chat
        'SUPER_CHAT_MESSAGE': _make_msg_callback('_on_super_chat', web_models.SuperChatMessage),
        # Delete super chat
        'SUPER_CHAT_MESSAGE_DELETE': _make_msg_callback('_on_super_chat_delete', web_models.SuperChatDeleteMessage),
        # Interactive messages: enter room, follow streamer, etc.
        'INTERACT_WORD': _make_msg_callback('_on_interact_word', web_models.InteractWordMessage),

        #
        # Open platform messages
        #

        # Danmaku
        'LIVE_OPEN_PLATFORM_DM': _make_msg_callback('_on_open_live_danmaku', open_models.DanmakuMessage),
        # Gift
        'LIVE_OPEN_PLATFORM_SEND_GIFT': _make_msg_callback('_on_open_live_gift', open_models.GiftMessage),
        # Guard purchase
        'LIVE_OPEN_PLATFORM_GUARD': _make_msg_callback('_on_open_live_buy_guard', open_models.GuardBuyMessage),
        # Super chat
        'LIVE_OPEN_PLATFORM_SUPER_CHAT': _make_msg_callback('_on_open_live_super_chat', open_models.SuperChatMessage),
        # Delete super chat
        'LIVE_OPEN_PLATFORM_SUPER_CHAT_DEL': _make_msg_callback(
            '_on_open_live_super_chat_delete', open_models.SuperChatDeleteMessage
        ),
        # Like
        'LIVE_OPEN_PLATFORM_LIKE': _make_msg_callback('_on_open_live_like', open_models.LikeMessage),
        # Enter room
        'LIVE_OPEN_PLATFORM_LIVE_ROOM_ENTER': _make_msg_callback('_on_open_live_enter_room', open_models.RoomEnterMessage),
        # Start streaming
        'LIVE_OPEN_PLATFORM_LIVE_START': _make_msg_callback('_on_open_live_start_live', open_models.LiveStartMessage),
        # End streaming
        'LIVE_OPEN_PLATFORM_LIVE_END': _make_msg_callback('_on_open_live_end_live', open_models.LiveEndMessage),
    }

    def handle(self, client: ws_base.WebSocketClientBase, command: dict):
        cmd = command.get('cmd', '')
        pos = cmd.find(':')  # Bilibili danmaku upgrade added parameters on 2019-5-29
        if pos != -1:
            cmd = cmd[:pos]

        if cmd not in self._CMD_CALLBACK_DICT:
            # Only log unknown cmds the first time they are encountered
            if cmd not in logged_unknown_cmds:
                logger.warning('room=%d unknown cmd=%s, command=%s', client.room_id, cmd, command)
                logged_unknown_cmds.add(cmd)
            return

        callback = self._CMD_CALLBACK_DICT[cmd]
        if callback is not None:
            callback(self, client, command)

    def _on_heartbeat(self, client: ws_base.WebSocketClientBase, message: web_models.HeartbeatMessage):
        """Received heartbeat packet"""

    def _on_danmaku(self, client: ws_base.WebSocketClientBase, message: web_models.DanmakuMessage):
        """Danmaku (bullet comment)"""

    def _on_gift(self, client: ws_base.WebSocketClientBase, message: web_models.GiftMessage):
        """Gift"""

    def _on_buy_guard(self, client: ws_base.WebSocketClientBase, message: web_models.GuardBuyMessage):
        """Guard purchase (captain)"""

    def _on_user_toast_v2(self, client: ws_base.WebSocketClientBase, message: web_models.UserToastV2Message):
        """Another guard purchase message"""

    def _on_super_chat(self, client: ws_base.WebSocketClientBase, message: web_models.SuperChatMessage):
        """Super chat"""

    def _on_super_chat_delete(self, client: ws_base.WebSocketClientBase, message: web_models.SuperChatDeleteMessage):
        """Delete super chat"""

    def _on_interact_word(self, client: ws_base.WebSocketClientBase, message: web_models.InteractWordMessage):
        """Interactive messages: enter room, follow streamer, etc."""

    #
    # Open platform messages
    #

    def _on_open_live_danmaku(self, client: ws_base.WebSocketClientBase, message: open_models.DanmakuMessage):
        """Danmaku"""

    def _on_open_live_gift(self, client: ws_base.WebSocketClientBase, message: open_models.GiftMessage):
        """Gift"""

    def _on_open_live_buy_guard(self, client: ws_base.WebSocketClientBase, message: open_models.GuardBuyMessage):
        """Guard purchase"""

    def _on_open_live_super_chat(self, client: ws_base.WebSocketClientBase, message: open_models.SuperChatMessage):
        """Super chat"""

    def _on_open_live_super_chat_delete(
        self, client: ws_base.WebSocketClientBase, message: open_models.SuperChatDeleteMessage
    ):
        """Delete super chat"""

    def _on_open_live_like(self, client: ws_base.WebSocketClientBase, message: open_models.LikeMessage):
        """Like"""

    def _on_open_live_enter_room(self, client: ws_base.WebSocketClientBase, message: open_models.RoomEnterMessage):
        """Enter room"""

    def _on_open_live_start_live(self, client: ws_base.WebSocketClientBase, message: open_models.LiveStartMessage):
        """Start streaming"""

    def _on_open_live_end_live(self, client: ws_base.WebSocketClientBase, message: open_models.LiveEndMessage):
        """End streaming"""
