将 nssm.exe（64位，来自 https://nssm.cc ）放在此目录。
然后以管理员身份运行 engine\install_service.bat 即可把 P.A.L.M 注册为 Windows 服务（后台常驻 + 开机自启）。
仅做临时常驻测试时无需 nssm：运行 test_daemon.bat 即可（pythonw 无窗口常驻，重启后不保留）。
