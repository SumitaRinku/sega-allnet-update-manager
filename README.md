# SEGA ALL.NET Update Manager

现代化 GUI 工具：向 SEGA ALL.NET 支持的游戏发送 downloadOrder，获取更新包资源列表，选择性下载并解密解包。

![icon](icon.ico)

## 功能

- **downloadOrder 双协议**：V1（naominet.jp，zlib+Base64）与 Lite（WAHLAP 中国服务器，AES-CBC 加密）
- **APP + OPT 双订单**：主 hello 只拿到 OPT 时，自动用递减版本补充 hello 获取 APP 程序补丁订单（如 SDGB 1.56 → 1.55 的 patch 订单）
- **分栏资源列表**：APP（游戏程序）/ OPT（内容数据）分组显示，逐文件勾选下载 / 解密
- **多线程分段下载**：自动探测 Range 支持，8 连接并发分段（实测可突破单连接限速约 7 倍），分段独立断点续传
- **断点续传 + 自动重试**：失败后 3 秒重试，从已下载位置继续；已存在的文件跳过下载
- **AES 解密**：按 sega-image-decryption 契约（跳过 0x200000 头 + 0x1000 块 CBC，per-block IV 派生），解密进度实时显示
- **OPT 镜像提取**：解密后的 exFAT 镜像自动提取内容到文件夹（FATtools）
- **原生高 DPI**：PySide6 (Qt) 渲染，混合 DPI 多屏下文字清晰、无抖动拖影
- **订单元数据**：显示 ORDER_TIME / RELEASE_TIME / 描述

## 使用

从 [Releases](../../releases) 下载 `SegaUpdateManager.exe` 单文件直接运行。

1. 选择游戏 ID，填写版本号（Title Ver，如 `1.56`、`A074`）
2. 点击「发送 downloadOrder」获取资源列表
3. 勾选要下载 / 解密的文件，选择保存目录，点击「下载选中资源」

## 源码运行

```powershell
pip install PySide6 pycryptodome FATtools
python sega_update_manager.py
```

## 打包 exe

```powershell
pyinstaller --noconfirm --clean --onefile --windowed --name SegaUpdateManager ^
  --icon icon.ico --add-data "icon.ico;." --collect-all FATtools ^
  --add-data "modules\orderopt_model.py;modules" ^
  --add-data "modules\sega_decrypt_to_file.py;modules" ^
  --add-data "modules\sega_key_iv.py;modules" sega_update_manager.py
```

## 项目结构

```
sega_update_manager.py   # 主程序（PySide6 GUI）
modules/
  orderopt_model.py      # downloadOrder 协议实现（V1 + Lite）
  sega_decrypt_to_file.py# 镜像解密（CBC 分块，per-block IV）
  sega_key_iv.py         # 解密密钥与 IV 猜测
icon.ico                 # 应用图标
```

## 许可证

[GPL-2.0](LICENSE)

## 免责声明

本项目仅供学习与研究 ALL.NET 分发协议使用。下载、解密任何内容请在获得授权的前提下进行，使用者自行承担一切责任。
