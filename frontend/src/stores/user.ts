import { defineStore } from "pinia";

import * as userBindingApi from "@/api/userBinding";

interface UserState {
  ip: string;
  username: string | null;
  loaded: boolean;
}

/** 当前客户端 IP 对应的用户名(与 InfoWeb 共用)。未绑定 = username 为 null。 */
export const useUserStore = defineStore("user", {
  state: (): UserState => ({
    ip: "",
    username: null,
    loaded: false,
  }),
  getters: {
    isBound(state): boolean {
      return !!state.username;
    },
  },
  actions: {
    async load() {
      // 后端 MySQL 连接可能因 wait_timeout 失效,首次请求偶发 500;重试一次代替手动刷新。
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          const b = await userBindingApi.getCurrentBinding();
          this.ip = b.ip;
          this.username = b.username;
          break;
        } catch {
          this.username = null;
        }
      }
      this.loaded = true;
    },
    async bind(username: string) {
      const b = await userBindingApi.bindCurrent(username);
      this.ip = b.ip;
      this.username = b.username;
    },
  },
});
