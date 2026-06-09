# 配置与本地运行数据地图

本文档只说明内部 Web 平台的“设置页配置”与“运行数据”边界，避免把两类东西混在一起。

## 结论

设置页配置现在只以一份 live JSON 为主：

- 默认路径：`platform_runtime/config.json`
- 环境变量覆盖：`PLATFORM_CONFIG_PATH`
- 加密依赖：`.env` 里的 `PLATFORM_APP_SECRET`

SQLite 仍然保存业务数据：

- 主数据库：`platform_runtime/platform.db`
- 用户、登录会话、任务、任务事件、生成产物索引、额度、审计日志、编辑会话等都继续在 SQLite。
- 任务运行时的 `jobs.effective_settings_json` 是提交任务时的配置快照，仍然留在 SQLite，方便追溯历史任务当时用的配置。

## 设置页 JSON 结构

`platform_runtime/config.json` 是设置页的唯一主配置文件，包含：

- `global.settings`：管理员全局默认普通设置。
- `global.secrets`：管理员全局默认密钥和 Key 池，值为加密字符串。
- `users.<user_id>.settings`：用户自己的普通设置覆盖。
- `users.<user_id>.secrets`：用户自己的密钥和 Key 池，值为加密字符串。

Key 池也放在这份 JSON 里：

- `llm_key_pool`：大模型 Key 池。
- `gpt_image_1k_key_pool`：GPT 1K 生图 Key 池。
- `gpt_image_key_pool`：GPT 2K/4K 生图 Key 池。
- `gemini_image_key_pool`：Banana / Gemini 生图 Key 池。

默认选中的 Key ID 也是普通设置字段，例如：

- `default_llm_key_id`
- `default_gpt_image_1k_key_id`
- `default_gpt_image_key_id`
- `default_gemini_image_key_id`

## SQLite 里哪些表仍然保留

这些表不能删，仍是平台业务数据：

- `users`
- `sessions`
- `user_quotas`
- `quota_transactions`
- `jobs`
- `job_events`
- `job_artifacts`
- `client_logs`
- `audit_logs`
- `conversations`
- `conversation_messages`
- `user_edit_conversations`
- `user_image_counters`

这些旧设置表也先保留，但现在只作为兼容和首次迁移来源，不再作为设置页主存储：

- `global_settings`
- `user_settings`
- `user_secrets`

首次读取设置时，如果 `platform_runtime/config.json` 还不是新的 settings document，平台会从旧 SQLite 设置表和旧配置文件迁移出一份新的 JSON。迁移后，设置页保存会写回 `platform_runtime/config.json`。

## 不是主配置的位置

这些文件容易误判，但不是设置页主配置：

- `config.json`：旧单机配置或本地种子配置，可能含真实密钥。
- `config.example.json`：模板配置，不应含真实密钥。
- `runtime/seed-config.json`：旧桌面打包生成的种子配置，可重建。
- `runtime-platform/platform-seed-config.json`：平台桌面打包生成的种子配置，可重建。
- `platform_runtime/storage/users/<user>/jobs/<job>/pipeline/config.json`：某个任务运行时复制出来的配置快照。
- `platform_runtime/storage/users/<user>/jobs/<job>/pipeline/data/**/json/settings.json`：某个任务输出里的公开设置快照。

## 必须一起备份的文件

要完整保留本机状态，至少备份：

- `.env`
- `platform_runtime/config.json`
- `platform_runtime/platform.db`
- `platform_runtime/platform.db-wal`
- `platform_runtime/platform.db-shm`
- `platform_runtime/storage`

原因：

- `platform_runtime/config.json` 里有加密后的设置页密钥。
- `.env` 里的 `PLATFORM_APP_SECRET` 参与解密。
- SQLite 保存业务数据。
- `platform_runtime/storage` 保存上传文件、生成结果和任务日志。

## 可清理目录

这些是可重建产物，确认没有正在运行的程序占用后可以清：

- `_tmp_*`
- `_runtime_uploads`
- `build/`
- `build-backend-exe/`
- `dist-backend-exe/`
- `dist-electron-backend-exe/`
- `dist-electron-platform/`
- `runtime/`
- `runtime-platform/`
- `release/`
- `logs/`
- `crash-dumps/`
- `platform_runtime/downloads/*.zip`
- `platform_runtime/test-smoke*`
- `__pycache__/`

不要手动删除：

- `.env`
- `config.json`
- `platform_runtime/config.json`
- `platform_runtime/platform.db*`
- `platform_runtime/storage`
- `node_modules`
- `data`

历史任务应该通过应用接口删除，这样 SQLite 记录和文件目录会一起清理。

## 打包配置规则

当前项目按内部发布处理，默认会携带真实设置：

- `scripts/prepare_platform_desktop_runtime.py` 优先把 `platform_runtime/config.json` 复制成 `runtime-platform/platform-seed-config.json`。
- 同一个脚本会把 `platform_runtime/platform.db*` 复制成 `runtime-platform/platform-seed.db*`。
- 同一个脚本也会把 `.env` 复制到打包后的平台后端目录，保证 settings JSON 里的加密 Key 可以解密。
- `scripts/package-platform-zip.ps1` 默认把 `.env`、`platform_runtime/config.json`、`platform_runtime/platform.db*` 放进服务器 zip，适合首次部署或明确要让服务器沿用本机设置页配置、Key 池和已注册用户。服务器已有用户时，不要覆盖服务器数据库，走下面的单独导出/导入流程。

如果临时要打一个不带真实配置的模板包：

```powershell
$env:PLATFORM_USE_EXAMPLE_CONFIG_SEED = "1"
npm run prepare:platform-desktop

powershell -ExecutionPolicy Bypass -File scripts/package-platform-zip.ps1 -IncludeRuntimeData:$false
```

`platform_runtime/storage/` 不默认放进服务器 zip。它保存历史任务文件、预览图和日志；如果服务器也要完整保留历史预览，需要单独同步这个目录。

单独迁移设置时仍可以使用导出/导入流程。服务器已经有同事账号时，不要直接覆盖服务器 `platform_runtime/platform.db*`，也不要只靠覆盖本地 `platform_runtime/config.json` 来同步用户配置；这份 JSON 里的 `users.<user_id>` 使用的是本机用户 ID，服务器用户 ID 可能不同。

```powershell
python scripts/export-platform-settings.py --username jk --output release/platform-settings-export.json
python scripts/import-platform-settings.py release/platform-settings-export.json --apply-to-users active
```

导入脚本会读取导出文件中的明文设置和 Key 池，在目标环境里重新写入 `global` 和目标 `users.<server_user_id>` 配置块，并用目标环境 `.env` 里的 `PLATFORM_APP_SECRET` 重新加密保存密钥。只想同步指定用户时，使用 `--target-usernames zhangsan,lisi`。

`platform-settings-export.json` 可能包含真实密钥，不要提交到 Git。

## 当前主线入口

当前截图对应的新平台主线：

- 后端：`platform_backend/app/main.py`
- 后台 worker：`platform_backend/app/worker.py`
- 平台启动器：`platform_backend/app/launcher.py`
- 用户前端：`platform_frontend/user`
- 管理前端：`platform_frontend/admin`
- 平台 Electron 壳：`electron-platform/main.js`
- Electron 兼容转发入口：`main.js`

旧单机主线源码仍在仓库中，仅用于查历史和必要时单独恢复：

- `api_server.py`
- `backend_main.py`
- `desktop_main.py`
- `legacy_tk_app.py`
- `web/`

这些旧入口不再进入平台 Docker 镜像或平台桌面 runtime，旧 backend-exe 的 npm/bat 入口也已经禁用。不要在当前平台发布流程里继续维护这条旧链路。
