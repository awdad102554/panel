import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.integrations.case_system.client import CaseSystemError
from app.services.internal_case_pause import backfill_paused_days
from app.services.internal_case_sync import sync_internal_cases
from app.services.time_limits import get_time_limits
from app.db.virtual import init_virtual_db

settings = get_settings()

# 让 app.* 模块的 INFO/WARNING 日志(尤其是后台同步循环的结果)输出到 uvicorn 控制台。
logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)


async def _sync_loop() -> None:
    """后台定时轻量同步内网案件。启动即跑一轮,之后按配置间隔循环;单轮异常不中断循环。

    轻量同步已自完备(筛选接口 + 日期补抓今/昨新案件 + 消失案件单点补拉),日常不跑全量;
    全量仅作手工恢复手段(POST /internal-cases/sync?full=true)。
    间隔每轮从"时限设置"读取(case_sync_interval_minutes,默认 60 分钟);
    读库或同步异常时退回 env 默认值,循环不中断。
    """
    while True:
        interval = settings.case_sync_interval_minutes * 60
        if settings.case_system_enabled:
            try:
                async with SessionLocal() as db:
                    interval = (await get_time_limits(db))["case_sync_interval_minutes"] * 60
                    result = await sync_internal_cases(db, full=False)
                    await db.commit()
                logger.info("内网案件同步完成(轻量): %s", result)
            except CaseSystemError as exc:
                logger.warning("内网案件同步不可用,等待下一轮: %s", exc)
            except Exception:
                logger.exception("内网案件同步异常,等待下一轮")
        await asyncio.sleep(interval)


async def _pause_backfill_loop() -> None:
    """后台回填已结案案件的中止天数(用于审理时长扣除中止期间)。

    启动即跑,每轮一批(100 件),已全部回填完则拉长到每小时探一次增量(新结案)。
    单轮异常不中断循环。
    """
    while True:
        wait_seconds = 3600
        if settings.case_system_enabled:
            try:
                async with SessionLocal() as db:
                    done = await backfill_paused_days(db)
                    await db.commit()
                if done:
                    logger.info("中止天数回填完成一批: %d 件", done)
                    wait_seconds = 60  # 还有存量,1 分钟后继续下一批
            except CaseSystemError as exc:
                logger.warning("中止天数回填不可用,等待下一轮: %s", exc)
            except Exception:
                logger.exception("中止天数回填异常,等待下一轮")
        await asyncio.sleep(wait_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_virtual_db()
    task = asyncio.create_task(_sync_loop())
    pause_task = asyncio.create_task(_pause_backfill_loop())
    try:
        yield
    finally:
        task.cancel()
        pause_task.cancel()
        # 等任务真正结束,避免关闭时循环正持 DB 会话 mid-sync 被打断告警。
        await asyncio.gather(task, pause_task, return_exceptions=True)


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # 暴露下载文件名头:跨域直连时前端才能从 content-disposition 取到文件名。
    expose_headers=["Content-Disposition"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
