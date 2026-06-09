# Web 平台部署说明

这个项目不是纯前端站点。部署时要同时运行两个服务：

- `api`：登录、用户端、管理端、下载和文件访问
- `worker`：后台执行生成任务

运行数据保存在 `platform_runtime/`，不要提交到 Git。当前是内部使用场景，部署包 `release/image_all-platform.zip` 默认会额外带上 `.env`、`platform_runtime/config.json` 和 `platform_runtime/platform.db*`，适合首次部署或明确要让服务器沿用本机设置页配置、Key 池和已注册用户。服务器已经有同事账号时，不要覆盖服务器数据库，按本文的“一键同步配置到服务器已有用户”流程处理。

## 本地先生成部署文件

在 Windows 本地项目目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/package-platform-zip.ps1
```

生成：

```text
release/image_all-platform.zip
```

这个压缩包包含前端、后端、Dockerfile、Compose、脚本、配置模板，以及当前内部运行所需的 `.env`、settings JSON 和 SQLite 用户库。历史图片、任务文件和任务日志所在的 `platform_runtime/storage/` 不默认塞进 zip，体积大；如果服务器也要保留历史预览，需要单独同步这个目录。

## 导出本地最新配置

如果服务器已经有十几个同事账号，不要用本地 `platform.db` 覆盖服务器数据库。正确做法是只导出你当前平台账号的有效设置和 Key 池，再导入到服务器现有用户。

```powershell
python scripts/export-platform-settings.py --username jk --output release/platform-settings-export.json
```

说明：

- `--username jk` 会把 `jk` 当前设置页的普通设置、默认选中 Key ID、完整 Key 池和其他密钥一起导出。
- 这份配置导入服务器时会先成为管理端全局默认配置。
- 如果导入时加 `--apply-to-users active`，会把同一份设置和 Key 池同步给服务器所有启用状态的用户。
- 如果只想同步指定用户，用 `--target-usernames zhangsan,lisi`。
- `release/platform-settings-export.json` 里有真实密钥，不要发到 Git，不要公开传给别人。

如果以后只想导出管理端全局默认配置，不合并某个用户自己的覆盖配置，可以用：

```powershell
python scripts/export-platform-settings.py --global-only --output release/platform-settings-export.json
```

如果服务器要使用某个旧桌面项目配置，也可以从旧配置文件导出：

```powershell
python scripts/export-platform-settings.py --config D:/work/code/skills/imag_Replicate2/config.json --output release/platform-settings-export.json
```

## 宝塔上传目录

建议放在：

```text
/www/wwwroot/image_all
```

在宝塔文件管理里：

1. 上传 `release/image_all-platform.zip`
2. 解压到 `/www/wwwroot/image_all`

zip 里已经默认带 `.env`、`platform_runtime/config.json` 和 `platform_runtime/platform.db*`。如果服务器上已经有更重要的新数据，先备份服务器的 `.env` 和 `platform_runtime/`，不要直接覆盖。

如果 `platform_runtime` 不存在，先在服务器执行：

```bash
mkdir -p /www/wwwroot/image_all/platform_runtime
```

## 服务器配置 `.env`

进入目录：

```bash
cd /www/wwwroot/image_all
```

如果 zip 中没有 `.env`，才执行：

```bash
cp .env.example .env
```

首次上线可以检查 `.env`，关键项应类似：

```text
PLATFORM_APP_SECRET=换成足够长的随机字符串
PLATFORM_ADMIN_USERNAME=admin
PLATFORM_ADMIN_PASSWORD=换成强密码
PLATFORM_CONFIG_PATH=platform_runtime/config.json
PLATFORM_BIND=127.0.0.1
PLATFORM_COOKIE_SECURE=1
PLATFORM_ALLOW_PRIVATE_URLS=0
PLATFORM_HISTORY_RETENTION_DAYS=10
PLATFORM_HISTORY_CLEANUP_INTERVAL_HOURS=24
PLATFORM_WORKER_CONCURRENCY=100
PLATFORM_DEFAULT_USER_CONCURRENT_LIMIT=30
PLATFORM_MAX_USER_CONCURRENT_LIMIT=100
```

`PLATFORM_WORKER_CONCURRENCY` 是服务器真正同时执行任务的 Worker 数，默认 100。`PLATFORM_DEFAULT_USER_CONCURRENT_LIMIT` 是新注册/新建用户的默认并发额度，默认 30。`PLATFORM_MAX_USER_CONCURRENT_LIMIT` 是管理端允许设置的用户并发额度上限，默认 100。管理端给用户设置的并发数是“单个用户最多可提交/挂起多少个任务”，两个限制会同时生效：用户额度没满才能提交，Worker 有空位才会立即执行，否则会短暂排队。

如果你暂时不用域名和宝塔反向代理，而是直接访问公网 IP 的 `8000` 端口，把这两项改成：

```text
PLATFORM_BIND=0.0.0.0
PLATFORM_COOKIE_SECURE=0
```

以后 `git pull` 不会覆盖 `.env`，所以公网访问配置只需要改一次。

再准备运行目录：

```bash
mkdir -p platform_runtime
```

`platform_runtime/config.json` 不用手动从 `config.example.json` 复制；首次启动或导入配置时会自动生成新的 settings JSON。业务数据仍写入 `platform_runtime/platform.db`。

## 启动服务

服务器需要 Docker 和 Docker Compose。宝塔可以只负责域名、HTTPS、反向代理，服务本身用 Docker Compose 起。

```bash
cd /www/wwwroot/image_all
docker compose -f docker-compose.platform.yml up -d --build
```

如果你没有随 zip 携带 `platform_runtime/config.json`，才需要只导入到管理端全局默认配置：

```bash
docker compose -f docker-compose.platform.yml exec api python scripts/import-platform-settings.py /app/platform_runtime/platform-settings-export.json
docker compose -f docker-compose.platform.yml restart api worker
```

## 一键同步配置到服务器已有用户

服务器已经有同事账号时，核心原则是：保留服务器自己的 `platform_runtime/platform.db*`，只导入 `platform-settings-export.json`。本地 `platform_runtime/config.json` 里的用户配置按本机 `user_id` 存，直接覆盖到服务器不一定能匹配服务器同事账号。

把本地生成的 `release/platform-settings-export.json` 上传到服务器：

```text
/www/wwwroot/image_all/platform_runtime/platform-settings-export.json
```

先干运行，确认目标用户列表：

```bash
cd /www/wwwroot/image_all
docker compose -f docker-compose.platform.yml exec api python scripts/import-platform-settings.py /app/platform_runtime/platform-settings-export.json --apply-to-users active --dry-run
```

确认无误后正式导入：

```bash
docker compose -f docker-compose.platform.yml exec api python scripts/import-platform-settings.py /app/platform_runtime/platform-settings-export.json --apply-to-users active
docker compose -f docker-compose.platform.yml restart api worker
```

这会做三件事：

- 更新服务器管理端全局默认配置。
- 把同一份普通设置写入所有 `status = active` 的服务器用户。
- 把同一份 Key 池和密钥写入这些用户自己的配置块，并用服务器 `.env` 里的 `PLATFORM_APP_SECRET` 重新加密保存。

如果只同步部分同事：

```bash
docker compose -f docker-compose.platform.yml exec api python scripts/import-platform-settings.py /app/platform_runtime/platform-settings-export.json --target-usernames zhangsan,lisi
docker compose -f docker-compose.platform.yml restart api worker
```

如果服务器是第一次部署，还没有任何重要用户和历史数据，可以直接使用 zip 里携带的 `.env`、`platform_runtime/config.json` 和 `platform_runtime/platform.db*`。如果服务器已经有人在用，就不要覆盖服务器的 `platform_runtime/platform.db*`。

访问：

```text
用户端：https://你的域名/user/
管理端：https://你的域名/admin/
```

本机临时访问：

```text
http://127.0.0.1:8000/user/
http://127.0.0.1:8000/admin/
```

## 宝塔反向代理

宝塔站点只负责：

- 域名
- HTTPS
- 反向代理

反向代理目标填：

```text
http://127.0.0.1:8000
```

站点根目录不用指向前端文件夹，这不是纯静态前端项目。

## 后续更新

不需要每次删除服务器目录再上传 zip。`platform_runtime/` 是数据库、历史、生成文件和导入配置所在目录，`.env` 是服务器环境配置，这两个都要保留。

建议后续更新走 Git。代码更新后，在服务器执行：

```bash
cd /www/wwwroot/image_all
git pull
docker compose -f docker-compose.platform.yml up -d --build
```

如果你暂时不用 Git，也可以重新上传新版 `release/image_all-platform.zip` 覆盖项目代码，但不要删除 `.env` 和 `platform_runtime/`。覆盖后同样执行：

```bash
cd /www/wwwroot/image_all
docker compose -f docker-compose.platform.yml up -d --build
```

如果本地配置也改了，重新生成并上传新版 `release/image_all-platform.zip` 会带上新的 `platform_runtime/config.json`。服务器已有用户时，建议单独重新导出 `platform-settings-export.json`，上传到服务器同名位置，然后执行：

```bash
docker compose -f docker-compose.platform.yml exec api python scripts/import-platform-settings.py /app/platform_runtime/platform-settings-export.json --apply-to-users active
docker compose -f docker-compose.platform.yml restart api worker
```

更新前建议备份：

```text
.env
platform_runtime/
```

## 自动清理

系统会自动清理：

- 24 小时前的下载 zip
- 10 天前的历史任务和对应文件

如果历史或文件没有被清掉，先确认 `api` 和 `worker` 是否都重启过。

## 常见问题

页面能打开但任务不跑：通常是 `worker` 没启动，执行 `docker compose -f docker-compose.platform.yml ps` 看状态。

上传失败：先检查宝塔 Nginx 上传限制，再检查 `.env` 里的 `PLATFORM_MAX_UPLOAD_MB`。

配置和本地不一致：先确认 zip 是否是最新生成的，并检查服务器 `.env`、`platform_runtime/config.json`、`platform_runtime/platform.db*` 是否被旧文件覆盖。只有走单独配置导出流程时，才需要执行 `platform-settings-export.json` 的导入命令。
