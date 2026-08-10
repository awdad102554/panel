import ElementPlus from "element-plus";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import "element-plus/dist/index.css";
import "@/styles/tokens.css";
import "@/styles/global.css";
import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "@/App.vue";
import router from "@/router";

const app = createApp(App);

app.use(createPinia());
app.use(router);
// 全局中文语言包:日期选择器等组件显示中文(月份/星期/按钮)。
app.use(ElementPlus, { locale: zhCn });

app.mount("#app");
