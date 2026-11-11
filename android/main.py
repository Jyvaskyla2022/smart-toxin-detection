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
        start = "/storage/emulated/0" if os.path.isdir("/storage/emulated/0") else "."
        fc = FileChooserListView(path=start, filters=["*.stmodel"])
        popup = Popup(title="选择 .stmodel 便携模型", content=fc, size_hint=(0.95, 0.9))
        fc.bind(on_submit=lambda inst, sel, touch: self._on_model(sel, popup))
        popup.open()

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
        start = "/storage/emulated/0/DCIM" if os.path.isdir("/storage/emulated/0/DCIM") else "."
        fc = FileChooserListView(path=start, filters=["*.jpg", "*.jpeg", "*.png"])
        popup = Popup(title="选择试管照片", content=fc, size_hint=(0.95, 0.9))
        fc.bind(on_submit=lambda inst, sel, touch: self._on_image(sel, popup))
        popup.open()

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
    SmartToxinApp().run()
