# Kitdock · 工具坞

一个持续积累实用工具的多语言仓库。工具按用途组织，共享组件按能力组织；每个工具保留自己的入口、文档和运行方式。

当前已有照片整理工具初版，支持命令行和桌面窗口。macOS 已完成有限范围的核心与界面验证；Windows 目标支持，尚未实机验证。

## 名称

暂定 **Kitdock**：Kit 表示工具集，Dock 表示停靠、汇集的地方，中文名为“工具坞”。名称不绑定语言、平台或某类业务。备选：Toolnest（工具巢）、Pocketworks（口袋工坊）。这些是命名提案，未核验名称占用情况。

## 目录

```text
kitdock/
├── README.md                  # 项目入口与工具索引
├── tools/                     # 面向用户的工具，每个工具一个目录
│   └── README.md
├── packages/                  # 供多个工具复用的组件
│   └── README.md
├── scripts/                   # 仓库维护、检查和发布辅助脚本
│   └── README.md
├── docs/
│   └── architecture.md        # 完整架构、复用和跨平台方案
└── templates/
    └── tool-readme.md         # 每个工具的 README 模板
```

工具少时直接使用 `tools/<tool-name>/`；工具多后可按用途分为 `tools/files/<tool-name>/`、`tools/network/<tool-name>/` 等。分类按需增加，不要求提前创建空类别。

## 工具索引

| 工具 | 用途 | 实现语言 | Windows | macOS | 文档 |
| --- | --- | --- | --- | --- | --- |
| Photo Organizer | 多来源照片 / 视频归档、按时间地点命名 | Python + Qt | 目标支持，未验证 | [已验证（有限范围）](tools/photo-organizer/README.md#开发与验证) | [使用说明](tools/photo-organizer/README.md) |

平台状态统一使用“已验证 / 目标支持，未验证 / 不支持”，已验证时链接到子项目的测试记录。

## 开始添加工具

1. 在 `tools/` 下创建以工具命名的目录，使用小写字母与连字符。
2. 复制 [README 模板](templates/tool-readme.md)，填写语言、功能、安装、使用和平台信息。
3. 选择合适的语言和原生项目结构；只安装该工具需要的工具链。
4. 若已有适用组件，复用 `packages/` 中的包；新的通用能力在出现真实复用需求时提取。
5. 验证运行平台，更新本页索引。

详细约定见 [架构方案](docs/architecture.md)。当前目录可整体移动，内部文档使用相对链接，无父工作区依赖。
