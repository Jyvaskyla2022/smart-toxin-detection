# ============================================================
#  Smart Toxin Detection —— 安卓打包配置（buildozer）
#  代码设计者：PhLi
#  使用方法见同目录 README_构建指南.md
# ============================================================

[app]
title = Smart Toxin Detection
package.name = smarttoxindetection
package.domain = org.phli

# 代码设计者信息（写入 APK 元数据）
author = PhLi

source.dir = .
# ttf/otf：中文字体（fonts/ 下），没有它们安卓上中文全是方块
source.include_exts = py,png,jpg,kv,txt,ttf,otf
version = 2.0.0

# 依赖：kivy 界面 / numpy 数值 / pillow 图像解码与HSV / plyer 调用安卓相机
requirements = python3,kivy==2.3.0,numpy,pillow,plyer

# 相机与存储权限
android.permissions = CAMERA,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES

# 竖屏
orientation = portrait
fullscreen = 0

android.api = 34
android.minapi = 24
# NDK 必须与 p4a v2024.01.21 配套使用 25b（p4a 官方推荐版本）。
# 【实测】r26b 及以上会挂：r26 的 clang 新增 -Wcast-function-type-strict 严格警告，
# 而 SDL2 引导包以 -Werror 编译，老版 harfbuzz（hb-ft.cc）直接报错终止。
android.ndk = 25b
# 只编 arm64-v8a：armeabi-v7a 上 numpy/OpenBLAS 交叉编译经常失败，
# 且双架构体积翻倍、构建时间翻倍、更容易把 runner 的磁盘耗尽
android.archs = arm64-v8a

# 钉住 python-for-android 版本（2024-01 发布，默认 Python 3.11.5 + Cython 0.29.36，
# kivy recipe 正好是 2.3.0）。
# 【为什么必须钉】p4a 新版把 Python 钉死为 3.14.2，而 kivy 2.3.0 的 Cython 生成
# 代码与 3.14 的 C API 不兼容（_PyLong_AsByteArray 参数变更、
# _PyInterpreterState_GetConfig 被移除等），编译必挂。此为 2026-11-11 云端构建
# 实测结论。若以后升级 kivy 到支持新 Python 的版本，可考虑去掉这一行。
p4a.branch = v2024.01.21

# 自动接受 SDK 许可，避免打包中途卡在交互式确认
android.accept_sdk_license = True

# 应用名称显示
android.app_name = Smart Toxin Detection
android.numeric_version = 200

# 应用图标：AI 设计的试管主题图标（512x512 PNG，p4a 自动缩放为各密度 mipmap）
icon.filename = icon.png

[buildozer]
log_level = 2
warn_on_root = 1
