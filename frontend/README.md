# 管理台

Vue 3 + Vite + TypeScript + Element Plus。总览、鉴权与扩展配置见仓库根目录 [README.md](../README.md)。

## 开发

```bash
npm install
npm run dev -- --host 0.0.0.0 --port 5175
```

Vite 把 `/api` 与 `/downloads` 代理到 `http://127.0.0.1:8000`。默认端口是 `5173`（见 `vite.config.ts`）；被占用时请显式 `--port`。

## 构建

```bash
npm run build
```

产物在 `dist/`，Compose 中由 nginx 挂载。
