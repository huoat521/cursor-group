# 部署说明

## 密钥（必改）

启动时会拒绝示例或过短的 `SECRET_KEY`、`CURSOR_TOKEN_ENCRYPT_KEY`，以及弱管理员密码 `admin123`。

```bash
cp .env.example .env
# 至少设置：
#   SECRET_KEY（≥32 位）
#   CURSOR_TOKEN_ENCRYPT_KEY（≥16 位）
#   BOOTSTRAP_ADMIN_PASSWORD（不要用 admin123）
#   MYSQL_ROOT_PASSWORD / MYSQL_PASSWORD（Compose 必填）
```

## Docker Compose

```bash
make build-frontend
make build-extension   # 可选；产物供「我的 Cursor」下载
docker compose up -d --build
```

| 服务 | 端口 |
|---|---|
| 管理台 nginx | 宿主机 **5173** → 容器 80 |
| API | **8000** |
| MySQL | 宿主机 **3307** → 容器 3306 |
| Redis | 仅 Compose 网络内，不映射到宿主机 |

前端静态文件由 nginx 提供，`/api` 与 `/downloads` 反代到 API。

## 复用已有 MySQL / Redis

把 `.env` 里的 `ASYNC_MYSQL_URI` / `REDIS_*` 指到现有实例，创建空库 `cursor_group` 后：

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
set -a && source ../.env && set +a
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000
```

首次启动执行 Alembic `upgrade head` 建表并创建管理员。若库里已有表但没有 `alembic_version`，会自动 `stamp head`。

手工迁移：

```bash
cd backend
PYTHONPATH=. alembic -c alembic.ini upgrade head
```

## Celery

```bash
celery -A app.celery_app.celery_app worker -l info
celery -A app.celery_app.celery_app beat -l info
```

| 任务 | 周期 |
|---|---|
| 用量同步 | 每 2 小时 |
| 租约回收 | 每小时 :20 |
| 历史清理 | 每天 03:30 |
| 号池告警 | 9 / 14 / 18 点 |
| 绑定巡检 | 每天 04:10 |

## 网络与代理

- 本机若设置了 `http_proxy`，访问 `127.0.0.1` 请设 `NO_PROXY=*`
- 局域网访问管理台与 API 时，防火墙需放行对应 TCP 端口（开发常见 `5175`、`8000`）
- 扩展的 `serverBaseUrl` 必须是 API origin，不能是管理台 origin
