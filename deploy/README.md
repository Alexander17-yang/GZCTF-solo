# 部署目录

本目录提供从当前源码构建并以 `/ctf/` 子路径运行整个平台的 Compose 模板。

```bash
cp .env.example .env
# 编辑 .env 后：
docker compose config
docker compose --profile build run --rm frontend-builder
docker compose up -d --build
```

完整步骤、备份与故障排查见仓库根目录 [`README.md`](../README.md)。
