import { apiClient } from "@/api/client";

/** 当前客户端 IP 的用户名绑定(与 InfoWeb 共用 user_ip 表)。 */
export interface CurrentBinding {
  ip: string;
  username: string | null;
}

export function getCurrentBinding() {
  return apiClient.get<CurrentBinding>("/user-bindings/current").then((res) => res.data);
}

export function bindCurrent(username: string) {
  return apiClient.put<CurrentBinding>("/user-bindings/current", { username }).then((res) => res.data);
}
