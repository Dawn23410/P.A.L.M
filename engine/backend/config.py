"""薄桥接层：实现见 palm_llm.server.config。"""
import palm_boot  # noqa: E402,F401  自举：挂载内嵌项目
from palm_llm.server.config import *  # noqa: F401,F403
from palm_llm.server.config import (  # noqa: F401
    BASE_DIR, CONFIG_PATH, CONV_DIR, DATA_DIR, HOME_DIR, UPLOAD_DIR,
    ensure_dirs, get_provider, load_config, save_config,
)
