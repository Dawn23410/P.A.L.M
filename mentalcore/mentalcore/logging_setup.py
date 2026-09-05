"""日志封装：统一用标准库 logging，按配置设置级别，避免各模块自起 handler。"""
import logging

_CONFIGURED = False


def get_logger(name: str = "mentalcore") -> logging.Logger:
    """返回命名 logger；首次调用按默认 INFO 配置一个简单 handler。"""
    global _CONFIGURED
    logger = logging.getLogger(name)
    if not _CONFIGURED:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        logging.getLogger("mentalcore").addHandler(handler)
        logging.getLogger("mentalcore").setLevel(logging.INFO)
        _CONFIGURED = True
    return logger


def set_level(level: str) -> None:
    """按字符串设置 mentalcore 根 logger 级别。"""
    logging.getLogger("mentalcore").setLevel(getattr(logging, level.upper(), logging.INFO))
