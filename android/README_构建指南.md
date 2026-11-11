# Smart Toxin Detection · 安卓版构建指南（代码设计者：PhLi）

> 安卓版为**离线推理 App**：电脑端点「导出便携模型(.stmodel)」，把 `.stmodel` 拷到手机，
> App 内选择后即可拍照/选图测算浓度。训练只在电脑端完成——手机端只做推理，
> 避免了在安卓上装 scikit-learn 的兼容性问题，APK 体积也小得多。
>
> **不想打 APK？** 同目录的网页版（`web/SmartToxinDetection.html`）无需打包，
> 手机浏览器打开即用，推理结果与 App 完全一致。详见《docs/从0开始操作手册.md》第 2 章。

## 一、工作原理

```
电脑端（训练）                          手机端（推理）
12组照片+浓度                          ① 选择 .stmodel 模型
  ↓ Smart Toxin Detection               ② 拍照 / 选图
  训练模型(.tubejob)                    ③ 纯浮点特征提取(RGB/HSV/灰度+中心ROI)
  ↓ 导出便携模型(.stmodel JSON)  ──拷贝→  ④ 树/线性/KNN 纯JSON推理
                                        ⑤ 显示浓度（历史CSV自动记录）
```

便携模型支持算法：随机森林、梯度提升树、线性回归、岭回归、KNN（SVR 不支持）。

三端一致性由两套测试守护：
- `tests/parity_test.py`：电脑端 ↔ 安卓端（特征 0 差异，预测 ≤2.3e-7）
- `tests/web_parity_test.py`：电脑端 ↔ 网页端（特征 ≤1.6e-6，预测 ≤3.8e-5）

## 二、三条构建路线

| 路线 | 需要什么 | 一句话概括 |
| --- | --- | --- |
| **A. GitHub Actions** | 仅 GitHub 账号 | 推代码 → Actions 点一下 → 下载 APK |
| **B. WSL2 + 一键脚本** | Windows 10/11 + WSL2 | 双击 `一键打包APK.bat` |
| **C. Ubuntu 虚拟机/服务器** | 一台 Linux | `bash build_apk.sh` |

## 三、路线 A：GitHub Actions（推荐，无需本地环境）

1. 注册/登录 <https://github.com>，`New repository` 创建仓库。
2. 把**整个 SmartToxinDetection 文件夹内容**上传（网页拖拽即可，注意勾选显示隐藏文件，`.github/` 目录必须传上去）。
3. 仓库页 `Actions` → `Build Android APK` → `Run workflow`。
4. 等待约 40-60 分钟（首次要下载 Android SDK/NDK）→ 运行页底部 `Artifacts` 下载 `SmartToxinDetection-apk` → 解压即 APK。

工作流文件：`.github/workflows/build-apk.yml`（Ubuntu 22.04 + Python 3.11 + buildozer stable，
已启用 `~/.buildozer` 缓存，第二次打包通常 15 分钟内完成）。

## 四、路线 B：WSL2（本机打包）

```powershell
# 1. 管理员 PowerShell 安装 WSL2 + Ubuntu
wsl --install -d Ubuntu
# 重启电脑，设置 Linux 用户名与密码
```

然后双击 `android\一键打包APK.bat`。脚本自动完成：
检查 WSL → 安装 JDK17/依赖 → 安装 buildozer → 下载 SDK/NDK → 编译 → APK 复制到 `dist\`。

也可在 WSL 内手动执行：

```bash
cd /mnt/d/SmartToxinDetection/android    # 按实际路径
bash build_apk.sh            # debug 版，直接可装
bash build_apk.sh release    # release 版（未签名）
```

`build_apk.sh` 使用独立虚拟环境 `.venv`（在 android 目录内），不污染系统 Python。

## 五、路线 C：Ubuntu 虚拟机 / 云服务器

```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip python3-venv \
                    autoconf libtool pkg-config zlib1g-dev libncurses-dev \
                    libncursesw5-dev libtinfo6 cmake libffi-dev libssl-dev
cd android && bash build_apk.sh
```

## 六、打包常见报错

| 报错关键词 | 原因 | 解决 |
| --- | --- | --- |
| `Aidl not found` / SDK 许可 | 许可未接受 | spec 已设 `android.accept_sdk_license=True`；仍报错删 `~/.buildozer` 重跑 |
| `NDK download failed` | 网络（NDK 约 1 GB） | 换网/代理；或手动下载放入 `~/.buildozer/android/platform/` |
| `Unsupported class file major version` | JDK 版本不对 | 装 JDK 17，`export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64` |
| `Cython` 编译错误 | Cython 3 不兼容 | `pip install "cython<3.0"`（脚本已固定） |
| `Killed` | 内存不足 | 只留 `android.archs = arm64-v8a`；WSL 配 8GB 内存 |
| 相机无响应 | 运行时权限未给 | 手机设置 → 应用 → 权限，允许相机/存储 |
| APK 闪退 | 缺 portable_model.py | 确认 `android/` 内 main.py、portable_model.py、buildozer.spec 三件齐全 |

## 七、安装到手机

1. APK 传到手机（数据线/网盘；微信点开常被拦，建议文件管理器打开）。
2. 点开 APK →「未知来源」→ 允许 → 安装。
3. 首次启动授予相机 + 存储权限。
4. 点 `选择模型` → 选中 `Download` 里的 `.stmodel` → 拍照测算。
5. 测算历史写入：`Android/data/org.phli.smarttoxindetection/files/手机测算记录.csv`。

## 八、版本信息

- 程序名：Smart Toxin Detection　包名：org.phli.smarttoxindetection
- 版本：2.0.0　作者：PhLi
- 目标：api 34 / 最低 api 24（Android 7.0+）
- 依赖：kivy 2.3.0 / numpy / pillow / plyer
