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
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView

from portable_model import PortableModel

# ---- 中文支持 -------------------------------------------------------------
# Kivy 默认字体（Roboto）不含 CJK 字形，安卓上所有中文都会显示成方块。
# 方案：把随 APK 打包的 DroidSansFallback.ttf 注册为默认字体名 "Roboto"。
# 注册统一在模块加载末尾执行（_register_cjk_font），字体文件三级查找：
#   1) p4a 正常解包路径  app目录/fonts/DroidSansFallback.ttf
#   2) app目录 根下
#   3) 从 APK assets 现场复制到应用私有目录再注册（解包缺失时的兜底）
# 结果记录在 _FONT_STATUS，显示在界面底部一行小字（纯 ASCII），方便截图排查。
_FONT_NAME = "DroidSansFallback.ttf"
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_FONT_CANDIDATES = [
    os.path.join(_APP_DIR, "fonts", _FONT_NAME),
    os.path.join(_APP_DIR, _FONT_NAME),
    "/sdcard/SmartToxinDetection/fonts/" + _FONT_NAME,
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
                      "app/fonts/" + _FONT_NAME):
            try:
                stream = am.open(asset)
            except Exception:
                continue
            try:
                dst = os.path.join(dst_dir, _FONT_NAME)
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
        if result_code != Activity.RESULT_OK or data is None:
            on_path(None)
            return
        try:
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
                name = f"imported_{int(time.time())}"
            # 2) 把内容流复制到应用私有目录（分区存储下唯一可靠的读取方式）
            user_dir = App.get_running_app().user_data_dir
            dst = os.path.join(user_dir, name)
            stream = resolver.openInputStream(uri)
            buf = bytearray(65536)
            with open(dst, "wb") as out:
                while True:
                    n = stream.read(buf)   # jnius 支持 bytearray 输出缓冲
                    if n <= 0:
                        break
                    out.write(bytes(buf[:n]))
            stream.close()
            on_path(dst)
        except Exception as e:
            on_path(None, e)

    _PICKER["handlers"][req] = handler
    intent = Intent(Intent.ACTION_GET_CONTENT)
    intent.setType(mime)
    intent.addCategory(Intent.CATEGORY_OPENABLE)
    mActivity.startActivityForResult(
        Intent.createChooser(intent,
                             cast("java.lang.CharSequence", String("选择文件"))),
        req)


# 模块加载的统一入口：此时 _ANDROID 已就绪、界面 Label 尚未创建，
# 在这里注册字体正好赶在第一个控件之前
_register_cjk_font()


class SmartToxinApp(App):
    title = f"{APP_NAME} v{APP_VERSION} (by {APP_AUTHOR})"

    # ---------------------------------------------------------------- 界面
    def build(self):
        if request_permissions is not None:
            try:
                request_permissions(_PERMS)
            except Exception:
                pass

        root = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))

        root.add_widget(Label(
            text=f"[b]{APP_NAME}[/b]  v{APP_VERSION}\n代码设计者：{APP_AUTHOR}",
            markup=True, halign="center", size_hint_y=None, height=dp(58),
            font_size="15sp"))

        self.lbl_model = Label(text="模型：未加载（点“选择模型”）", halign="left",
                               size_hint_y=None, height=dp(46),
                               text_size=(Window.width - dp(20), None), font_size="12sp")
        root.add_widget(self.lbl_model)

        btns = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        btns.add_widget(Button(text="选择模型", on_press=self.pick_model, font_size="13sp"))
        btns.add_widget(Button(text="拍照测算", on_press=self.take_photo, font_size="13sp"))
        btns.add_widget(Button(text="选图测算", on_press=self.pick_image, font_size="13sp"))
        root.add_widget(btns)

        self.lbl_result = Label(
            text="测算结果将显示在这里\n\n拍摄条件要与电脑端训练时一致\n（同背景、同距离、同光照）",
            halign="center", valign="middle", font_size="20sp", color=(0.70, 0.14, 0.12, 1))
        root.add_widget(self.lbl_result)

        root.add_widget(Label(text="最近测算记录", size_hint_y=None, height=dp(24),
                              halign="left", font_size="12sp"))
        scroll = ScrollView()
        self.lbl_log = Label(text="", halign="left", valign="top", size_hint_y=None,
                             font_size="12sp")
        self.lbl_log.bind(width=lambda inst, w: setattr(inst, "text_size", (w, None)),
                          texture_size=lambda inst, ts: setattr(inst, "height", ts[1]))
        scroll.add_widget(self.lbl_log)
        root.add_widget(scroll)

        # 字体诊断行（纯 ASCII，任何状态下都可读；中文正常时它无存在感，
        # 中文变方块时请把这行截图发给开发者）
        self.lbl_diag = Label(text=_FONT_STATUS[:110], size_hint_y=None,
                              height=dp(24), halign="left", font_size="10sp",
                              color=(0.45, 0.50, 0.49, 1),
                              text_size=(Window.width - dp(20), None))
        root.add_widget(self.lbl_diag)

        self.model = None
        self.records = []
        self._auto_load_last()
        return root

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
        self.lbl_model.text = (f"模型：[{self.model.sample_type}] {self.model.model_name}\n"
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
        if self.model is None:
            self._alert("请先选择便携模型（.stmodel）")
            return
        try:
            from plyer import camera
            # 安卓上 plyer 需要绝对路径，否则拍照保存失败
            filename = os.path.join(self.user_data_dir, f"std_{int(time.time())}.jpg")
            camera.take_picture(filename=filename, on_complete=self._on_photo)
        except Exception as e:
            self._alert(f"相机不可用：{e}\n可改用“选图测算”。")

    def _on_photo(self, path):
        if path and os.path.isfile(path):
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
        try:
            from PIL import Image
            img = Image.open(path).convert("RGB")
            vec = self.model.feature_vector(img)
            conc = self.model.predict(img)
            r, g, b = vec[0] * 255, vec[1] * 255, vec[2] * 255
            self.lbl_result.text = (f"测算浓度：{conc:.4f}\n"
                                   f"R {r:.0f} / G {g:.0f} / B {b:.0f}")
            stamp = time.strftime("%m-%d %H:%M:%S")
            self.records.insert(0, f"{stamp}  {os.path.basename(path)}  →  {conc:.4f}")
            self.lbl_log.text = "\n".join(self.records[:30])
            self._save_record(stamp, os.path.basename(path), conc, (r, g, b))
        except Exception as e:
            self._alert(f"测算失败：{e}")

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
        Popup(title="提示",
              content=Label(text=msg, text_size=(Window.width * 0.8, None)),
              size_hint=(0.85, 0.4)).open()


if __name__ == "__main__":
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
