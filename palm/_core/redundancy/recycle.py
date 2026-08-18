def send_to_recycle_bin(path: str) -> bool:
    # 独立态：不实际删除，交由调用方决定。
    return False


def bootstrap_source(*_args, **_kwargs) -> None:
    return None
