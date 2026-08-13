# HTTPS + 域名访问（2026-07-31 启用）

访问地址：**https://hailiangjeff.top:5444**

## 结构

- nginx 直接服务前端构建产物 `frontend/dist`（SPA，`try_files` 回退 `index.html`）
- `/api/v1/` 反代到本机 uvicorn `127.0.0.1:6543`（panel.service，超时放宽到 600s，
  覆盖一致性校验/全量同步等分钟级请求）。**uvicorn 只绑定 127.0.0.1**
  （2026-08-12 起，此前 0.0.0.0 暴露直连端口）；系统免登录设计，公网可达性
  完全依赖 nginx 这一层——已加 IP 白名单（2026-08-12）：仅 127.0.0.1、
  192.168.123.0/24、10.99.144.0/24，其余 403
- 证书复用 InfoWeb 的泛域名证书 `/vol2/1000/python-project/certs/hailiangjeff.top.pem/.key`
  （`*.hailiangjeff.top` +  apex；InfoWeb 本站在 5443）

## 配置位置与运维

- 配置文件：`/etc/nginx/sites-enabled/panel`
- 生效 nginx 实例是 **infoweb-nginx.service**（不是系统的 nginx.service——后者是
  failed 状态）。重载必须 HUP **master 进程**（`ps aux | grep "nginx: master"` 中
  监听 5444 的那个，`nginx: master process nginx`）：`ss -tlnp | grep :5444` 看到的
  pid 是 worker，HUP worker 不会重载配置（2026-08-12 踩坑确认）。改配置后先
  `sudo nginx -t` 验证，再 `sudo kill -HUP <master_pid>`。
- **前端改动后必须重新构建**：`cd frontend && npm run build`，5444 服务的是
  `dist`（5173 的 vite dev server 仅供开发调试，访问生产请用 5444）
