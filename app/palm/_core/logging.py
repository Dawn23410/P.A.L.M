import logging


def get_logger(name: str = "palm_sdk") -> logging.Logger:
    return logging.getLogger(name)
