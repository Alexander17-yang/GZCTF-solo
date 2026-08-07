# GZCTF 方块竞技场 Sidecar

一个轻量 FastAPI 服务，为 GZCTF 增加 Solo PK、One-way One-by-one 单方向单挑、多人 Boss、管理配置和持久化结算。数据保存在 SQLite；管理员和玩家身份均通过转发现有 `GZCTF_Token` Cookie 到 GZCTF `/api/account/profile` 验证。

## 设计边界

- 每个 GZCTF `gameId` 对应一份竞技场配置。
- Flag 只在管理写入时接收，使用 PBKDF2-SHA256、独立随机盐和可选 pepper 保存；任何 GET 都不会返回 Flag 或哈希。
- PK 得分、错误扣分、首杀、连胜、单方向首解裁决、Boss HP、护盾、贡献和排行榜均使用 SQLite `BEGIN IMMEDIATE` 原子结算。
- 同一玩家对同一题、同一模式只能产生一次正确结算；数据库部分唯一索引提供最终幂等保护。
- Sidecar 默认不提供独立管理员账号。管理员继续登录 GZCTF，角色必须为 `Admin`。
- Sidecar 不修改 GZCTF 原题库/Submission。竞技场题目可通过 `sourceChallengeId` 关联原题，但 Flag 需要在竞技场配置中单独设置。

## API

浏览器部署在 `/ctf` 子路径时，下面路径前面加 `/ctf`。

### 公开

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/arena/public/active` | 最近更新的 `published && enabled` 配置和 Boss 状态；没有时 404 |
| GET | `/api/arena/public/games/{gameId}` | 指定赛事的已发布配置 |

公开题目包含 `title/category/difficulty/description/target/attachmentUrl/status`、PK/Boss 参数与 `locked`，不包含 `flag`、`flagHash` 或 `hasFlag`。纯单方向题不会通过普通公开题库提前下发；对局只返回当前轮题面。

### 管理（GZCTF Admin Cookie）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/arena/admin/games/{gameId}` | 获取完整配置；未创建时返回 `exists:false` 默认对象 |
| PUT | `/api/arena/admin/games/{gameId}` | 全量保存配置和题目；可带 `revision` 做乐观锁 |
| DELETE | `/api/arena/admin/games/{gameId}` | 删除配置及其竞技场运行数据 |
| POST | `/api/arena/admin/games/{gameId}/challenges` | 新增单题 |
| PUT | `/api/arena/admin/games/{gameId}/challenges/{id}` | 更新单题 |
| DELETE | `/api/arena/admin/games/{gameId}/challenges/{id}` | 删除单题 |
| GET | `/api/arena/admin/games/{gameId}/pk-matches` | 查看 PK 房间、双方人员和最终结果 |
| DELETE | `/api/arena/admin/games/{gameId}/pk-matches/{matchId}/room` | 删除 PK 运行房间，保留审计记录 |
| DELETE | `/api/arena/admin/games/{gameId}/pk-matches/{matchId}` | 删除 PK 历史记录 |
| GET | `/api/arena/admin/games/{gameId}/one-way-matches` | 查看单方向房间、方向、逐轮结果和最终胜负 |
| DELETE | `/api/arena/admin/games/{gameId}/one-way-matches/{matchId}/room` | 删除单方向运行房间，保留审计记录 |
| DELETE | `/api/arena/admin/games/{gameId}/one-way-matches/{matchId}` | 删除单方向历史记录 |
| POST | `/api/arena/admin/games/{gameId}/reset` | Body `{"modes":["pk","boss","one_way"]}`，清空对应运行进度 |

题目的 `flag` 是 write-only。更新题目时省略 `flag` 会保留原值；发送 `clearFlag:true` 会删除。修改 `flagCaseSensitive` 时必须同时重新填写 `flag`。

若 Boss 尚无贡献，修改 Boss 配置会自动重建初始状态；已有伤害时不会静默恢复 HP，管理员需点击/调用 reset 才会应用新的初始 HP、阶段和护盾。

### 玩家（任意有效 GZCTF Cookie）

| 方法 | 路径 | Body / 参数 |
|---|---|---|
| POST | `/api/arena/pk/rooms` | `{"gameId":1}` 创建 6 位数字房间 |
| POST | `/api/arena/pk/rooms/{code}/join` | `{"gameId":1}` 加入房间；第二名玩家加入时统一设置 `startsAt` |
| GET | `/api/arena/pk/rooms/{code}?gameId=1` | 房间成员、状态、`startsAt/endsAt/serverTime` |
| POST | `/api/arena/pk/rooms/{code}/leave` | `{"gameId":1}` 比赛开始前退出 |
| GET | `/api/arena/pk/state?gameId=1&roomCode=123456` | PK 个人状态、已解题和本房间榜单；省略 `roomCode` 保留旧全局状态 |
| POST | `/api/arena/pk/submit` | `{"gameId":1,"challengeId":2,"flag":"flag{...}","roomCode":"123456"}`；省略 `roomCode` 兼容旧逻辑 |
| POST | `/api/arena/one-way/rooms` | `{"gameId":1,"directionId":"web"}`，选择方向并创建 6 位房间 |
| POST | `/api/arena/one-way/rooms/{code}/join` | 可不带 Body，凭全局唯一房间号加入；仍兼容 `{"gameId":1}` |
| GET | `/api/arena/one-way/rooms/{code}?gameId=1` | 当前轮、服务端时间、比分与已完成轮次结果 |
| POST | `/api/arena/one-way/rooms/{code}/leave` | 比赛开始前退出等待房 |
| POST | `/api/arena/one-way/submit` | `{"gameId":1,"challengeId":2,"roomCode":"123456","flag":"flag{...}"}` |
| GET | `/api/arena/boss/state?gameId=1` | Boss 状态、个人贡献、已解题和榜单 |
| POST | `/api/arena/boss/submit` | `{"gameId":1,"challengeId":2,"flag":"flag{...}"}` |

PK 房间最多两名不同玩家。房主创建后为 `waiting`；第二名玩家加入后进入 5 秒 `countdown`，匹配时钟只从响应中的统一 `startsAt` 开始。房间计分、连胜、首杀和已解记录完全隔离。倒计时尚未结束的提交会返回 HTTP 409 和 `Retry-After`，超过 `matchSeconds` 后返回 HTTP 410。

PK 冷却会返回 HTTP 429 和 `Retry-After`。Flag 错误属于已处理的提交，返回 HTTP 200 与 `correct:false`。

单方向房间在第二名玩家加入后统一设置倒计时。每轮只开放冻结题池中的一题；第一个正确提交通过条件更新原子锁定胜者，超时无人解出则补记平局。题目、题面、附件、目标、Flag Hash 和大小写规则在创建房间时冻结，因此管理员后续切换模式不会改变进行中的房间。

完整 schema 可在容器启动后查看 `/api/arena/docs` 或 `/api/arena/openapi.json`。

## 本地测试

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
uvicorn app.main:app --host 127.0.0.1 --port 8090
```

Windows 激活命令为 `.venv\\Scripts\\Activate.ps1`。

## Compose 部署

1. 将 `arena-sidecar` 目录放到现有 GZCTF compose 目录，例如 `/opt/gzctf/arena-sidecar`。
2. 复制 `.env.example` 为 `.env`，生成并固定保存 `ARENA_FLAG_PEPPER`：

   ```bash
   python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
   ```

3. 将 `compose.example.yml` 中 `arena-sidecar` 服务和 `arena-data` volume 合并到现有 compose。服务必须加入 GZCTF 所在 network，并把 `GZCTF_INTERNAL_URL` 指向实际 GZCTF service 名。
4. 启动：

   ```bash
   docker compose build arena-sidecar
   docker compose up -d arena-sidecar
   curl -fsS http://127.0.0.1:8090/healthz
   ```

5. 把 `nginx-location.conf` 的 location 放在通用 `/ctf/` location **之前**，执行 `nginx -t && systemctl reload nginx`。

容器端口只能发布到 `127.0.0.1:8090`，不要发布为 `0.0.0.0:8090`。SQLite volume 需要定期备份；在线备份建议：

```bash
docker compose exec -T arena-sidecar python -c \
  "import sqlite3; s=sqlite3.connect('/data/arena.db'); d=sqlite3.connect('/data/arena-backup.db'); s.backup(d); d.close(); s.close()"
```

## 可选应急本地管理员

仅当 GZCTF 身份服务故障且确有需要时启用。正常部署保持关闭。

```bash
python -m app.hash_password
```

把输出写入 `ARENA_LOCAL_ADMIN_PASSWORD_HASH`，设置随机 `ARENA_TOKEN_SECRET`（至少 32 字符）并将 `ARENA_LOCAL_ADMIN_ENABLED=true`。本地登录为 `POST /api/arena/admin/login`。此功能不是正常前端流程所必需。
