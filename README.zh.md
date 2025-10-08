# MitmPilot

MitmPilot 是一个用于运行、管理和分享 [mitmproxy](https.://www.mitmproxy.org/) 插件的 Python 项目。

## 主要特性

- **插件管理**: 轻松加载、卸载和在线安装 mitmproxy 插件。
- **Web 界面**: 基于 FastAPI 提供了一个用户友好的 Web 界面来管理和监控插件。
- **Hook 路由**: 灵活的 Hook 机制，支持根据规则动态匹配和执行插件。
- **可扩展性**: 设计上易于扩展，可以方便地添加新功能和模块。

## 快速开始

要开始使用 MitmPilot，请按照以下步骤操作：

1.  **克隆仓库：**
    ```bash
    git clone https://github.com/wumode/MitmPilot.git
    cd MitmPilot
    ```

2.  **环境设置：**
    ```bash
    # 安装 uv
    pip install uv
    # 创建虚拟环境
    uv venv
    # 激活虚拟环境
    source .venv/bin/activate
    # 安装依赖
    uv pip install -e ".[dev]"
    ```

3. **运行前端项目:** [MitmPilot-Frontend](https://github.com/wumode/MitmPilot-Frontend)

4. **运行应用程序：**
    ```bash
    python -m app.main
    ```

    应用程序将可以通过 `http://0.0.0.0:6008` 访问。

## 贡献

欢迎各种形式的贡献，包括但不限于：

- 提交 Bug 报告
- 贡献代码
- 完善文档

## 许可证

本项目基于 [GPL-3.0](LICENSE) 开源。

## 相关项目

MitmPilot 核心功能移植自 [MoviePilot](https://github.com/jxxghp/MoviePilot)