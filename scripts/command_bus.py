# -*- coding: utf-8 -*-
"""实机控制指令出口（桩）。

原 ROS 版本通过 StateMsg 话题把指令发给 agent（导航/任务规划）。
脱离 ROS 后，指令统一走 dispatch()；当前仅记录日志，控制层之后重写。
"""

import logging

log = logging.getLogger("lmam.command_bus")

_HANDLERS = []


def register(handler) -> None:
    """注册指令处理器 handler(command: dict) -> None（去重）。"""
    if handler not in _HANDLERS:
        _HANDLERS.append(handler)


def dispatch(command: dict) -> None:
    """分发一条实机控制指令。

    TODO: 之后在此挂接新的控制层实现（导航/机械臂/展区讲解联动）。
    """
    log.info("[STUB] 实机控制指令: %s (待重写)", command)
    for handler in list(_HANDLERS):
        try:
            handler(command)
        except Exception as e:  # noqa: BLE001 控制层异常不能打断语音主流程
            log.warning("[command_bus] handler 异常: %s", e)
