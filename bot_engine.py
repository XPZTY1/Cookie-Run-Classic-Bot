import sys
import config
from core.bot_instance import BotInstance

# Re-export BotInstance
__all__ = [
    "BotInstance",
    "get_default_instance",
    "set_gui_log_callback",
    "log_info",
    "log_debug",
    "start_bot",
    "stop_bot",
    "quit_program",
    "bot_loop",
]

_default_instance = None


def get_default_instance():
    global _default_instance
    if _default_instance is None:
        dev_id = getattr(config, "DEVICE_ID", "").strip()
        _default_instance = BotInstance(dev_id)
    return _default_instance


def set_gui_log_callback(callback):
    get_default_instance()._gui_log_callback = callback


def log_info(msg):
    get_default_instance().log_info(msg)


def log_debug(msg):
    get_default_instance().log_debug(msg)


def start_bot():
    get_default_instance().start_bot()


def stop_bot():
    if _default_instance:
        _default_instance.stop_bot()


def quit_program():
    print(">> ออกจากโปรแกรม (F9)")
    if _default_instance and _default_instance.running:
        _default_instance.save_global_stats(session_done=True)
        _default_instance.print_session_report()
    sys.exit(0)


def bot_loop():
    get_default_instance().bot_loop()
