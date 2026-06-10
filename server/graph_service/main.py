from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from graph_service.config import get_settings
from graph_service.routers import ingest, retrieve
from graph_service.zep_graphiti import build_graphiti


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # One shared Graphiti for the whole process (see build_graphiti). Stored on
    # app.state so the get_graphiti dependency hands the SAME instance to every
    # request — no per-request driver, so Neo4j connections stay bounded.
    graphiti = build_graphiti(settings)
    await graphiti.build_indices_and_constraints()
    app.state.graphiti = graphiti
    try:
        yield
    finally:
        await graphiti.close()


app = FastAPI(lifespan=lifespan)


app.include_router(retrieve.router)
app.include_router(ingest.router)


@app.get('/healthcheck')
async def healthcheck():
    return JSONResponse(content={'status': 'healthy'}, status_code=200)
