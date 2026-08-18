# 子进程句柄桩：独立态无管理芯片，返回 None。
class _NullHandle:
    state = "inactive"

    def load(self):
        raise FileNotFoundError("独立态无管理芯片，无法拉起子进程")

    def unload(self):
        return None


def get_handle(name: str):
    return None
