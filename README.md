# 设计出图

`imag_Replicate2` 现在是一个本地 Electron 桌面应用：

- 前端是内置浏览器窗口，不依赖系统默认浏览器
- 后端是本地 `FastAPI + Python`
- 数据、日志、配置都保存在应用目录，方便排查和转交
- 打包后可直接给别人使用

## 功能结构

应用内固定 3 个页面：

- `复刻风格图片`
- `图片生成`
- `一键追色`
- `历史`
- `设置`

右上角有单独的 `日志` 按钮，点击后弹出日志窗口查看：

- 当前任务日志
- `logs/app.log`
- `logs/backend-server.log`
- `logs/electron-shell.log`

## 当前生图逻辑

`复刻风格图片` 保留原来的两段式流程：

1. 用 1~5 张风格图 + 1~5 张产品图 + 用户提示词，请大模型整理提示词
2. 实际生图阶段只把产品图组发送到生图接口，风格图只参与提示词生成

`图片生成` 有两个模式：

- `普通模式`：用户选择生图模型、分辨率、比例、生成次数，后端按同一提示词发起多次生图请求。
- `Agent 模式`：用户只写自然语言需求并上传参考图；后端用 `image_agent_model` 走 planner + image_video_creator 的工具式流程，先通过 `write_plan` 规划数量/规格/交付项，再收集每张图的生图工具任务，最后按用户选择的生图模型调用现有生图接口。Agent 会携带当前图片生成会话的历史上下文，超出上下文预算时自动压缩较早消息。

设置页负责统一维护：

- 网络请求代理开关（默认不使用系统代理，直连供应商接口）
- 系统提示词
- 图片 Agent 规划/创作提示词
- 大模型请求设置（复刻风格图片、复刻风格图片2、Agent 和一键追色都可选择 `/v1/chat/completions` 或 `/v1/responses`）

## Win11 / 低配电脑兼容

应用支持 Windows 11 x64。兼容包默认带 `compat-mode.flag`，会禁用 GPU 硬件加速并关闭部分动画、模糊和阴影效果，以规避低配电脑或显卡驱动异常导致的黑屏、白屏、画面闪烁或明显卡顿。如果后续确认机器显卡稳定、想恢复硬件加速，可以在程序 exe 同级目录新建空文件 `enable-gpu.flag`，再重新启动应用。
- 生图请求设置（gpt-image-2 与 Gemini 的 Base/Key 分开配置，Gemini 模型 ID 内置）
- 默认提示词数
- 默认比例
- 默认单条出图数
- 用户任务额度；服务器实际执行并发由 `PLATFORM_WORKER_CONCURRENCY` 控制

设置有改动就自动保存。

## 数据目录

任务结果保存在：

```text
data/
  edit_conversations.json
  history.json
  image/
    YYYYMMDD-HHMMSS/
      json/
      images/
```

其中：

- `edit_conversations.json` 保存图片编辑页的非空会话，重启后会自动恢复
- `json/` 保存请求、返回、manifest、summary、run.log
- `images/` 保存参考图和生成图

## 日志目录

```text
logs/
  app.log
  backend-server.log
  electron-shell.log
```

这些日志都会保留在本地，方便后续定位请求参数、接口返回和桌面壳问题。

## 开发启动

```powershell
cd D:\work\code\skills\imag_Replicate_lan
npm install
npm run dev
```

也可以直接双击：

```text
launch.bat
```

## 打包

```powershell
cd D:\work\code\skills\imag_Replicate_lan
build.bat
```

`build.bat` 会自动执行：

1. `npm install`
2. `npm run dist:platform-desktop`

打包输出在：

```text
dist-electron-platform/
  设计出图-<version>.exe
```

## 运行时说明

`scripts/prepare_platform_desktop_runtime.py` 会自动生成最小化的嵌入式 Python 运行时，并准备平台后端资源。这样打包出来的平台桌面版会把：

- 平台后端源码
- 精简 Python 运行时
- 用户端和管理端前端资源

一起带进包里，不依赖用户额外安装 Python。

## 旧 backend-exe 链路

旧单机桌面的独立后端 exe 链路已经退役。当前维护的是平台桌面包：

```powershell
npm run dist:platform-desktop
```

为了避免误操作，`npm run dist:backend-exe`、`npm run dist:legacy-backend-exe`、`npm run prepare:runtime` 和 `npm run prepare:backend-exe` 都只会提示使用平台桌面打包命令，不再执行旧链路。


## 2026-04-24 Update

- `复刻风格图片` 和 `图片编辑` 现在统一使用 `分辨率 + 比例` 组合。
- `图片编辑` 有输入图时走 `/v1/images/edits`，没有输入图时走 `/v1/images/generations`。
- `size` 会按分辨率档位和比例自动换算，并满足最长边、16 倍数、总像素限制。

## 一键追色

- 新增 `一键追色` 页面：上传色调参考图和静物场景图。
- 大模型使用设置项 `color_match_model`，默认 `gpt-5.5`，复用现有大模型 API Base、API Key、超时和重试设置。
- 色彩分析图固定使用 `1K / 4:3`；最终两路追色图使用页面选择的分辨率和比例。
