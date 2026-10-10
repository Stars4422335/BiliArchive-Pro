# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：BiliArchive-Pro 核心引擎（CLI 守护进程）
# 产物为单目录模式：build/ 与 dist/BiliArchive-Pro/
#
# 用法（在项目根目录、已激活 venv）：
#   venv\Scripts\python.exe -m PyInstaller build.spec --noconfirm
# 产物验证：
#   dist\BiliArchive-Pro\BiliArchive-Pro.exe --version
#
# 说明：
# - 不打包 config.yaml / data/ / downloads/ / bin/：运行时由用户目录提供，
#   exe 启动后 os.chdir 到 exe 所在目录，配置与数据落在 exe 旁边。
# - ffmpeg 不内嵌：沿用组件检查逻辑（PATH 或 bin/ 目录）。
# - login.py 与 web.py 未包含：登录需终端二维码交互，WebUI 需前端 dist，
#   二者仍以源码方式运行；本 spec 先覆盖核心引擎的免 Python 环境分发。

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # bilibili-api-python 动态选择网络客户端，静态分析发现不了
        'bilibili_api',
        'bilibili_api.clients.HTTPXClient',
        'bilibili_api.clients.AiohttpClient',
        # yt-dlp 的提取器通过插件机制动态加载
        'yt_dlp',
        'yt_dlp.extractor',
        'yt_dlp.extractor.bilibili',
        # uvicorn 工作进程与协议实现为运行时动态导入
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 与核心引擎无关的重依赖，减小体积
        # 注意：PIL/Pillow 是 bilibili_api.utils.picture 的真实依赖，不可排除
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'pytest',
        'PyInstaller',
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BiliArchive-Pro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BiliArchive-Pro',
)
