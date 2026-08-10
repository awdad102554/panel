import axios from "axios";

// 系统免登录(2026-07-31):不再需要携带 token 或处理 401 跳转。
export const apiClient = axios.create({
  baseURL: "/api/v1",
});
