# -*- coding: utf-8 -*-
"""Smart Toxin Detection —— 便携模型推理引擎（供安卓端）

程序名称 : Smart Toxin Detection
代码设计 : PhLi

无 kivy / sklearn 依赖，仅 numpy + Pillow：
加载电脑端导出的 .stmodel（纯 JSON）并离线推理，特征定义与电脑端完全一致。
"""
import json

import numpy as np


class PortableModel:
    """加载 .stmodel（JSON）并推理。支持 linear / forest / knn。"""

    def __init__(self, path: str):
        with open(path, encoding="utf-8") as f:
            self.spec = json.load(f)
        if self.spec.get("format") != "stmodel":
            raise ValueError("不是有效的 .stmodel 便携模型文件")
        self.fcfg = self.spec.get("feature_cfg", {})
        self.scaler = self.spec["scaler"]
        self.model = self.spec["model"]
        self.sample_type = self.spec.get("sample_type", "?")
        self.model_name = self.spec.get("model_name", "?")

    # ---- 特征 ----
    def feature_vector(self, img) -> np.ndarray:
        """img: PIL.Image（RGB 模式）。返回与电脑端完全一致的特征向量。

        ⚠ 本方法与 core/features.py 的 _compute_features 逐行对应（双端统一纯
        numpy 浮点公式），一致性由 tests/parity_test.py 守护；修改必须双端同步。
        """
        w, h = img.size
        ratio = float(self.fcfg.get("roi_ratio", 0.5))
        rw, rh = max(1, int(w * ratio)), max(1, int(h * ratio))
        left, top = (w - rw) // 2, (h - rh) // 2
        roi = img.crop((left, top, left + rw, top + rh))

        rgb01 = np.asarray(roi, dtype=np.uint8).astype(np.float32) / np.float32(255.0)

        feats = []
        if self.fcfg.get("use_rgb", True):
            feats.append(rgb01.reshape(-1, 3).mean(axis=0))
        if self.fcfg.get("use_rgb_std", True):
            feats.append(rgb01.reshape(-1, 3).std(axis=0))
        if self.fcfg.get("use_hsv", True):
            r = rgb01[..., 0]
            g = rgb01[..., 1]
            b = rgb01[..., 2]
            maxc = np.maximum(np.maximum(r, g), b)
            minc = np.minimum(np.minimum(r, g), b)
            delta = maxc - minc
            v = maxc
            s = np.where(maxc > 0, delta / np.maximum(maxc, np.float32(1e-12)), np.float32(0.0))
            safe = np.where(delta == 0, np.float32(1.0), delta)
            rc = (maxc - r) / safe
            gc = (maxc - g) / safe
            bc = (maxc - b) / safe
            h = np.where(maxc == r, bc - gc,
                         np.where(maxc == g, np.float32(2.0) + rc - bc,
                                  np.float32(4.0) + gc - rc))
            h = (h / np.float32(6.0)) % np.float32(1.0)
            h = np.where(delta == 0, np.float32(0.0), h).astype(np.float32)
            s = s.astype(np.float32)
            v = v.astype(np.float32)
            ang = h * np.float32(2.0 * np.pi)
            h_mean = (np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())
                      / np.float32(2.0 * np.pi)) % np.float32(1.0)
            feats.append(np.array([h_mean, s.mean(), v.mean()], dtype=np.float32))
            hsv_arr = np.stack([h, s, v], axis=-1)
            feats.append(hsv_arr.reshape(-1, 3).std(axis=0))
        if self.fcfg.get("use_gray", True):
            r = rgb01[..., 0]
            g = rgb01[..., 1]
            b = rgb01[..., 2]
            gray = r * np.float32(0.299) + g * np.float32(0.587) + b * np.float32(0.114)
            feats.append(np.array([gray.mean()], dtype=np.float32))
        return np.concatenate(feats).astype(np.float32)

    # ---- 预处理 ----
    def _scale(self, x: np.ndarray) -> np.ndarray:
        mean = np.asarray(self.scaler["mean"], dtype=np.float64)
        scale = np.asarray(self.scaler["scale"], dtype=np.float64)
        return (x.astype(np.float64) - mean) / np.where(scale == 0, 1e-12, scale)

    # ---- 推理 ----
    def predict(self, img) -> float:
        x = self._scale(self.feature_vector(img))
        m = self.model
        if m["type"] == "linear":
            return float(np.dot(x, np.asarray(m["coef"])) + m["intercept"])
        if m["type"] == "forest":
            vals = [self._predict_tree(t, x) for t in m["trees"]]
            return float(np.mean(vals))
        if m["type"] == "boost":
            vals = sum(self._predict_tree(t, x) for t in m["trees"])
            return float(m["init"] + m["lr"] * vals)
        if m["type"] == "knn":
            X = np.asarray(m["X"], dtype=np.float64)
            y = np.asarray(m["y"], dtype=np.float64)
            d = np.sqrt(((X - x) ** 2).sum(axis=1))
            k = min(m["k"], len(y))
            idx = np.argsort(d)[:k]
            return float(y[idx].mean())
        raise ValueError(f"便携模型暂不支持该算法类型: {m['type']}")

    def _predict_tree(self, node: dict, x: np.ndarray) -> float:
        while "v" not in node:
            branch = "l" if x[node["f"]] <= node["th"] else "r"
            node = node[branch]
        return float(node["v"])
