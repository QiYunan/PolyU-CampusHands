"""HTTP endpoints; business rules live in services.py."""

from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.schemas import RequestCreate, RequestRead
from app.services import InvalidDeadline, create_request, get_request


router = APIRouter(prefix="/api")


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


@router.post("/requests", response_model=RequestRead, status_code=status.HTTP_201_CREATED)
def post_request(payload: RequestCreate, session: Session = Depends(get_session)) -> RequestRead:
    try:
        record = create_request(session, payload)
    except InvalidDeadline as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RequestRead.from_record(record)


@router.get("/requests/{request_id}", response_model=RequestRead)
def read_request(request_id: int, session: Session = Depends(get_session)) -> RequestRead:
    record = get_request(session, request_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Request not found")
    return RequestRead.from_record(record)


@router.get("/system/health")
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Database unavailable") from error
    return {"status": "ok"}
