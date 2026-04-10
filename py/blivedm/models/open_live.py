# -*- coding: utf-8 -*-
import dataclasses
from typing import *

__all__ = (
    'DanmakuMessage',
    'GiftMessage',
    'GuardBuyMessage',
    'SuperChatMessage',
    'SuperChatDeleteMessage',
    'LikeMessage',
)

# Comments are copied from official documentation, ask Bilibili if you don't understand
# https://open-live.bilibili.com/document/f9ce25be-312e-1f4a-85fd-fef21f1637f8


@dataclasses.dataclass
class DanmakuMessage:
    """
    Danmaku message
    """

    uname: str = ''
    """User nickname"""
    open_id: str = ''
    """User unique identifier"""
    uface: str = ''
    """User avatar"""
    timestamp: int = 0
    """Danmaku send time in seconds timestamp"""
    room_id: int = 0
    """Live room receiving danmaku"""
    msg: str = ''
    """Danmaku content"""
    msg_id: str = ''
    """Message unique ID"""
    guard_level: int = 0
    """Corresponding room guard level"""
    fans_medal_wearing_status: bool = False
    """Fan medal wearing status for this room"""
    fans_medal_name: str = ''
    """Fan medal name"""
    fans_medal_level: int = 0
    """Corresponding room medal info"""
    emoji_img_url: str = ''
    """Emoji image URL"""
    dm_type: int = 0
    """Danmaku type: 0 - normal danmaku, 1 - emoji danmaku"""
    glory_level: int = 0
    """Live glory level"""
    reply_open_id: str = ''
    """User unique identifier being @mentioned"""
    reply_uname: str = ''
    """Nickname of @mentioned user"""
    is_admin: int = 0
    """Whether the danmaku sender is a room moderator, 0 or 1, 1 means moderator"""

    @classmethod
    def from_command(cls, data: dict):
        return cls(
            uname=data['uname'],
            open_id=data['open_id'],
            uface=data['uface'],
            timestamp=data['timestamp'],
            room_id=data['room_id'],
            msg=data['msg'],
            msg_id=data['msg_id'],
            guard_level=data['guard_level'],
            fans_medal_wearing_status=data['fans_medal_wearing_status'],
            fans_medal_name=data['fans_medal_name'],
            fans_medal_level=data['fans_medal_level'],
            emoji_img_url=data['emoji_img_url'],
            dm_type=data['dm_type'],
            glory_level=data['glory_level'],
            reply_open_id=data['reply_open_id'],
            reply_uname=data['reply_uname'],
            is_admin=data['is_admin'],
        )


@dataclasses.dataclass
class AnchorInfo:
    """
    Streamer info
    """

    uid: int = 0
    """Streamer UID receiving the gift"""
    open_id: str = ''
    """Streamer unique identifier"""
    uname: str = ''
    """Streamer nickname"""
    uface: str = ''
    """Streamer avatar"""

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            uid=data['uid'],
            open_id=data['open_id'],
            uname=data['uname'],
            uface=data['uface'],
        )


@dataclasses.dataclass
class ComboInfo:
    """
    Combo info
    """

    combo_base_num: int = 0
    """Number of items gifted per combo hit"""
    combo_count: int = 0
    """Combo count"""
    combo_id: str = ''
    """Combo ID"""
    combo_timeout: int = 0
    """Combo validity period in seconds"""

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            combo_base_num=data['combo_base_num'],
            combo_count=data['combo_count'],
            combo_id=data['combo_id'],
            combo_timeout=data['combo_timeout'],
        )


@dataclasses.dataclass
class GiftMessage:
    """
    Gift message
    """

    room_id: int = 0
    """Room number"""
    open_id: str = ''
    """User unique identifier"""
    uname: str = ''
    """Gift sender nickname"""
    uface: str = ''
    """Gift sender avatar"""
    gift_id: int = 0
    """Item ID (blind box: revealed item ID)"""
    gift_name: str = ''
    """Item name (blind box: revealed item name)"""
    gift_num: int = 0
    """Number of items gifted"""
    price: int = 0
    """
    Gift unit price revealed (1000 = 1 yuan = 10 battery), blind box: revealed item value

    Note:

    - For free gifts, this field may not be 0, it could be silver seed points count
    - Some discounted gifts don't show actual value here, actual value should use `r_price`
    """
    r_price: int = 0
    """
    Actual value (1000 = 1 yuan = 10 battery), blind box: revealed item value

    Note: for free gifts, this field may not be 0
    """
    paid: bool = False
    """Whether it's a paid item"""
    fans_medal_level: int = 0
    """Actual sender medal info"""
    fans_medal_name: str = ''
    """Fan medal name"""
    fans_medal_wearing_status: bool = False
    """Fan medal wearing status for this room"""
    guard_level: int = 0
    """Guard level"""
    timestamp: int = 0
    """Gift receiving time in seconds timestamp"""
    anchor_info: AnchorInfo = dataclasses.field(default_factory=AnchorInfo)
    """Streamer info"""
    msg_id: str = ''
    """Message unique ID"""
    gift_icon: str = ''
    """Item icon"""
    combo_gift: bool = False
    """Whether it's a combo gift"""
    combo_info: ComboInfo = dataclasses.field(default_factory=ComboInfo)
    """Combo info"""

    @classmethod
    def from_command(cls, data: dict):
        combo_info = data.get('combo_info', None)
        if combo_info is None:
            combo_info = ComboInfo()
        else:
            combo_info = ComboInfo.from_dict(combo_info)

        return cls(
            room_id=data['room_id'],
            open_id=data['open_id'],
            uname=data['uname'],
            uface=data['uface'],
            gift_id=data['gift_id'],
            gift_name=data['gift_name'],
            gift_num=data['gift_num'],
            price=data['price'],
            r_price=data['r_price'],
            paid=data['paid'],
            fans_medal_level=data['fans_medal_level'],
            fans_medal_name=data['fans_medal_name'],
            fans_medal_wearing_status=data['fans_medal_wearing_status'],
            guard_level=data['guard_level'],
            timestamp=data['timestamp'],
            anchor_info=AnchorInfo.from_dict(data['anchor_info']),
            msg_id=data['msg_id'],
            gift_icon=data['gift_icon'],
            combo_gift=data.get('combo_gift', False),  # Official debugger doesn't send this field
            combo_info=combo_info,  # Official debugger doesn't send this field
        )


@dataclasses.dataclass
class UserInfo:
    """
    User info
    """

    open_id: str = ''
    """User unique identifier"""
    uname: str = ''
    """User nickname"""
    uface: str = ''
    """User avatar"""

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            open_id=data['open_id'],
            uname=data['uname'],
            uface=data['uface'],
        )


@dataclasses.dataclass
class GuardBuyMessage:
    """
    Guard purchase message
    """

    user_info: UserInfo = dataclasses.field(default_factory=UserInfo)
    """User info"""
    guard_level: int = 0
    """Guard level"""
    guard_num: int = 0
    """Guard quantity"""
    guard_unit: str = ''
    """Guard unit (normal unit is "month", if other content, ignore `guard_num` and use this field instead, e.g. "*3 days")"""
    price: int = 0
    """Guard price in gold seeds"""
    fans_medal_level: int = 0
    """Fan medal level"""
    fans_medal_name: str = ''
    """Fan medal name"""
    fans_medal_wearing_status: bool = False
    """Fan medal wearing status for this room"""
    room_id: int = 0
    """Room number"""
    msg_id: str = ''
    """Message unique ID"""
    timestamp: int = 0
    """Guard purchase time in seconds timestamp"""

    @classmethod
    def from_command(cls, data: dict):
        return cls(
            user_info=UserInfo.from_dict(data['user_info']),
            guard_level=data['guard_level'],
            guard_num=data['guard_num'],
            guard_unit=data['guard_unit'],
            price=data['price'],
            fans_medal_level=data['fans_medal_level'],
            fans_medal_name=data['fans_medal_name'],
            fans_medal_wearing_status=data['fans_medal_wearing_status'],
            room_id=data['room_id'],
            msg_id=data['msg_id'],
            timestamp=data['timestamp'],
        )


@dataclasses.dataclass
class SuperChatMessage:
    """
    Super chat message
    """

    room_id: int = 0
    """Live room ID"""
    open_id: str = ''
    """User unique identifier"""
    uname: str = ''
    """Purchasing user nickname"""
    uface: str = ''
    """Purchasing user avatar"""
    message_id: int = 0
    """Message ID (needed for retracting messages in risk control scenarios)"""
    message: str = ''
    """Message content"""
    rmb: int = 0
    """Payment amount (yuan)"""
    timestamp: int = 0
    """Gift time in seconds"""
    start_time: int = 0
    """Effective start time"""
    end_time: int = 0
    """Effective end time"""
    guard_level: int = 0
    """Corresponding room guard level"""
    fans_medal_level: int = 0
    """Corresponding room medal info"""
    fans_medal_name: str = ''
    """Corresponding room medal name"""
    fans_medal_wearing_status: bool = False
    """Fan medal wearing status for this room"""
    msg_id: str = ''
    """Message unique ID"""

    @classmethod
    def from_command(cls, data: dict):
        return cls(
            room_id=data['room_id'],
            open_id=data['open_id'],
            uname=data['uname'],
            uface=data['uface'],
            message_id=data['message_id'],
            message=data['message'],
            rmb=data['rmb'],
            timestamp=data['timestamp'],
            start_time=data['start_time'],
            end_time=data['end_time'],
            guard_level=data['guard_level'],
            fans_medal_level=data['fans_medal_level'],
            fans_medal_name=data['fans_medal_name'],
            fans_medal_wearing_status=data['fans_medal_wearing_status'],
            msg_id=data['msg_id'],
        )


@dataclasses.dataclass
class SuperChatDeleteMessage:
    """
    Delete super chat message
    """

    room_id: int = 0
    """Live room ID"""
    message_ids: List[int] = dataclasses.field(default_factory=list)
    """Message IDs"""
    msg_id: str = ''
    """Message unique ID"""

    @classmethod
    def from_command(cls, data: dict):
        return cls(
            room_id=data['room_id'],
            message_ids=data['message_ids'],
            msg_id=data['msg_id'],
        )


@dataclasses.dataclass
class LikeMessage:
    """
    Like message

    Note:

    - Like events are only triggered when the room is streaming
    - Like counts are aggregated per user every 2 seconds
    """

    uname: str = ''
    """User nickname"""
    open_id: str = ''
    """User unique identifier"""
    uface: str = ''
    """User avatar"""
    timestamp: int = 0
    """Time in seconds timestamp"""
    room_id: int = 0
    """Live room where it occurred"""
    like_text: str = ''
    """Like text (e.g., "xxx liked")"""
    like_count: int = 0
    """Aggregated like count for a single user in the last 2 seconds"""
    fans_medal_wearing_status: bool = False
    """Fan medal wearing status for this room"""
    fans_medal_name: str = ''
    """Fan medal name"""
    fans_medal_level: int = 0
    """Corresponding room medal info"""
    msg_id: str = ''  # This field is not listed in the official documentation table, but it exists in the reference JSON
    """Message unique ID"""
    # There is also a guard_level field, but since it doesn't appear in the official documentation, it is not added

    @classmethod
    def from_command(cls, data: dict):
        return cls(
            uname=data['uname'],
            open_id=data['open_id'],
            uface=data['uface'],
            timestamp=data['timestamp'],
            room_id=data['room_id'],
            like_text=data['like_text'],
            like_count=data['like_count'],
            fans_medal_wearing_status=data['fans_medal_wearing_status'],
            fans_medal_name=data['fans_medal_name'],
            fans_medal_level=data['fans_medal_level'],
            msg_id=data.get('msg_id', ''),  # This field is not listed in the official documentation table, but it exists in the reference JSON
        )


@dataclasses.dataclass
class RoomEnterMessage:
    """
    Enter room message
    """

    room_id: int = 0
    """Live room ID"""
    uface: str = ''
    """User avatar"""
    uname: str = ''
    """User nickname"""
    open_id: str = ''
    """User unique identifier"""
    timestamp: int = 0
    """Timestamp of occurrence"""
    msg_id: str = ''  # This field is not listed in the official documentation table, but it actually exists
    """Message unique ID"""

    @classmethod
    def from_command(cls, data: dict):
        return cls(
            room_id=data['room_id'],
            uface=data['uface'],
            uname=data['uname'],
            open_id=data['open_id'],
            timestamp=data['timestamp'],
            msg_id=data.get('msg_id', ''),  # This field is not listed in the official documentation table, but it actually exists
        )


@dataclasses.dataclass
class LiveStartMessage:
    """
    Start streaming message
    """

    room_id: int = 0
    """Live room ID"""
    open_id: str = ''
    """User unique identifier"""
    timestamp: int = 0
    """Timestamp of occurrence"""
    area_name: str = ''
    """Secondary category name at stream start"""
    title: str = ''
    """Live room title at stream start"""
    msg_id: str = ''  # This field is not listed in the official documentation table, but it actually exists
    """Message unique ID"""

    @classmethod
    def from_command(cls, data: dict):
        return cls(
            room_id=data['room_id'],
            open_id=data['open_id'],
            timestamp=data['timestamp'],
            area_name=data['area_name'],
            title=data['title'],
            msg_id=data.get('msg_id', ''),  # This field is not listed in the official documentation table, but it actually exists
        )


@dataclasses.dataclass
class LiveEndMessage:
    """
    End streaming message
    """

    room_id: int = 0
    """Live room ID"""
    open_id: str = ''
    """User unique identifier"""
    timestamp: int = 0
    """Timestamp of occurrence"""
    area_name: str = ''
    """Secondary category name at stream start"""
    title: str = ''
    """Live room title at stream start"""
    msg_id: str = ''  # This field is not listed in the official documentation table, but it actually exists
    """Message unique ID"""

    @classmethod
    def from_command(cls, data: dict):
        return cls(
            room_id=data['room_id'],
            open_id=data['open_id'],
            timestamp=data['timestamp'],
            area_name=data['area_name'],
            title=data['title'],
            msg_id=data.get('msg_id', ''),  # This field is not listed in the official documentation table, but it actually exists
        )
