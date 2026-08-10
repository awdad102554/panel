# HTTPS + 域名访问（2026-07-31 启用）

访问地址：**https://hailiangjeff.top:5444**

## 结构

- nginx 直接服务前端构建产物 `frontend/dist`（SPA，`try_files` 回退 `index.html`）
- `/api/v1/` 反代到本机 uvicorn `127.0.0.1:6543`（panel.service，超时放宽到 600s，
  覆盖一致性校验/全量同步等分钟级请求）
- 证书复用 InfoWeb 的泛域名证书 `/vol2/1000/python-project/certs/hailiangjeff.top.pem/.key`
  （`*.hailiangjeff.top` +  apex；InfoWeb 本站在 5443）

## 配置位置与运维

- 配置文件：`/etc/nginx/sites-enabled/panel`
- 生效 nginx 实例是 **infoweb-nginx.service**（不是系统的 nginx.service——后者是
  failed 状态）。注意：`systemctl reload infoweb-nginx` 的 ExecReload 指向的 pid 文件
  不是实际服务 5443/5444 的 master，reload 可能不生效。可靠做法是先找进程再 HUP：
  `sudo kill -HUP $(ss -tlnp | grep :5444 | grep -oP 'pid=\K[0-9]+' | sort -n | head -1)`
  （改动配置后执行；配置出错时先 `sudo nginx -t` 验证）
- **前端改动后必须重新构建**：`cd frontend && npm run build`，5444 服务的是
  `dist`（5173 的 vite dev server 仅供开发调试，访问生产请用 5444）
