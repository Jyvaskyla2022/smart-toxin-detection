# Smart Toxin Detection（智能毒素浓度检测）v2.0

> **代码设计者：PhLi**
> 基于机器学习的溶液浓度检测客户端：导入「浓度 + 试管照片」训练模型 → 任意照片 / 摄像头实时测算浓度。支持多样品、模型自命名保存调用、隐藏手工矫正、便携模型导出至安卓端。

## 功能特性

- 📸 **数据管理**：导入试管照片，文件名自动识别浓度 / CSV 对照表导入，双击改浓度
- 🚀 **模型训练**：6 种回归算法，参数可视化调整，后台训练，自动评估（测试集+交叉验证）+ 散点图
- 🔮 **浓度测算**：
  - 上传照片 / 批量文件夹测算，结果导出 CSV
  - **电脑摄像头实时测算**：实时画面 + 实时 RGB + 实时浓度
  - **手机IP摄像头**：手机装 IP Webcam 类 App 接入局域网即可当无线摄像头
  - 每次测算自动留痕 `prediction_history.csv`，截图存 `captures/`
- 🛠 **隐藏手工矫正**：测算结果右键（或 Ctrl+M）→ 录入真实浓度 → 自动回流训练集 → 可一键原参数重训
- 💾 **模型库**：模型自动保存 `.tubejob`，自命名、版本对比、删除、跨机迁移
- 📦 **便携模型导出**：一键导出纯 JSON `.stmodel`，安卓 App / 手机网页版离线推理，三端结果一致
- 📱 **手机网页版**：单文件 HTML（`web/`），浏览器打开即用、免打包、可添加到主屏幕；程序菜单「文件 → 导出手机网页版」一键导出
- 🤖 **安卓版（两条实现）**：
  - `android_native/` —— 原生 WebView 壳（已编译好 `installer\SmartToxinDetection_v2.0.0.apk`，`python android_native\build_apk.py` 一键重编，工具链走国内镜像，**无需 WSL/Linux**）
  - `android/` —— Kivy 原生 Python 版（buildozer 打包，需 Linux，见 android/README_构建指南.md）
- 📖 **从0开始操作手册**：`docs/Smart Toxin Detection 从0开始操作手册.docx`（含电脑端、手机网页版、安卓 APK 三章 + 常见问题）

## 目录结构

```
SmartToxinDetection/
├── main.py                  # 电脑客户端主程序（GUI 入口）
├── core/
│   ├── features.py          # 颜色特征提取（纯 numpy 公式，与安卓端逐行对应）
│   ├── dataset.py           # 数据集与样品类型管理
│   ├── train.py             # 训练与测算（6 种算法 + 交叉验证）
│   └── storage.py           # 模型保存/加载 + 便携模型(.stmodel)导出
├── android/                 # 安卓端（Kivy）
│   ├── main.py              # App 界面（拍照/选图测算）
│   ├── portable_model.py    # 便携推理引擎（无 sklearn 依赖）
│   ├── buildozer.spec       # APK 打包配置（作者 PhLi）
│   ├── build_apk.sh         # Linux/WSL 一键打包脚本
│   ├── 一键打包APK.bat       # Windows 侧调用 WSL 打包
│   └── README_构建指南.md
├── web/
│   └── SmartToxinDetection.html  # 手机网页版（单文件离线）
├── docs/
│   ├── 从0开始操作手册.md    # 完整手册（Markdown 源）
│   ├── md2docx.py           # 手册转 Word 脚本
│   └── Smart Toxin Detection 从0开始操作手册.docx
├── tests/
│   ├── smoke_test.py        # 全流程冒烟测试
│   ├── parity_test.py       # 双端推理一致性测试（必须通过）
│   └── web_parity_test.py   # 三端一致性测试（需 Node）
├── build_windows.bat        # 一键构建（依赖→测试→PyInstaller→安装包）
├── installer/               # 分发包
│   ├── SmartToxinDetection_Setup_v2.0.0.exe   # 单文件安装包（双击安装）
│   └── SmartToxinDetection_v2.0.0_绿色版.zip   # 绿色版压缩包
├── packaging/
│   ├── installer_app.py     # 安装程序源码（编译成 Setup.exe）
│   ├── uninstall_app.py     # 卸载程序源码
│   ├── make_installer.py    # 合成单文件安装包
│   └── installer.iss        # Inno Setup 备用脚本（可选）
├── requirements.txt
└── 使用教程.md
```

## 快速开始（源码运行）

```bash
pip install -r requirements.txt
python main.py
```

## 打包为 Windows 安装程序

1. 双击 `build_windows.bat`（自动建环境 → 跑测试 → PyInstaller 打包），产物：`dist\SmartToxinDetection\SmartToxinDetection.exe`
2. 安装 [Inno Setup 6](https://jrsoftware.org/isdl.php)
3. 把 `dist\SmartToxinDetection` 复制为 `packaging\app\`
4. 用 Inno Setup 编译 `packaging\installer.iss` → 得到安装程序

## 安卓版

详见 `android/README_构建指南.md`（需 Linux/WSL + buildozer）。流程：电脑端导出 `.stmodel` → 拷到手机 → App 内选择 → 拍照测算。

## 技术要点

- 特征（双端统一）：中心 ROI 内 RGB 均值/标准差、纯 numpy 浮点 HSV（色相圆均值）均值/标准差、加权灰度；**不依赖 OpenCV 8-bit 量化**，保证双端逐位一致
- 管线：StandardScaler + 回归器（sklearn），特征配置随模型序列化
- 便携推理：树模型递归序列化为 JSON；GBRT 按 `init + lr×Σ树` 还原；KNN 存样本矩阵
- 中文路径：OpenCV 用 `np.fromfile + imdecode`
- 质量门禁：`smoke_test.py`（功能）+ `parity_test.py`（双端一致性，逐位校验）

详细使用方法见 **使用教程.md**。
