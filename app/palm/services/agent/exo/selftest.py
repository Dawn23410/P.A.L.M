"""薄桥接层（可执行入口）：转发到独立项目「智能体框架」（`palm_agent`）。

原命令 `python -m palm.services.agent.exo.selftest` 仍可用。
"""
import runpy
import sys

import palm_boot  # noqa: F401,E402  自举：挂载独立项目

if __name__ == "__main__":
    sys.argv[0] = "palm_agent.exo.selftest"
    runpy.run_module("palm_agent.exo.selftest", run_name="__main__", alter_sys=True)
else:
    from palm_agent.exo.selftest import *  # noqa: F401,F403,E402
