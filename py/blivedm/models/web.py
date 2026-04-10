# -*- coding: utf-8 -*-
import dataclasses
import json
from typing import *

__all__ = (
    'HeartbeatMessage',
    'DanmakuMessage',
    'GiftMessage',
    'GuardBuyMessage',
    'SuperChatMessage',
    'SuperChatDeleteMessage',
)


@dataclasses.dataclass
class HeartbeatMessage:
    """
    Heartbeat message
    """

    popularity: int = 0
    """Popularity value, deprecated"""

    @classmethod
    def from_command(cls, data: dict):
        return cls(
            popularity=data['popularity'],
        )


@dataclasses.dataclass
class DanmakuMessage:
    """
    Danmaku message
    """

    mode: int = 0
    """Danmaku display mode (scrolling, top, bottom)"""
    font_size: int = 0
    """Font size"""
    color: int = 0
    """Color"""
    timestamp: int = 0
    """Timestamp (milliseconds)"""
    rnd: int = 0
    """Random number, called danmaku ID in frontend, possibly for deduplication"""
    uid_crc32: str = ''
    """CRC32 of user ID text"""
    msg_type: int = 0
    """Whether it's a gift danmaku (rhythm storm)"""
    bubble: int = 0
    """Right comment bar bubble"""
    dm_type: int = 0
    """Danmaku type: 0 text, 1 emoji, 2 voice"""
    emoticon_options: Union[dict, str] = ''
    """Emoji parameters"""
    voice_config: Union[dict, str] = ''
    """Voice parameters"""
    mode_info: dict = dataclasses.field(default_factory=dict)
    """Some additional parameters"""

    msg: str = ''
    """Danmaku content"""

    uid: int = 0
    """User ID"""
    uname: str = ''
    """Username"""
    face: str = ''
    """User avatar URL"""
    admin: int = 0
    """Whether room moderator"""
    vip: int = 0
    """Whether monthly VIP (laoye)"""
    svip: int = 0
    """Whether yearly VIP (laoye)"""
    urank: int = 0
    """User identity, used to determine whether formal member, guess non-formal member is 5000, formal member is 10000"""
    mobile_verify: int = 0
    """Whether phone verified"""
    uname_color: str = ''
    """Username color"""

    medal_level: int = 0
    """Medal level"""
    medal_name: str = ''
    """Medal name"""
    runame: str = ''
    """Medal room streamer name"""
    medal_room_id: int = 0
    """Medal room ID"""
    mcolor: int = 0
    """Medal color"""
    special_medal: str = ''
    """Special medal"""

    user_level: int = 0
    """User level"""
    ulevel_color: int = 0
    """User level color"""
    ulevel_rank: str = ''
    """User level rank, '>50000' when >50000"""

    old_title: str = ''
    """Old title"""
    title: str = ''
    """Title"""

    privilege_type: int = 0
    """Guard type: 0 non-guard, 1 governor, 2 admiral, 3 captain"""

    wealth_level: int = 0
    """Glory level"""

    @classmethod
    def from_command(cls, info: list):
        mode_info = info[0][15]
        try:
            face = mode_info['user']['base']['face']
        except (TypeError, KeyError):
            face = ''

        if len(info[3]) != 0:
            medal_level = info[3][0]
            medal_name = info[3][1]
            runame = info[3][2]
            medal_room_id = info[3][3]
            mcolor = info[3][4]
            special_medal = info[3][5]
        else:
            medal_level = 0
            medal_name = ''
            runame = ''
            medal_room_id = 0
            mcolor = 0
            special_medal = 0

        if len(info[5]) != 0:
            old_title = info[5][0]
            title = info[5][1]
        else:
            old_title = ''
            title = ''

        return cls(
            mode=info[0][1],
            font_size=info[0][2],
            color=info[0][3],
            timestamp=info[0][4],
            rnd=info[0][5],
            uid_crc32=info[0][7],
            msg_type=info[0][9],
            bubble=info[0][10],
            dm_type=info[0][12],
            emoticon_options=info[0][13],
            voice_config=info[0][14],
            mode_info=mode_info,

            msg=info[1],

            uid=info[2][0],
            uname=info[2][1],
            face=face,
            admin=info[2][2],
            vip=info[2][3],
            svip=info[2][4],
            urank=info[2][5],
            mobile_verify=info[2][6],
            uname_color=info[2][7],

            medal_level=medal_level,
            medal_name=medal_name,
            runame=runame,
            medal_room_id=medal_room_id,
            mcolor=mcolor,
            special_medal=special_medal,

            user_level=info[4][0],
            ulevel_color=info[4][2],
            ulevel_rank=info[4][3],

            old_title=old_title,
            title=title,

            privilege_type=info[7],

            wealth_level=info[16][0],
        )

    @property
    def emoticon_options_dict(self) -> dict:
        """
        Example:

        ```
        {'bulge_display': 0, 'emoticon_unique': 'official_13', 'height': 60, 'in_player_area': 1, 'is_dynamic': 1,
         'url': 'https://i0.hdslb.com/bfs/live/a98e35996545509188fe4d24bd1a56518ea5af48.png', 'width': 183}
         ```
        """
        if isinstance(self.emoticon_options, dict):
            return self.emoticon_options
        try:
            return json.loads(self.emoticon_options)
        except (json.JSONDecodeError, TypeError):
            return {}

    @property
    def voice_config_dict(self) -> dict:
        """
        Example:

        ```
        {'voice_url': 'https%3A%2F%2Fboss.hdslb.com%2Flive-dm-voice%2Fb5b26e48b556915cbf3312a59d3bb2561627725945.wav
         %3FX-Amz-Algorithm%3DAWS4-HMAC-SHA256%26X-Amz-Credential%3D2663ba902868f12f%252F20210731%252Fshjd%252Fs3%25
         2Faws4_request%26X-Amz-Date%3D20210731T100545Z%26X-Amz-Expires%3D600000%26X-Amz-SignedHeaders%3Dhost%26
         X-Amz-Signature%3D114e7cb5ac91c72e231c26d8ca211e53914722f36309b861a6409ffb20f07ab8',
         'file_format': 'wav', 'text': 'Tang, good afternoon.', 'file_duration': 1}
         ```
        """
        if isinstance(self.voice_config, dict):
            return self.voice_config
        try:
            return json.loads(self.voice_config)
        except (json.JSONDecodeError, TypeError):
            return {}

    @property
    def extra_dict(self) -> dict:
        """
        Example:

        ```
        {'send_from_me': False, 'mode': 0, 'color': 14893055, 'dm_type': 0, 'font_size': 25, 'player_mode': 4,
        'show_player_type': 0, 'content': 'Indeed', 'user_hash': '2904574201', 'emoticon_unique': '', 'bulge_display': 0,
        'recommend_score': 5, 'main_state_dm_color': '', 'objective_state_dm_color': '', 'direction': 0,
        'pk_direction': 0, 'quartet_direction': 0, 'anniversary_crowd': 0, 'yeah_space_type': '', 'yeah_space_url': '',
        'jump_to_url': '', 'space_type': '', 'space_url': '', 'animation': {}, 'emots': None, 'is_audited': False,
        'id_str': '6fa9959ab8feabcd1b337aa5066768334027', 'icon': None, 'show_reply': True, 'reply_mid': 0,
        'reply_uname': '', 'reply_uname_color': '', 'reply_is_mystery': False, 'reply_type_enum': 0, 'hit_combo': 0,
        'esports_jump_url': ''}
        ```
        """
        try:
            extra = self.mode_info['extra']
            if isinstance(extra, dict):
                return extra
            return json.loads(extra)
        except (KeyError, json.JSONDecodeError, TypeError):
            return {}


@dataclasses.dataclass
class GiftMessage:
    """
    Gift message
    """

    gift_name: str = ''
    """Gift name"""
    num: int = 0
    """Quantity"""
    uname: str = ''
    """Username"""
    face: str = ''
    """User avatar URL"""
    guard_level: int = 0
    """Guard level: 0 non-guard, 1 governor, 2 admiral, 3 captain"""
    uid: int = 0
    """User ID"""
    timestamp: int = 0
    """Timestamp"""
    gift_id: int = 0
    """Gift ID"""
    gift_type: int = 0
    """Gift type (unknown)"""
    gift_img_basic: str = ''
    """Icon URL"""
    action: str = ''
    """Observed actions include 'feed', 'give'"""
    price: int = 0
    """Gift unit price in seeds"""
    rnd: str = ''
    """Random number, possibly for deduplication. Sometimes timestamp + dedup ID, sometimes UUID"""
    coin_type: str = ''
    """Seed type: 'silver' or 'gold', 1000 gold seeds = 1 yuan"""
    total_coin: int = 0
    """Total seeds"""
    tid: str = ''
    """Possibly transaction ID, sometimes same as rnd"""
    medal_level: int = 0
    """Medal level"""
    medal_name: str = ''
    """Medal name"""
    medal_room_id: int = 0
    """Medal room ID, 0 when not logged in"""
    medal_ruid: int = 0
    """Medal streamer ID"""

    @classmethod
    def from_command(cls, data: dict):
        medal_info = data.get('medal_info', None)
        if medal_info is not None:
            medal_level = medal_info['medal_level']
            medal_name = medal_info['medal_name']
            medal_room_id = medal_info['anchor_roomid']
            medal_ruid = medal_info['target_id']
        else:
            medal_level = 0
            medal_name = ''
            medal_room_id = 0
            medal_ruid = 0

        return cls(
            gift_name=data['giftName'],
            num=data['num'],
            uname=data['uname'],
            face=data['face'],
            guard_level=data['guard_level'],
            uid=data['uid'],
            timestamp=data['timestamp'],
            gift_id=data['giftId'],
            gift_type=data['giftType'],
            gift_img_basic=data['gift_info']['img_basic'],
            action=data['action'],
            price=data['price'],
            rnd=data['rnd'],
            coin_type=data['coin_type'],
            total_coin=data['total_coin'],
            tid=data['tid'],
            medal_level=medal_level,
            medal_name=medal_name,
            medal_room_id=medal_room_id,
            medal_ruid=medal_ruid,
        )


@dataclasses.dataclass
class GuardBuyMessage:
    """
    Guard purchase message
    """

    uid: int = 0
    """User ID"""
    username: str = ''
    """Username"""
    guard_level: int = 0
    """Guard level: 0 non-guard, 1 governor, 2 admiral, 3 captain"""
    num: int = 0  # Can be understood as gift quantity?
    """Quantity"""
    price: int = 0
    """Unit price in gold seeds"""
    gift_id: int = 0
    """Gift ID"""
    gift_name: str = ''
    """Gift name"""
    start_time: int = 0
    """Start timestamp, same as end timestamp"""
    end_time: int = 0
    """End timestamp, same as start timestamp"""

    @classmethod
    def from_command(cls, data: dict):
        return cls(
            uid=data['uid'],
            username=data['username'],
            guard_level=data['guard_level'],
            num=data['num'],
            price=data['price'],
            gift_id=data['gift_id'],
            gift_name=data['gift_name'],
            start_time=data['start_time'],
            end_time=data['end_time'],
        )


@dataclasses.dataclass
class UserToastV2Message:
    """
    Another guard purchase message, contains more data
    """

    uid: int = 0
    """User ID"""
    username: str = ''
    """Username"""
    guard_level: int = 0
    """Guard level: 0 non-guard, 1 governor, 2 admiral, 3 captain"""
    num: int = 0  # Can be understood as gift quantity?
    """Quantity"""
    price: int = 0
    """Unit price in gold seeds"""
    unit: str = ''
    """Unit, according to open platform documentation, normal unit is "month", if other content, ignore `guard_num` and use this field instead, e.g. "*3 days" """
    gift_id: int = 0
    """Gift ID"""
    start_time: int = 0
    """Start timestamp, same as end timestamp"""
    end_time: int = 0
    """End timestamp, same as start timestamp"""
    source: int = 0
    """Guess 0 means self-purchased, 2 means gifted by others, this only affects whether animation is played"""
    toast_msg: str = ''
    """Notification message ("<%XXX%> renewed captain in streamer XXX's room, today is the XXXth day accompanying the streamer")"""

    @classmethod
    def from_command(cls, data: dict):
        sender_info = data['sender_uinfo']
        guard_info = data['guard_info']
        pay_info = data['pay_info']
        gift_info = data['gift_info']
        option = data['option']
        return cls(
            uid=sender_info['uid'],
            username=sender_info['base']['name'],
            guard_level=guard_info['guard_level'],
            num=pay_info['num'],
            price=pay_info['price'],
            unit=pay_info['unit'],
            gift_id=gift_info['gift_id'],
            start_time=guard_info['start_time'],
            end_time=guard_info['end_time'],
            source=option['source'],
            toast_msg=data['toast_msg'],
        )


@dataclasses.dataclass
class SuperChatMessage:
    """
    Super chat message
    """

    price: int = 0
    """Price (RMB)"""
    message: str = ''
    """Message"""
    message_trans: str = ''
    """Message Japanese translation"""
    start_time: int = 0
    """Start timestamp"""
    end_time: int = 0
    """End timestamp"""
    time: int = 0
    """Remaining time (approximately end timestamp - start timestamp)"""
    id: int = 0
    """Super chat ID, used for deletion"""
    gift_id: int = 0
    """Gift ID"""
    gift_name: str = ''
    """Gift name"""
    uid: int = 0
    """User ID"""
    uname: str = ''
    """Username"""
    face: str = ''
    """User avatar URL"""
    guard_level: int = 0
    """Guard level: 0 non-guard, 1 governor, 2 admiral, 3 captain"""
    user_level: int = 0
    """User level"""
    background_bottom_color: str = ''
    """Bottom background color, '#rrggbb'"""
    background_color: str = ''
    """Background color, '#rrggbb'"""
    background_icon: str = ''
    """Background icon"""
    background_image: str = ''
    """Background image URL"""
    background_price_color: str = ''
    """Background price color, '#rrggbb'"""
    medal_level: int = 0
    """Medal level"""
    medal_name: str = ''
    """Medal name"""
    medal_room_id: int = 0
    """Medal room ID"""
    medal_ruid: int = 0
    """Medal streamer ID"""

    @classmethod
    def from_command(cls, data: dict):
        medal_info = data.get('medal_info', None)
        if medal_info is not None:
            medal_level = medal_info['medal_level']
            medal_name = medal_info['medal_name']
            medal_room_id = medal_info['anchor_roomid']
            medal_ruid = medal_info['target_id']
        else:
            medal_level = 0
            medal_name = ''
            medal_room_id = 0
            medal_ruid = 0

        return cls(
            price=data['price'],
            message=data['message'],
            message_trans=data['message_trans'],
            start_time=data['start_time'],
            end_time=data['end_time'],
            time=data['time'],
            id=data['id'],
            gift_id=data['gift']['gift_id'],
            gift_name=data['gift']['gift_name'],
            uid=data['uid'],
            uname=data['user_info']['uname'],
            face=data['user_info']['face'],
            guard_level=data['user_info']['guard_level'],
            user_level=data['user_info']['user_level'],
            background_bottom_color=data['background_bottom_color'],
            background_color=data['background_color'],
            background_icon=data['background_icon'],
            background_image=data['background_image'],
            background_price_color=data['background_price_color'],
            medal_level=medal_level,
            medal_name=medal_name,
            medal_room_id=medal_room_id,
            medal_ruid=medal_ruid,
        )


@dataclasses.dataclass
class SuperChatDeleteMessage:
    """
    Delete super chat message
    """

    ids: List[int] = dataclasses.field(default_factory=list)
    """Super chat ID array"""

    @classmethod
    def from_command(cls, data: dict):
        return cls(
            ids=data['ids'],
        )


@dataclasses.dataclass
class InteractWordMessage:
    """
    Interactive message: enter room, follow streamer, etc.
    """

    uid: int = 0
    """User ID"""
    username: str = ''
    """Username"""
    face: str = ''
    """User avatar URL"""
    timestamp: int = 0
    """Timestamp"""
    msg_type: int = 0
    """`{1: 'Entered', 2: 'Followed', 3: 'Shared', 4: 'Special followed', 5: 'Mutual followed', 6: 'Liked streamer'}`"""

    @classmethod
    def from_command(cls, data: dict):
        user_info = data['uinfo']
        user_base_info = user_info['base']
        return cls(
            uid=user_info['uid'],
            username=user_base_info['name'],
            face=user_base_info['face'],
            timestamp=data['timestamp'],
            msg_type=data['msg_type'],
        )
