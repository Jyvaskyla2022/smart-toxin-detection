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
source.include_exts = py,png,jpg,kv,txt
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
# NDK 明确钉死 26b：新版（如 r30b）与 python-for-android 尚不兼容，
# 若不写，某些环境下 buildozer 会自动拉最新 NDK 导致编译失败
android.ndk = 26b
# 只编 arm64-v8a：armeabi-v7a 上 numpy/OpenBLAS 交叉编译经常失败，
# 且双架构体积翻倍、构建时间翻倍、更容易把 runner 的磁盘耗尽
android.archs = arm64-v8a

# 自动接受 SDK 许可，避免打包中途卡在交互式确认
android.accept_sdk_license = True

# 应用名称显示
android.app_name = Smart Toxin Detection
android.numeric_version = 200

[buildozer]
log_level = 2
warn_on_root = 1
