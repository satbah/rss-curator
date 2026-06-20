from dotenv import load_dotenv
load_dotenv()  # Must run before app.* imports — ai_filter reads ANTHROPIC_API_KEY at first call

import asyncio
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.models import Article, Feed, Interest, init_db
from app.scheduler import add_feed_job, remove_feed_job, setup_scheduler


def _safe_url(url: str) -> str:
    try:
        p = urlparse(url)
        if p.scheme in ("http", "https"):
            return url
    except Exception:
        pass
    return "#"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = setup_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["safe_url"] = _safe_url


@app.get("/")
async def root():
    return RedirectResponse(url="/articles")


@app.get("/feeds")
async def feeds_list(request: Request):
    feeds = Feed.select().order_by(Feed.id)
    return templates.TemplateResponse(request, "feeds.html", {"feeds": feeds})


@app.post("/feeds")
async def feeds_create(
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    interval_min: int = Form(60),
):
    if urlparse(url).scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="URL は http:// または https:// で始まる必要があります")
    feed = Feed.create(name=name, url=url, interval_min=interval_min, enabled=True)
    await add_feed_job(request.app.state.scheduler, feed)
    return RedirectResponse(url="/feeds", status_code=303)


@app.post("/feeds/{feed_id}/delete")
async def feeds_delete(request: Request, feed_id: int):
    await remove_feed_job(request.app.state.scheduler, feed_id)
    Feed.delete_by_id(feed_id)
    return RedirectResponse(url="/feeds", status_code=303)


@app.post("/feeds/{feed_id}/toggle")
async def feeds_toggle(request: Request, feed_id: int):
    try:
        feed = Feed.get_by_id(feed_id)
    except Feed.DoesNotExist:
        raise HTTPException(status_code=404, detail="Feed not found")
    feed.enabled = not feed.enabled
    feed.save()
    if feed.enabled:
        await add_feed_job(request.app.state.scheduler, feed)
    else:
        await remove_feed_job(request.app.state.scheduler, feed_id)
    return RedirectResponse(url="/feeds", status_code=303)


@app.get("/interests")
async def interests_list(request: Request):
    interests = Interest.select().order_by(Interest.id)
    return templates.TemplateResponse(request, "interests.html", {"interests": interests})


@app.post("/interests")
async def interests_create(
    name: str = Form(...),
    description: str = Form(...),
):
    Interest.create(name=name, description=description)
    return RedirectResponse(url="/interests", status_code=303)


@app.post("/interests/{interest_id}/delete")
async def interests_delete(interest_id: int):
    Interest.delete_by_id(interest_id)
    return RedirectResponse(url="/interests", status_code=303)


@app.get("/articles")
async def articles_list(request: Request, q: str = ""):
    loop = asyncio.get_running_loop()

    def _fetch() -> list:
        query = Article.select(Article, Feed).join(Feed).order_by(Article.published_at.desc())
        if q:
            query = query.where(Article.title.contains(q))
        return list(query.limit(100))

    articles = await loop.run_in_executor(None, _fetch)
    return templates.TemplateResponse(request, "articles.html", {"articles": articles, "q": q})
