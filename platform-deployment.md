# Web 平台部署说明

这个项目不是纯前端站点。部署时要同时运行两个服务：

- `api`：登录、用户端、管理端、下载和文件访问
- `worker`：后台执行生成任务

运行数据保存在 `platform_runtime/`，不要提交到 Git。部署包 `release/image_all-platform.zip` 只放前后端代码、Docker 配置和模板，不放本地数据库、历史、日志、账号数据。

## 本地先生成部署文件

在 Windows 本地项目目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/package-platform-zip.ps1
```

生成：

```text
release/image_all-platform.zip
```

这个压缩包包含前端、后端、Dockerfile、Compose、脚本和配置模板。

## 导出本地最新配置

如果服务器要使用你指定的旧桌面项目配置，单独导出配置：

```powershell
python scripts/export-platform-settings.py --config D:/work/code/skills/imag_Replicate2/config.json --output release/platform-settings-export.json
```

说明：

- `--config D:/work/code/skills/imag_Replicate2/config.json` 表示模型 ID、请求地址、提示词和默认密钥都从这个旧项目配置文件导出。
- 这份配置导入服务器后会成为管理端全局默认配置；普通用户部署后仍然需要自己填写密钥。
- 只有管理员账号运行任务时才会使用管理端默认密钥，普通用户不会继承管理端默认密钥。
- `release/platform-settings-export.json` 里有真实密钥，不要发到 Git，不要公开传给别人。

如果以后只想从当前平台数据库导出管理端全局默认配置，可以用：

```powershell
python scripts/export-platform-settings.py --global-only --output release/platform-settings-export.json
```

## 宝塔上传目录

建议放在：

```text
/www/wwwroot/image_all
```

在宝塔文件管理里：

1. 上传 `release/image_all-platform.zip`
2. 解压到 `/www/wwwroot/image_all`
3. 单独上传 `release/platform-settings-export.json` 到 `/www/wwwroot/image_all/platform_runtime/platform-settings-export.json`

如果 `platform_runtime` 不存在，先在服务器执行：

```bash
mkdir -p /www/wwwroot/image_all/platform_runtime
```

## 服务器配置 `.env`

进入目录：

```bash
cd /www/wwwroot/image_all
cp .env.example .env
```

编辑 `.env`，至少改这些：

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
PLATFORM_WORKER_CONCURRENCY=20
```

`PLATFORM_WORKER_CONCURRENCY` 是服务器真正同时执行任务的 Worker 数。管理端给用户设置的并发数是“单个用户最多可提交/挂起多少个任务”，两个限制会同时生效：用户额度没满才能提交，Worker 有空位才会立即执行，否则会短暂排队。

如果你暂时不用域名和宝塔反向代理，而是直接访问公网 IP 的 `8000` 端口，把这两项改成：

```text
PLATFORM_BIND=0.0.0.0
PLATFORM_COOKIE_SECURE=0
```

以后 `git pull` 不会覆盖 `.env`，所以公网访问配置只需要改一次。

再准备基础配置文件：

```bash
mkdir -p platform_runtime
cp -n config.example.json platform_runtime/config.json
```

## 启动服务

服务器需要 Docker 和 Docker Compose。宝塔可以只负责域名、HTTPS、反向代理，服务本身用 Docker Compose 起。

```bash
cd /www/wwwroot/image_all
docker compose -f docker-compose.platform.yml up -d --build
```

导入本地配置：

```bash
docker compose -f docker-compose.platform.yml exec api python scripts/import-platform-settings.py /app/platform_runtime/platform-settings-export.json
docker compose -f docker-compose.platform.yml restart api worker
```

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

如果本地配置也改了，再重新导出 `platform-settings-export.json`，上传到服务器同名位置，然后执行：

```bash
docker compose -f docker-compose.platform.yml exec api python scripts/import-platform-settings.py /app/platform_runtime/platform-settings-export.json
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

配置和本地不一致：确认是否上传并执行了 `platform-settings-export.json` 的导入命令。zip 不会自动包含本地数据库和密钥导出文件。
