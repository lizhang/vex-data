"""FastAPI app + Mangum Lambda handler."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mangum import Mangum

from app.api.routes.query import router as query_router
from app.services.athena import AthenaQueryError, AthenaTimeoutError


app = FastAPI(title="VEX Data API", version="1.0")

app.include_router(query_router, prefix="/query")


@app.exception_handler(AthenaTimeoutError)
def _athena_timeout_handler(_request: Request, exc: AthenaTimeoutError) -> JSONResponse:
    return JSONResponse(
        status_code=504,
        content={"error": "Query timed out", "execution_id": exc.execution_id},
    )


@app.exception_handler(AthenaQueryError)
def _athena_query_error_handler(_request: Request, exc: AthenaQueryError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={
            "error": "Athena query failed",
            "state_reason": exc.state_reason,
            "execution_id": exc.execution_id,
        },
    )


handler = Mangum(app)
