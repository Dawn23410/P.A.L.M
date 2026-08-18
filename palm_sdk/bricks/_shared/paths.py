import os


def agent_memory_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".palm", "memory")


def find_brick_root(start_file: str) -> str:
    """从砖内任意文件向上回溯到砖根目录（含 src/ 的目录）。"""
    d = os.path.dirname(os.path.abspath(start_file))
    while d and d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "src")):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.abspath(start_file))


def brick_data_dir(brick_file: str, subdir: str = "data") -> str:
    """砖独立运行时的本地数据目录（砖根/子目录）。"""
    return os.path.join(find_brick_root(brick_file), subdir)


def brick_local(brick_file: str, *parts: str) -> str:
    """砖内任意本地资源路径（砖根/parts），位置无关、深度无关。

    替代散落的 parents[N] / dirname×N 硬锚点，使砖可随意移动到任意文件夹。
    """
    return os.path.join(find_brick_root(brick_file), *parts)


def fallback_dir(value: object, brick_file: str, subdir: str = "data") -> str:
    """value 非空用原值；否则回退砖本地 subdir 目录（独立运行默认路径）。"""
    if value:
        return str(value)
    return brick_data_dir(brick_file, subdir)


def resolve_storage(*parts: str, brick_file: str) -> str:
    """解析存储池路径：全局已配置用全局池，否则回退砖本地 data/。"""
    from palm_sdk.core.config import settings
    return os.path.join(fallback_dir(settings.STORAGE_POOL_DIR, brick_file), *parts)
