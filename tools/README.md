# 工具目录

每个面向用户的工具占一个目录，命名描述用途，不描述实现语言。

允许 `tools/<tool-name>/` 和 `tools/<category>/<tool-name>/` 两种布局。分类按需建立，例如 `files`、`network`、`data`、`system`。

每个工具必须包含自己的 `README.md`，从 [模板](../templates/tool-readme.md) 开始填写。源码布局遵循所用语言惯例，私有实现留在工具内，公共逻辑提取到 `packages/`。

当前没有已实现工具。架构文档中的工具名称仅供示例。
