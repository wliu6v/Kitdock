# Photo Organizer · 照片整理

把 iPhone、安卓导出的照片、视频和配套文件复制到同一个目录，按拍摄时间和可用地点统一命名。初版不改动原件、不转换图片格式。

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 状态 | 初版，可从源码运行；尚未提供独立安装包 |
| 实现语言 | Python 3.11+；窗口使用 PySide6 / Qt |
| 开发工具链 | 子项目 `.tool-versions` 选择 asdf Python 3.11.5 |
| 用户运行依赖 | Python、ExifTool；窗口额外需要 PySide6-Essentials |
| 入口 | `photo-organizer` / `photo-organizer-gui` / `python -m photo_organizer` |
| 仓库共享组件 | 无，可单独复制本工具目录 |

## 已实现

- 一个或多个输入目录，递归扫描并汇总到同一个输出目录。无需固定 iPhone / Android 目录名。
- `20261001_123040_重庆市李子坝.heic` 格式；无地点时省略地点；同秒不同内容加 `_02`、`_03` 等序号。
- 支持 HEIC / HEIF / JPG / JPEG / PNG / DNG / TIFF / WEBP / AVIF、MOV / MP4 / M4V / AVI / 3GP / 3G2，以及 AAE / XMP。保留原始字节，扩展名统一小写。
- 同目录、同原始主文件名的配套文件使用同一输出主文件名；同目录中可读取到相同 Apple ContentIdentifier 的文件也会合组。图片时间优先。
- 窗口选择或拖入多个目录；可修改完整导出路径，也可只改目录名。
- 扫描、读取信息、整理三个阶段的进度，显示已处理数 / 总数，支持取消和预览。
- SHA-256 校验、相同整组跳过、重名防覆盖、取消后补齐同组、逐文件 JSONL 报告。

## 安装与启动

以下命令均在本工具目录执行。

### macOS 开发环境

使用 asdf 现有安装，不修改全局版本：

```sh
asdf current python
asdf list python
# 仅在没有项目指定版本时：
asdf install python 3.11.5
python -m venv .venv
.venv/bin/python -m pip install -e '.[gui]'
```

安装 [ExifTool](https://exiftool.org/install.html)，确保 `exiftool` 位于 PATH；也可在窗口中填写程序完整路径，或通过 `--exiftool` 指定。官方 Perl 版本需保留它旁边的 `lib` 目录。

```sh
.venv/bin/photo-organizer --gui
# 或双击 launch.command
```

如果把官方 ExifTool 放到 `bin/exiftool/exiftool`，`launch.command` 会自动选择它。`bin/` 和 `.venv/` 不提交；这不是包含依赖的发行包。

### Windows

安装原生 Python 3.11+（无需 asdf / WSL / Git Bash）。安装 ExifTool Windows 版，将 `exiftool(-k).exe` 改名为 `exiftool.exe`，保留官方随附的支持目录；加入 PATH，或放到本工具的 `bin/` 中。

在 PowerShell 中执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[gui]"
.\.venv\Scripts\photo-organizer.exe --gui
```

之后可以双击 `launch.cmd`。该入口自动识别 `bin\exiftool.exe`。选择 Qt 版本时须符合其操作系统要求；本次验证使用 PySide6-Essentials 6.12.0。

只需命令行时，安装 `-e .`，无需 GUI 依赖。

## 命令行示例

```sh
# 一个来源；默认导出到 /photos/iPhone_整理
photo-organizer /photos/iPhone

# 两个来源汇总，自定义输出目录
photo-organizer /photos/iPhone /photos/Android -o /photos/旅行合集

# 先查看命名方案，不创建输出目录和报告
photo-organizer /photos/iPhone /photos/Android --dry-run

# 严格跳过缺少拍摄时间的文件
photo-organizer /photos/iPhone --missing-time skip

# 使用自定义 ExifTool 程序
photo-organizer /photos/iPhone --exiftool /path/to/exiftool
```

Windows 同样传入一个或多个目录，带空格的路径使用双引号。未传输入目录或传入 `--gui` 时打开窗口。命令行输入目录和设置也可通过 `--gui` 预填到窗口。

## 默认行为与配置

| 参数 / 窗口设置 | 默认值 | 说明 |
| --- | --- | --- |
| 输入目录 | 必填 | 支持多个目录；重复及重叠输入中的同一文件只扫描一次 |
| `-o / --output` | 输入 A 同级的 `A_整理` | 禁止输出与任何输入互相包含；防止重复扫描或覆盖源目录 |
| 仅改目录名 | `A_整理` | 始终使用目录 A 的默认父级；完整路径编辑允许更换父级 |
| `--dry-run` | 关闭 | 读取元数据和计算校验值，但不写入；若启用地点查询，仍会联网 |
| `--missing-time` | `mtime` | `mtime` 使用文件修改时间并加 `_时间待确认`；`skip` 保留在原目录，写入报告 |
| `--utc-offset` | `+08:00` | 只用于不含当地时区的 QuickTime UTC 时间；范围 ±14:00 |
| `--exiftool` | `exiftool` | 可传完整可执行程序路径 |
| `--geocode-url` | 空，禁用网络 | 自建或允许批量查询的 Nominatim 兼容 HTTPS `/reverse` 服务 |

拍摄时间优先使用 EXIF DateTimeOriginal / 亚秒时间、XMP 拍摄时间、Apple CreationDate 等；视频退回 QuickTime CreateDate / MediaCreateDate。带时区的拍摄日期保留拍摄时当地钟表时间；纯 QuickTime UTC 时间按照指定偏移换算，避免随电脑时区改变。[ExifTool 对 QuickTime 时间的说明](https://exiftool.org/TagNames/QuickTime.html)。

没有内嵌时间时，尝试原文件名中明确的 `YYYYMMDD_HHMMSS`（及常见分隔符）日期。还没有则按缺失时间策略处理。文件修改时间受导出过程影响，不等于拍摄时间；报告会记录时间来源。它使用运行电脑的本地时区。

## 地点后缀

离线时读取文件已有的城市和地点文字。多数手机只保存 GPS 坐标，因此不会凭坐标直接生成“李子坝”。若需要 GPS 转地名，在窗口勾选联网并填写你有权用于批量查询的 Nominatim 兼容服务地址，或使用 `--geocode-url`。

- 明确开启后才向配置服务发送坐标，不上传照片内容。
- 单线程、请求间隔至少 1.1 秒；以四位小数坐标缓存结果到输出目录 `.location-cache.json`。预览仅使用内存缓存。
- 后缀只取城市及街区 / 村 / 区等区域字段，不使用门牌、完整地址或经纬度。实际精度和中文覆盖由服务数据决定，不能保证每张都识别到景点。
- 查询失败会记录警告，仍继续复制；已有文件内地名优先，不再联网。
- 本工具不接入公共 `nominatim.openstreetmap.org` 批量服务；请按你使用的服务条款、配额及署名要求配置。没有配置可用服务时不加 GPS 地点后缀。
- 地名设置变化可能产生新的命名结果，当前去重只发生在相同命名系列和配套文件集合内，不是全库跨名称去重。

## 文件安全与报告

- 仅复制，不删除、移动或修改源文件。忽略隐藏文件、符号链接、非普通文件及未支持的扩展名。
- 先写临时文件并校验，再通过硬链接原子发布，绝不替换已有媒体文件。exFAT 等不支持硬链接的磁盘使用排他创建；普通失败会清理本次半成品，但断电 / 强制杀进程可能留下半成品，重跑会保留它并分配新名称。
- 每次输出独立 `.photo-report-<id>.jsonl`，记录来源、目标、时间来源、校验值、警告和错误；报告含本地路径。
- `.photo-groups.json` 保存组名与内容哈希，以便正常取消或失败后重跑补齐同组。原有输出被外部修改后，会新分配名称而不会覆盖。
- `.photo-organizer.lock` 防止同一工具同时写同一输出。强制结束可能残留锁；确认没有另一整理进程后手动移除锁再重试。
- 元数据损坏或同一组存在冲突时整组留在原处，并报告失败，其他组继续。没有元数据的正常文件与损坏文件分开处理。
- AAE 会完整保留并跟随命名，但重命名后第三方软件是否重新应用编辑信息不保证；Live Photo 配对也依赖导出软件是否保留标识。本工具不重建 Apple 照片图库。
- 分组启发式基于同目录同名和可读配对 ID，不保证识别已任意改名或分散目录的配套文件。
- 取消在文件分块及处理间隙检查，单次 ExifTool 读取最多等待 30 秒，网络请求超时 10 秒；哈希/校验期间进度计数可能暂时不变。

CLI 的阶段进度写 stderr，汇总及预览 JSON 写 stdout。退出码：`0` 完成，`1` 处理失败或存在失败文件，`2` 参数 / GUI 依赖错误，`130` 用户取消。被用户策略跳过的文件不算失败。

## 开发与验证

```sh
.venv/bin/python -m unittest discover -s tests -v
# 指定 ExifTool 时增加真实元数据集成测试
PHOTO_EXIFTOOL="$PWD/bin/exiftool/exiftool" .venv/bin/python -m unittest discover -s tests -v
```

| 平台 / 架构 | 状态 | 实际验证 |
| --- | --- | --- |
| macOS / arm64 | 已验证（下列范围） | 2026-10-27；Python 3.11.5、Qt 6.12.0、ExifTool 13.59；核心测试、PNG 集成、JPG / HEIC / MOV 样例元数据、Qt 离屏窗口及拖入事件 |
| Windows / amd64 | 目标支持，未验证 | 已添加 CI 配置，但尚未实际运行 Windows 作业或设备测试 |
| macOS / x86_64、Windows / arm64 | 目标支持，未验证 | 依赖对应 Python / Qt / ExifTool 可用性，尚未验证 |

本次共运行 25 项测试：24 项通过，1 项因本机文件系统不区分大小写而跳过。另用官方 ExifTool 样例组成两个输入目录，CLI 首次复制 5 个文件，重复运行跳过 5 个，预览正常退出。

测试不代表你的 iPhone 17 Pro、影视飓风 App 实际导出数据已经验证。尚未验证真实在线地名服务、Finder / Explorer 人工拖入、Windows 启动器和真实 exFAT 磁盘。Qt 拖入处理通过构造事件验证。

## 后续扩展

`src/photo_organizer/transforms.py` 定义 `MediaTransform` 协议并保留 TODO。当前整理流程不调用转换器，后续接入时需要同时考虑输出命名、报告、重复检测和 Live Photo 配套关系。

- TODO：HEIC 转 JPG，保留 EXIF、ICC 色彩配置、方向及原件。
- TODO：JPG 压缩，质量 / 目标大小选项，不覆盖原件。
- TODO：转换进度、衍生文件关联和转换后的去重测试。
- TODO：使用真实 iPhone 17 Pro / 第三方相机 App / 安卓导出目录验收。
- TODO：Mac / Windows 独立安装包，随包分发依赖及其许可文件。
