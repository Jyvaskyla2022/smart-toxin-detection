# -*- coding: utf-8 -*-
"""Smart Toxin Detection —— 安卓端（Kivy）

程序名称 : Smart Toxin Detection
代码设计 : PhLi
功能     : 加载电脑端导出的便携模型（.stmodel 纯 JSON），拍照/选图离线推算浓度。
说明     : 推理逻辑与电脑端、手机网页端完全一致（同一套纯 numpy 浮点特征公式），
           一致性由 tests/parity_test.py、tests/web_parity_test.py 守护。
运行环境 : Android（python-for-android / buildozer 打包），详见 README_构建指南.md
"""
import csv
import os
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView

from portable_model import PortableModel

# ---- 中文支持 -------------------------------------------------------------
# Kivy 默认字体（Roboto）不含 CJK 字形，安卓上所有中文都会显示成方块。
# 主字体用 Noto Sans SC（拉丁字母 + 简体中文 + 常用标点全覆盖）。
# 【踩坑记录】之前用的 DroidSansFallback 只含 CJK，不含拉丁字母、半角括号
# 和弯引号——注册为全局默认后"中文正常了，英文/数字反而全变方块"。
# 注册统一在模块加载末尾执行（_register_cjk_font），字体文件查找顺序：
#   Noto（fonts/ 子目录 → app 根目录 → /sdcard）→ DroidSansFallback 同样三个位置
#   → 都没有时，从 APK assets 现场复制到应用私有目录再注册（解包缺失兜底）
# 结果记录在 _FONT_STATUS，显示在界面底部一行小字（方便截图排查）。
_FONT_NAME = "NotoSansSC-Regular.otf"
_FALLBACK_FONT_NAME = "DroidSansFallback.ttf"
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_FONT_CANDIDATES = []
for _n in (_FONT_NAME, _FALLBACK_FONT_NAME):
    _FONT_CANDIDATES += [
        os.path.join(_APP_DIR, "fonts", _n),
        os.path.join(_APP_DIR, _n),
        "/sdcard/SmartToxinDetection/fonts/" + _n,
    ]
_FONT_STATUS = "FONT: pending"


def _private_dir():
    try:
        from jnius import autoclass
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        return act.getFilesDir().getAbsolutePath()
    except Exception:
        return _APP_DIR


def _copy_asset_font():
    """从 APK assets 里把字体复制到私有目录（解包缺失时的兜底）。"""
    try:
        from jnius import autoclass
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        am = act.getAssets()
        dst_dir = _private_dir()
        for asset in ("private/fonts/" + _FONT_NAME,
                      "fonts/" + _FONT_NAME,
                      "app/fonts/" + _FONT_NAME,
                      "private/fonts/" + _FALLBACK_FONT_NAME,
                      "fonts/" + _FALLBACK_FONT_NAME,
                      "app/fonts/" + _FALLBACK_FONT_NAME):
            try:
                stream = am.open(asset)
            except Exception:
                continue
            try:
                dst = os.path.join(dst_dir, os.path.basename(asset))
                buf = bytearray(65536)
                with open(dst, "wb") as out:
                    while True:
                        n = stream.read(buf)
                        if n <= 0:
                            break
                        out.write(bytes(buf[:n]))
                stream.close()
                return dst
            except Exception:
                pass
    except Exception:
        pass
    return None


def _register_cjk_font():
    global _FONT_STATUS
    path = None
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            path = p
            break
    if path is None:
        path = _copy_asset_font()
    if path is None:
        try:
            entries = ",".join(sorted(os.listdir(_APP_DIR))[:10])
        except Exception as e:
            entries = "list failed: " + str(e)
        _FONT_STATUS = "FONT: file missing | APPDIR: " + entries
        return
    try:
        from kivy.core.text import LabelBase
        # 注意：Kivy 的参数名是 fn_bolditalic（bold 和 italic 之间没有下划线），
        # 写成 fn_bold_italic 会抛 TypeError，这正是之前闪退/方块的根因
        LabelBase.register(
            name="Roboto",
            fn_regular=path,
            fn_bold=path,
            fn_italic=path,
            fn_bolditalic=path,
        )
        _FONT_STATUS = "FONT: OK " + path
    except Exception as e:
        _FONT_STATUS = "FONT: register failed " + repr(e)[:80]
# ---------------------------------------------------------------------------

APP_NAME = "Smart Toxin Detection"
APP_AUTHOR = "PhLi"
APP_VERSION = "2.0.0"

ALGO_CN = {"linear": "线性回归", "ridge": "岭回归", "forest": "随机森林",
           "boost": "梯度提升树", "knn": "K近邻", "svr": "支持向量回归"}

# 安卓 6.0+ 需要运行时申请权限；桌面调试时该模块不存在，直接跳过
try:
    from android.permissions import Permission, request_permissions  # type: ignore

    _PERMS = [Permission.CAMERA, Permission.READ_EXTERNAL_STORAGE,
              Permission.WRITE_EXTERNAL_STORAGE]
except Exception:  # pragma: no cover - 非安卓环境
    request_permissions = None
    _PERMS = []

# ---- 崩溃自报告 ------------------------------------------------------------
# 闪退时用户什么都看不到，没法反馈。这里把启动失败的堆栈：
#   1) 直接弹到屏幕上（可滚动对话框，方便截图发给开发者）；
#   2) 写入手机可见目录的 crash.log。
def _external_report_dir():
    """用户在文件管理器里能找到的目录（优先应用专属外部目录）。"""
    try:
        from jnius import autoclass
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        d = act.getExternalFilesDir(None)
        if d is not None:
            return d.getAbsolutePath()   # /storage/emulated/0/Android/data/<包名>/files
    except Exception:
        pass
    return "/sdcard/SmartToxinDetection"


def _show_crash_dialog(text):
    try:
        from jnius import autoclass, PythonJavaClass, java_method

        class _Runner(PythonJavaClass):
            __javainterfaces__ = ["java/lang/Runnable"]

            def __init__(self, msg):
                super().__init__()
                self.msg = msg

            @java_method("()V")
            def run(self):
                try:
                    act = autoclass("org.kivy.android.PythonActivity").mActivity
                    tv = autoclass("android.widget.TextView")(act)
                    tv.setText(self.msg)
                    tv.setTextSize(11.0)
                    tv.setPadding(36, 36, 36, 36)
                    scroll = autoclass("android.widget.ScrollView")(act)
                    scroll.addView(tv)
                    builder = autoclass("android.app.AlertDialog$Builder")(act)
                    builder.setTitle("启动失败（请截图反馈）")
                    builder.setView(scroll)
                    builder.setPositiveButton("关闭", None)
                    builder.show()
                except Exception:
                    pass

        act = autoclass("org.kivy.android.PythonActivity").mActivity
        act.runOnUiThread(_Runner(text))
    except Exception:
        pass


def _report_crash():
    import traceback
    tb = traceback.format_exc()
    saved = []
    for d in {_external_report_dir(), "/sdcard/SmartToxinDetection"}:
        try:
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, "crash.log")
            with open(p, "w", encoding="utf-8") as f:
                f.write(tb)
            saved.append(p)
        except Exception:
            pass
    msg = tb[-1800:]
    if saved:
        msg += "\n\n—— 日志已保存到 ——\n" + "\n".join(saved)
    _show_crash_dialog(msg)


# ---- 运行轨迹（trace）------------------------------------------------------
# 闪退如果是原生层崩溃（如 SDL2 恢复、pyjnius 线程问题），python 的
# try/except 拦不住、crash.log 也不会有内容。这里在关键节点写轨迹文件，
# 下次打开 App 时自动弹出上次的轨迹，精确定位死在哪一步。
def _trace_path():
    try:
        from jnius import autoclass
        act = autoclass("org.kivy.android.PythonActivity").mActivity
        d = act.getExternalFilesDir(None)
        if d is not None:
            return os.path.join(d.getAbsolutePath(), "trace.log")
    except Exception:
        pass
    return os.path.join(_private_dir(), "trace.log")


def _trace(msg):
    try:
        p = _trace_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%H:%M:%S] ") + msg + "\n")
    except Exception:
        pass


# ---- 系统文件选择器（SAF）--------------------------------------------------
# 安卓 11+（含鸿蒙）启用“分区存储”后，普通文件 API 看不到 Download /
# Documents 里的非媒体文件（.stmodel 模型正是这种），所以 Kivy 内置的
# FileChooserListView 必然“扫描不到手机中的模型”。唯一可靠的方式是调用
# 系统文件选择器（Storage Access Framework）：用户选中哪个文件，系统就把
# 那个文件授权给本应用，我们再把它复制进应用私有目录加载。
try:
    from android import activity as _a_activity  # type: ignore
    _ANDROID = True
except Exception:            # 桌面调试环境没有 android 模块
    _a_activity = None
    _ANDROID = False

_PICKER = {"next_req": 820001, "handlers": {}}


def _on_any_picker_result(request_code, result_code, data):
    """全局分发：系统文件选择器的返回结果（android.activity 只绑一次）。"""
    handler = _PICKER["handlers"].pop(request_code, None)
    if handler is not None:
        try:
            handler(result_code, data)
        except Exception:
            pass


if _ANDROID:
    _a_activity.bind(on_activity_result=_on_any_picker_result)


def _pick_file(mime: str, on_path):
    """弹出系统文件选择器；选中后复制到应用私有目录，回调 on_path(path)。

    on_path(None) 表示用户取消；on_path(None, exc) 表示出错。
    """
    from jnius import autoclass, cast

    mActivity = autoclass("org.kivy.android.PythonActivity").mActivity
    Activity = autoclass("android.app.Activity")
    Intent = autoclass("android.content.Intent")
    String = autoclass("java.lang.String")

    req = _PICKER["next_req"]
    _PICKER["next_req"] += 1

    def handler(result_code, data):
        # ⚠ 本回调运行在安卓 UI 线程：只做文件复制这类线程安全操作，
        # 界面更新必须用 Clock.schedule_once 转交 Kivy 主线程，
        # 否则跨线程操作 Kivy 控件会直接把 App 搞崩（拍照返回时已实测踩坑）
        _trace("picker: UIthread result_code=%d" % result_code)
        try:
            if result_code != Activity.RESULT_OK or data is None:
                _trace("picker: canceled, schedule on_path(None)")
                Clock.schedule_once(lambda dt: on_path(None), 0)
                return
            resolver = mActivity.getContentResolver()
            uri = data.getData()
            # 1) 查询原始文件名（保留 .stmodel 等后缀）
            name = None
            try:
                cur = resolver.query(uri, None, None, None, None)
                if cur is not None:
                    if cur.moveToFirst():
                        idx = cur.getColumnIndex("_display_name")
                        if idx >= 0:
                            name = cur.getString(idx)
                    cur.close()
            except Exception:
                name = None
            if not name:
                name = "imported_%d" % int(time.time())
            # 2) 把内容流复制到应用私有目录（分区存储下唯一可靠的读取方式）
            dst = os.path.join(_private_dir(), name)
            stream = resolver.openInputStream(uri)
            buf = bytearray(65536)
            with open(dst, "wb") as out:
                while True:
                    n = stream.read(buf)   # jnius 支持 bytearray 输出缓冲
                    if n <= 0:
                        break
                    out.write(bytes(buf[:n]))
            stream.close()
            _trace("picker: copied ok, schedule on_path")
            Clock.schedule_once(lambda dt, p=dst: on_path(p), 0)
        except Exception as e:
            _trace("picker: error " + str(e)[:120])
            Clock.schedule_once(lambda dt, err=e: on_path(None, err), 0)

    _PICKER["handlers"][req] = handler
    intent = Intent(Intent.ACTION_GET_CONTENT)
    intent.setType(mime)
    intent.addCategory(Intent.CATEGORY_OPENABLE)
    mActivity.startActivityForResult(
        Intent.createChooser(intent,
                             cast("java.lang.CharSequence", String("选择文件"))),
        req)


def _create_document(mime, title, src_path, on_saved):
    """SAF 创建文档：弹系统"保存到…"对话框，把本地 src_path 的内容写进
    用户选择的位置（Download 等）。分区存储下导出文件的唯一可靠方式。

    on_saved(result)：None=用户取消；"ok"=成功；异常对象=失败。
    """
    from jnius import autoclass

    mActivity = autoclass("org.kivy.android.PythonActivity").mActivity
    Activity = autoclass("android.app.Activity")
    Intent = autoclass("android.content.Intent")

    req = _PICKER["next_req"]
    _PICKER["next_req"] += 1

    def handler(result_code, data):
        # ⚠ 本回调运行在安卓 UI 线程：只做流读写，界面更新 Clock.schedule_once 转交
        _trace("saver: UIthread result_code=%d" % result_code)
        try:
            if result_code != Activity.RESULT_OK or data is None:
                Clock.schedule_once(lambda dt: on_saved(None), 0)
                return
            resolver = mActivity.getContentResolver()
            uri = data.getData()
            out = resolver.openOutputStream(uri)
            with open(src_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    out.write(chunk)
            out.close()
            _trace("saver: saved ok")
            Clock.schedule_once(lambda dt: on_saved("ok"), 0)
        except Exception as e:
            _trace("saver: error " + str(e)[:120])
            Clock.schedule_once(lambda dt, err=e: on_saved(err), 0)

    _PICKER["handlers"][req] = handler
    intent = Intent(Intent.ACTION_CREATE_DOCUMENT)
    intent.setType(mime)
    intent.addCategory(Intent.CATEGORY_OPENABLE)
    intent.putExtra(Intent.EXTRA_TITLE, title)
    mActivity.startActivityForResult(intent, req)


def _save_bitmap(bmp, dst):
    """把相机返回的缩略图 Bitmap 压缩保存为 jpg（相机忽略 EXTRA_OUTPUT 时的兜底）。"""
    from jnius import autoclass
    fmt = autoclass("android.graphics.Bitmap$CompressFormat").JPEG
    out = autoclass("java.io.FileOutputStream")(dst)
    ok = bmp.compress(fmt, 92, out)
    out.close()
    if not ok:
        raise RuntimeError("Bitmap 压缩失败")


def _capture_camera_photo(on_path):
    """调系统相机拍照，拍完复制到应用私有目录，回调 on_path(本地路径)。

    【踩坑记录】plyer 的安卓相机实现把 file:// URI 放进 Intent 传给系统相机，
    安卓 7（API 24）起跨应用传 file:// URI 会直接抛
    android.os.FileUriExposedException（targetSdk 越高越严格）。
    正确做法：先在 MediaStore 插入一条记录拿 content:// URI，把它作为
    EXTRA_OUTPUT 交给系统相机（带读写授权 flags），拍完后把内容流复制回
    应用私有目录——与"导入模型"同一套安全模式。
    """
    from jnius import autoclass, cast

    mActivity = autoclass("org.kivy.android.PythonActivity").mActivity
    Activity = autoclass("android.app.Activity")
    Intent = autoclass("android.content.Intent")
    MediaStore = autoclass("android.provider.MediaStore")
    MediaImages = autoclass("android.provider.MediaStore$Images$Media")
    ContentValues = autoclass("android.content.ContentValues")
    resolver = mActivity.getContentResolver()

    values = ContentValues()
    values.put("_display_name", "std_%d.jpg" % int(time.time()))
    values.put("mime_type", "image/jpeg")
    try:
        values.put("relative_path", "Pictures/SmartToxinDetection")  # 安卓 10+
    except Exception:
        pass
    uri = resolver.insert(MediaImages.EXTERNAL_CONTENT_URI, values)
    if uri is None:
        raise RuntimeError("无法创建媒体记录")

    req = _PICKER["next_req"]
    _PICKER["next_req"] += 1

    def handler(result_code, data):
        # ⚠ 本回调运行在安卓 UI 线程（Kivy 非线程安全）：
        # 只做 JNI/文件操作，界面更新一律 Clock.schedule_once 转交主线程
        _trace("camera: UIthread result_code=%d" % result_code)
        try:
            if result_code != Activity.RESULT_OK:
                _trace("camera: canceled, schedule on_path(None)")
                Clock.schedule_once(lambda dt: on_path(None), 0)
                return
            _trace("camera: result ok")
            # 【踩坑·确诊】两轮轨迹（第 13/14 轮）都表明：相机返回的 Intent
            # 一调 data.getData() 就原生层崩溃（python 的 try/except 拦不住），
            # 而选图器返回的 Intent 调同样的方法却没事。拍照用的是 EXTRA_OUTPUT，
            # 照片一定会写进我们自己插入的 MediaStore 记录，所以干脆完全不碰
            # 返回 Intent 的数据部分，直接用自己的 uri。
            target = uri
            _trace("camera: use own MediaStore uri")

            # 方案 A：查媒体记录的真实文件路径，让 PIL 直接打开 ——
            # 完全绕开 ContentResolver 流。上一轮轨迹显示崩溃发生在
            # openInputStream / 流读取一带（原生层），方案 A 走通就根本不碰流。
            # （应用自己插入的媒体记录，其真实路径对本体应用直接可读）
            real = None
            try:
                cur = resolver.query(target, None, None, None, None)
                if cur is not None:
                    if cur.moveToFirst():
                        idx = cur.getColumnIndex("_data")
                        if idx >= 0:
                            real = cur.getString(idx)
                    cur.close()
            except Exception as e:
                real = None
                _trace("camera: query fail " + str(e)[:100])
            _trace("camera: real path %s" % (real,))
            if real and os.path.isfile(real) and os.path.getsize(real) > 0:
                _trace("camera: direct path ok, schedule on_path")
                Clock.schedule_once(lambda dt, p=real: on_path(p), 0)
                return

            # 方案 B：ContentResolver 流复制（64KB 分块）
            dst = os.path.join(_private_dir(), "std_%d.jpg" % int(time.time()))
            copied = -1
            try:
                _trace("camera: stream opening")
                stream = resolver.openInputStream(target)
                _trace("camera: stream opened")
                copied = 0
                buf = bytearray(65536)
                with open(dst, "wb") as out:
                    while True:
                        n = stream.read(buf)
                        if copied == 0:
                            _trace("camera: first chunk n=%d" % n)
                        if n <= 0:
                            break
                        out.write(bytes(buf[:n]))
                        copied += n
                stream.close()
            except Exception as e:
                copied = -1
                _trace("camera: copy err " + str(e)[:100])
            _trace("camera: copied=%d bytes" % copied)
            if copied > 0:
                _trace("camera: schedule on_path")
                Clock.schedule_once(lambda dt, p=dst: on_path(p), 0)
                return

            # 方案 C：部分相机忽略 EXTRA_OUTPUT，只返回缩略图 Bitmap
            _trace("camera: bitmap fallback")
            bmp = None
            try:
                extras = data.getExtras()
                if extras is not None:
                    bmp = extras.get("data")
            except Exception as e:
                _trace("camera: extras fail " + str(e)[:80])
            if bmp is None:
                raise RuntimeError("相机未返回照片数据（三条取图路径都失败）")
            _save_bitmap(bmp, dst)
            _trace("camera: bitmap saved, schedule on_path")
            Clock.schedule_once(lambda dt, p=dst: on_path(p), 0)
        except Exception as e:
            _trace("camera: error " + str(e)[:120])
            Clock.schedule_once(lambda dt, err=e: on_path(None, err), 0)

    _PICKER["handlers"][req] = handler
    intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)
    # 【踩坑】pyjnius 无法把 Uri 自动匹配到 putExtra(String, Parcelable) 重载，
    # 会误选 (String, String) 版本报 "Invalid instance of 'android/net/Uri'
    # passed for a 'java/lang/String'"，必须用 cast 显式转成 Parcelable
    intent.putExtra(MediaStore.EXTRA_OUTPUT,
                    cast("android/os/Parcelable", uri))
    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
    _trace("camera: intent fired req=%d" % req)
    mActivity.startActivityForResult(intent, req)


# 模块加载的统一入口：此时 _ANDROID 已就绪、界面 Label 尚未创建，
# 在这里注册字体正好赶在第一个控件之前
_register_cjk_font()


# ---- 界面主题（浅灰底 + 白圆角卡片 + 青绿主色）-------------------------------
PAGE_BG = (0.945, 0.957, 0.965, 1)
TEAL = (0.13, 0.55, 0.47, 1)          # 主青绿
TEAL_DARK = (0.07, 0.42, 0.36, 1)     # 深青绿（实心按钮）
TEAL_LIGHT = (0.85, 0.94, 0.91, 1)    # 浅青绿（浅底按钮）
TEAL_TEXT = (0.10, 0.44, 0.38, 1)
INK = (0.15, 0.17, 0.18, 1)           # 正文
GRAY = (0.46, 0.50, 0.52, 1)          # 次要文字
RED = (0.78, 0.22, 0.18, 1)           # 浓度条默认色（微量红）
RED_LIGHT = (0.99, 0.92, 0.91, 1)
RED_TEXT = (0.78, 0.25, 0.22, 1)


class Card(BoxLayout):
    """白色圆角卡片容器（高度随内容自适应）。"""
    def __init__(self, **kw):
        super().__init__(orientation="vertical", padding=dp(14), spacing=dp(9),
                         size_hint_y=None, **kw)
        with self.canvas.before:
            Color(1, 1, 1, 1)
            self._rect = RoundedRectangle(radius=[dp(14)])
        self.bind(pos=self._upd, size=self._upd,
                  minimum_height=self.setter("height"))

    def _upd(self, *a):
        self._rect.pos = self.pos
        self._rect.size = self.size


class Flat(Button):
    """圆角扁平按钮（自带按下变暗反馈）。

    传 height 时自动设 size_hint_y=None，避免被父布局压成 0 高
    （【踩坑】Card 里直接放的按钮，光给 height 不给 size_hint_y=None，
    高度会被 Card 的 minimum_height 布局算成 0，只剩文字没有底色）。
    """
    def __init__(self, text, bg, fg, font_size="14sp", **kw):
        self._bg = bg
        if kw.get("height") is not None:
            kw.setdefault("size_hint_y", None)
        super().__init__(text=text, font_size=font_size, color=fg,
                         background_normal="", background_down="",
                         background_color=(0, 0, 0, 0), bold=True, **kw)
        with self.canvas.before:
            self._col = Color(*bg)
            self._rect = RoundedRectangle(radius=[dp(10)])
        self.bind(pos=self._upd, size=self._upd, state=self._on_state)

    def _upd(self, *a):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def _on_state(self, inst, st):
        r, g, b, a = self._bg
        f = 0.85 if st == "down" else 1.0
        self._col.rgb = (r * f, g * f, b * f)


class ColorBar(BoxLayout):
    """测算结果的颜色条，set_rgb() 显示照片实测色。"""
    def __init__(self, **kw):
        super().__init__(size_hint_y=None, height=dp(12), **kw)
        with self.canvas.before:
            self._col = Color(*RED)
            self._rect = RoundedRectangle(radius=[dp(6)])
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *a):
        self._rect.pos = self.pos
        self._rect.size = self.size

    def set_rgb(self, r, g, b):
        self._col.rgb = (r / 255.0, g / 255.0, b / 255.0)


def card_header(text):
    lbl = Label(text=f"[b]{text}[/b]", markup=True, color=TEAL_TEXT,
                font_size="14.5sp", halign="left", size_hint_y=None, height=dp(22))
    lbl.bind(width=lambda inst, w: setattr(inst, "text_size", (w, None)))
    return lbl


def body_label(text, color=INK, font_size="12.5sp", halign="left", **kw):
    lbl = Label(text=text, color=color, font_size=font_size, halign=halign,
                valign="top", size_hint_y=None, **kw)
    lbl.bind(width=lambda inst, w: setattr(inst, "text_size", (w, None)),
             texture_size=lambda inst, ts: setattr(inst, "height", max(ts[1], 1)))
    return lbl


class SmartToxinApp(App):
    title = f"{APP_NAME} v{APP_VERSION} (by {APP_AUTHOR})"

    # ---------------------------------------------------------------- 界面
    def build(self):
        if request_permissions is not None:
            try:
                request_permissions(_PERMS)
            except Exception:
                pass

        Window.clearcolor = PAGE_BG
        self.last_vec = None
        self.last_rgb = None

        page = ScrollView()
        root = GridLayout(cols=1, padding=dp(16), spacing=dp(12),
                          size_hint_y=None)
        root.bind(minimum_height=root.setter("height"))

        # 标题区
        title = Label(text=f"[b]{APP_NAME}[/b]", markup=True, font_size="21sp",
                      color=INK, halign="center", size_hint_y=None, height=dp(30))
        title.bind(width=lambda inst, w: setattr(inst, "text_size", (w, None)))
        root.add_widget(title)
        root.add_widget(body_label(
            f"试管毒素浓度测算 · 手机离线版 v{APP_VERSION} · 代码设计者：{APP_AUTHOR}",
            color=GRAY, font_size="11.5sp", halign="center"))

        # ① 加载模型
        c1 = Card()
        c1.add_widget(card_header("① 加载模型 .stmodel"))
        btn_model = Flat("＋ 选择便携模型文件", TEAL_LIGHT, TEAL_TEXT, height=dp(46))
        btn_model.bind(on_press=self.pick_model)
        c1.add_widget(btn_model)
        self.lbl_model = body_label(
            "未加载模型。请先在电脑端「模型库」导出 .stmodel，再传到手机。")
        c1.add_widget(self.lbl_model)
        c1.add_widget(body_label(
            "模型一旦加载就会记住在本机，下次打开无需重复选择。",
            color=GRAY, font_size="11sp"))
        root.add_widget(c1)

        # ② 采集照片
        c2 = Card()
        c2.add_widget(card_header("② 采集照片"))
        row2 = BoxLayout(spacing=dp(10), size_hint_y=None, height=dp(46))
        btn_photo = Flat("拍照测算", TEAL_DARK, (1, 1, 1, 1))
        btn_photo.bind(on_press=self.take_photo)
        btn_gallery = Flat("从相册选择", TEAL_LIGHT, TEAL_TEXT)
        btn_gallery.bind(on_press=self.pick_image)
        row2.add_widget(btn_photo)
        row2.add_widget(btn_gallery)
        c2.add_widget(row2)
        c2.add_widget(body_label(
            "拍摄要求与电脑端训练时一致：同一背景、同一距离、同一光照，"
            "试管置于画面正中央。", color=GRAY, font_size="11.5sp"))
        root.add_widget(c2)

        # ③ 测算结果
        c3 = Card()
        c3.add_widget(card_header("③ 测算结果"))
        self.color_bar = ColorBar()
        c3.add_widget(self.color_bar)
        self.lbl_conc = Label(text="尚未测算", font_size="26sp", color=INK,
                              halign="center", size_hint_y=None, height=dp(54))
        self.lbl_conc.bind(width=lambda inst, w: setattr(inst, "text_size", (w, None)))
        c3.add_widget(self.lbl_conc)
        self.lbl_rgb = body_label(" ", color=GRAY, font_size="12sp", halign="center")
        c3.add_widget(self.lbl_rgb)
        btn_detail = Flat("▶ 查看特征明细", TEAL_LIGHT, TEAL_TEXT,
                          font_size="12.5sp", height=dp(36))
        btn_detail.bind(on_press=self.toggle_detail)
        self.btn_detail = btn_detail
        c3.add_widget(btn_detail)
        self.lbl_detail = body_label("", color=INK, font_size="11.5sp")
        c3.add_widget(self.lbl_detail)
        root.add_widget(c3)

        # ④ 测算记录
        c4 = Card()
        self.lbl_records = card_header("④ 测算记录（0 条）")
        c4.add_widget(self.lbl_records)
        rec_scroll = ScrollView(size_hint_y=None, height=dp(120))
        self.lbl_log = body_label("暂无记录", color=GRAY, font_size="12sp")
        # 记录少时列表区跟着内容收缩（上限 150dp），避免大片空白
        self.lbl_log.bind(texture_size=lambda inst, ts: setattr(
            rec_scroll, "height", min(dp(150), ts[1] + dp(10))))
        rec_scroll.add_widget(self.lbl_log)
        c4.add_widget(rec_scroll)
        row4 = BoxLayout(spacing=dp(10), size_hint_y=None, height=dp(42))
        btn_export = Flat("导出 CSV", TEAL_LIGHT, TEAL_TEXT)
        btn_export.bind(on_press=self.export_csv)
        btn_clear = Flat("清空记录", RED_LIGHT, RED_TEXT)
        btn_clear.bind(on_press=self.clear_records)
        row4.add_widget(btn_export)
        row4.add_widget(btn_clear)
        c4.add_widget(row4)
        root.add_widget(c4)

        page.add_widget(root)

        self.model = None
        self.records = []
        self._auto_load_last()
        _trace("kivy: build done")
        return page

    def on_pause(self):
        _trace("lifecycle: on_pause")
        return True

    def on_resume(self):
        _trace("lifecycle: on_resume")

    def on_stop(self):
        _trace("app: exit")

    # ---------------------------------------------------------------- 模型
    def _auto_load_last(self):
        """启动时自动恢复上次使用的模型（记录在私有目录 last_model.txt）。"""
        marker = os.path.join(self.user_data_dir, "last_model.txt")
        if not os.path.isfile(marker):
            return
        try:
            with open(marker, encoding="utf-8") as f:
                path = f.read().strip()
            if path and os.path.isfile(path):
                self._load_model(path)
        except Exception:
            pass

    def _load_model(self, path: str):
        self.model = PortableModel(path)
        algo = ALGO_CN.get(self.model.spec.get("algo"), self.model.spec.get("algo", "?"))
        nf = len(self.model.spec.get("feature_names", []))
        m = self.model.spec.get("model", {})
        if m.get("type") == "knn":
            extra = f"{len(m.get('y', []))} 个训练样本"
        elif m.get("trees"):
            extra = f"{len(m['trees'])} 棵树"
        else:
            extra = "线性系数"
        self.lbl_model.text = (f"已加载：[{self.model.sample_type}] {self.model.model_name}\n"
                               f"{algo} ｜ 特征 {nf} 维 ｜ {extra}")
        try:
            with open(os.path.join(self.user_data_dir, "last_model.txt"), "w",
                      encoding="utf-8") as f:
                f.write(path)
        except Exception:
            pass

    def pick_model(self, *_):
        # 首选：系统文件选择器（安卓 11+/鸿蒙 分区存储下唯一能选到
        # Download/Documents 里 .stmodel 的方式）
        if _ANDROID:
            try:
                _pick_file("*/*", self._on_imported_model)
                return
            except Exception as e:
                self._alert(f"系统文件选择器启动失败：{e}\n改用内置浏览器。")
        # 后备：内置文件浏览器（老安卓可用；安卓 11+ 看不到非媒体文件）
        start = "/storage/emulated/0" if os.path.isdir("/storage/emulated/0") else "."
        fc = FileChooserListView(path=start, filters=["*.stmodel"])
        popup = Popup(title="选择 .stmodel 便携模型", content=fc, size_hint=(0.95, 0.9))
        fc.bind(on_submit=lambda inst, sel, touch: self._on_model(sel, popup))
        popup.open()

    def _on_imported_model(self, path, err=None):
        if err is not None:
            self._alert(f"导入模型失败：{err}")
            return
        if not path:
            return  # 用户取消
        try:
            self._load_model(path)
        except Exception as e:
            self._alert(f"模型加载失败：{e}")

    def _on_model(self, selection, popup):
        if not selection:
            return
        popup.dismiss()
        try:
            self._load_model(selection[0])
        except Exception as e:
            self._alert(f"模型加载失败：{e}")

    # ---------------------------------------------------------------- 采集
    def take_photo(self, *_):
        _trace("kivy: take_photo")
        if self.model is None:
            self._alert("请先选择便携模型（.stmodel）")
            return
        try:
            _capture_camera_photo(self._on_captured_photo)
        except Exception as e:
            self._alert(f"相机不可用：{e}\n可改用“选图测算”。")

    def _on_captured_photo(self, path, err=None):
        _trace("kivy: _on_captured_photo path=%s" % (path,))
        if err is not None:
            self._alert(f"拍照失败：{err}\n可改用“选图测算”。")
            return
        if path:
            self._predict_path(path)

    def pick_image(self, *_):
        if self.model is None:
            self._alert("请先选择便携模型（.stmodel）")
            return
        # 首选：系统文件选择器（相册 / 云盘 / 任意来源都能选，统一走 SAF）
        if _ANDROID:
            try:
                _pick_file("image/*", self._on_imported_image)
                return
            except Exception as e:
                self._alert(f"系统文件选择器启动失败：{e}\n改用内置浏览器。")
        # 后备：内置文件浏览器
        start = "/storage/emulated/0/DCIM" if os.path.isdir("/storage/emulated/0/DCIM") else "."
        fc = FileChooserListView(path=start, filters=["*.jpg", "*.jpeg", "*.png"])
        popup = Popup(title="选择试管照片", content=fc, size_hint=(0.95, 0.9))
        fc.bind(on_submit=lambda inst, sel, touch: self._on_image(sel, popup))
        popup.open()

    def _on_imported_image(self, path, err=None):
        if err is not None:
            self._alert(f"导入照片失败：{err}")
            return
        if path:
            self._predict_path(path)

    def _on_image(self, selection, popup):
        if selection and os.path.isfile(selection[0]):
            popup.dismiss()
            self._predict_path(selection[0])

    # ---------------------------------------------------------------- 推理
    def _predict_path(self, path):
        _trace("kivy: predict start %s" % path)
        try:
            from PIL import Image
            img = Image.open(path).convert("RGB")
            vec = self.model.feature_vector(img)
            conc = self.model.predict(img)
            r, g, b = vec[0] * 255, vec[1] * 255, vec[2] * 255
            self.lbl_conc.text = f"{conc:.4f}"
            self.lbl_rgb.text = f"R {r:.0f} · G {g:.0f} · B {b:.0f}"
            self.color_bar.set_rgb(r, g, b)
            self.last_vec = vec
            self.last_rgb = (r, g, b)
            stamp = time.strftime("%m-%d %H:%M:%S")
            self.records.insert(0, f"{stamp}  {os.path.basename(path)}  →  {conc:.4f}")
            self.lbl_log.text = "\n".join(self.records[:30])
            self._upd_record_count()
            self._save_record(stamp, os.path.basename(path), conc, (r, g, b))
            _trace("kivy: predict done conc=%.4f" % conc)
        except Exception as e:
            _trace("kivy: predict error " + str(e)[:120])
            self._alert(f"测算失败：{e}")

    def toggle_detail(self, *_):
        """展开 / 收起 13 维特征明细。"""
        if self.last_vec is None:
            self._alert("还没有测算结果，先拍照或从相册选一张照片。")
            return
        if self.lbl_detail.text:
            self.lbl_detail.text = ""
            self.btn_detail.text = "▶ 查看特征明细"
            return
        names = self.model.spec.get("feature_names", [])
        lines = []
        for i, v in enumerate(self.last_vec):
            name = names[i] if i < len(names) else f"特征{i + 1}"
            lines.append(f"{name}   {v:.3f}")
        self.lbl_detail.text = "\n".join(lines)
        self.btn_detail.text = "━ 收起特征明细"

    def _upd_record_count(self):
        self.lbl_records.text = f"[b]④ 测算记录（{len(self.records)} 条）[/b]"

    def export_csv(self, *_):
        """把测算记录导出为 CSV（安卓走系统“保存到…”对话框，用户选位置）。"""
        fp = os.path.join(self.user_data_dir, "手机测算记录.csv")
        if not self.records or not os.path.isfile(fp):
            self._alert("还没有测算记录，先拍照或从相册测算一次。")
            return
        if _ANDROID:
            try:
                _create_document("text/csv", "手机测算记录.csv", fp, self._on_exported)
                return
            except Exception as e:
                self._alert(f"导出启动失败：{e}")
                return
        # 非 Android（电脑开发调试）：复制到当前目录
        try:
            import shutil
            shutil.copyfile(fp, os.path.join(os.getcwd(), "手机测算记录.csv"))
            self._alert("已导出到程序目录：手机测算记录.csv")
        except Exception as e:
            self._alert(f"导出失败：{e}")

    def _on_exported(self, result, err=None):
        if err is not None:
            self._alert(f"导出失败：{err}")
        elif result == "ok":
            self._alert("已导出 CSV。可在文件管理器的「下载」目录\n（或导出时选择的位置）找到它。")
        # result None = 用户取消，不打扰

    def clear_records(self, *_):
        if not self.records:
            self._alert("当前没有可清空的记录。")
            return
        self.records = []
        self.lbl_log.text = "暂无记录"
        self._upd_record_count()
        try:
            os.remove(os.path.join(self.user_data_dir, "手机测算记录.csv"))
        except Exception:
            pass
        self._alert("已清空全部测算记录。")

    def _save_record(self, stamp, fname, conc, rgb):
        """追加写入手机端测算历史（CSV，UTF-8 BOM 便于 Excel 打开）。"""
        fp = os.path.join(self.user_data_dir, "手机测算记录.csv")
        try:
            new = not os.path.isfile(fp)
            with open(fp, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["时间", "照片", "浓度", "R", "G", "B", "设计者"])
                w.writerow([stamp, fname, f"{conc:.4f}",
                            f"{rgb[0]:.0f}", f"{rgb[1]:.0f}", f"{rgb[2]:.0f}", APP_AUTHOR])
        except Exception:
            pass

    def _alert(self, msg):
        box = BoxLayout(orientation="vertical", padding=dp(12))
        lbl = body_label(msg, color=INK, font_size="13sp")
        box.add_widget(lbl)
        popup = Popup(title="提示", content=box, size_hint=(0.88, None), height=dp(120))
        # 高度跟随文字实际行数，避免文字超出弹窗（之前轨迹弹窗文字重叠的教训）
        lbl.bind(texture_size=lambda inst, ts: setattr(
            popup, "height", min(Window.height * 0.7, ts[1] + dp(64))))
        popup.open()


if __name__ == "__main__":
    _trace("app: main start")
    try:
        SmartToxinApp().run()
    except SystemExit:
        pass
    except Exception:
        # 启动失败时把堆栈弹到屏幕上并写入 crash.log，方便用户截图反馈
        try:
            _report_crash()
        except Exception:
            pass
        raise
