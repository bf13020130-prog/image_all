# Web 平台部署说明

这个项目不是纯前端。实际运行时分成两部分：

- `api`：提供登录、用户端、管理端、下载和文件访问
- `worker`：后台执行生成任务

运行数据都落在 `platform_runtime/`，不要提交到 Git。

## 你现在的场景

你已经有宝塔面板、阿里云轻量服务器、一个空的新仓库。最稳的做法是：

1. 本地把代码整理好
2. 生成一个部署 zip
3. 上传到服务器解压
4. 配好 `.env` 和原始 `config.json`
5. 用 Docker Compose 启动 `api` 和 `worker`
6. 宝塔只做域名和反向代理

## 本地首次推送到新仓库

如果远端仓库是空的，建议用这套命令做第一次初始化：

```bash
git remote set-url origin https://github.com/bf13020130-prog/image_all.git
git checkout --orphan main
git add -A
git commit -m "Initial import"
git push -u origin main
```

这样远端会得到一个干净的初始提交，不会带上旧仓库历史。

## 生成服务器部署 zip

在 Windows 本地执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/package-platform-zip.ps1
```

默认输出：

```text
release/image_all-platform.zip
```

这个包只包含仓库需要的源码和配置模板，不包含运行日志、数据库、缓存和 `platform_runtime/`。

## 服务器目录建议

建议放在：

```text
/www/wwwroot/image_all
```

不要把它当成纯静态站点目录。这个项目必须有后端和 worker。

## 服务器部署步骤

1. 把 `release/image_all-platform.zip` 上传到服务器
2. 在宝塔文件管理器解压到 `/www/wwwroot/image_all`
3. 进入目录，复制环境文件：

```bash
cp .env.example .env
```

4. 编辑 `.env`，至少改这些：

```text
PLATFORM_APP_SECRET=足够长的随机字符串
PLATFORM_ADMIN_USERNAME=admin
PLATFORM_ADMIN_PASSWORD=强密码
PLATFORM_CONFIG_PATH=platform_runtime/config.json
PLATFORM_COOKIE_SECURE=1
PLATFORM_ALLOW_PRIVATE_URLS=0
PLATFORM_HISTORY_RETENTION_DAYS=10
PLATFORM_HISTORY_CLEANUP_INTERVAL_HOURS=24
```

说明：

- `PLATFORM_COOKIE_SECURE=1` 适合 HTTPS 站点
- `PLATFORM_ALLOW_PRIVATE_URLS=0` 适合上线后禁止本机/内网图片地址
- `PLATFORM_HISTORY_RETENTION_DAYS=10` 会自动删除 10 天前的历史和文件

5. 准备原项目配置文件：

```bash
mkdir -p platform_runtime
cp config.example.json platform_runtime/config.json
```

如果你有原来的 `config.json`，也可以直接放到：

```text
/www/wwwroot/image_all/platform_runtime/config.json
```

6. 启动服务：

```bash
docker compose -f docker-compose.platform.yml up -d --build
```

## 宝塔站点怎么配

宝塔站点只负责：

- 域名
- HTTPS
- 反向代理

反向代理目标填：

```text
http://127.0.0.1:8000
```

站点根目录可以是空目录，不需要指向前端文件夹。

## 启动后访问

- 用户端：`/user/`
- 管理端：`/admin/`

本机直连地址：

```text
http://127.0.0.1:8000/user/
http://127.0.0.1:8000/admin/
```

## 自动清理

系统会自动清理两类东西：

- 24 小时前的下载 zip
- 10 天前的历史任务和对应文件

这样可以减轻磁盘压力。

## 后续更新

以后升级按这个顺序：

```bash
cd /www/wwwroot/image_all
git pull
docker compose -f docker-compose.platform.yml up -d --build
```

建议先备份：

```text
.env
platform_runtime/
```

## 常见问题

如果页面能打开，但任务不跑，通常是 `worker` 没起来。

如果上传被拦，先检查宝塔的 Nginx 上传限制，再检查 `.env` 里的 `PLATFORM_MAX_UPLOAD_MB`。

如果历史删不掉，先看服务是否重启过。自动清理在 API 启动和 worker 循环里都会跑。
