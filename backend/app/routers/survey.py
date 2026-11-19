"""Pyetësori anonim për studentët dhe rezultatet për administratën."""

import json

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import SurveyResponse
from ..ratelimit import check_rate_limit, client_ip
from ..survey import PROGRAMS, SURVEY_STATEMENTS, summarize
from .admin import require_admin

router = APIRouter(tags=["survey"])


class SurveyRequest(BaseModel):
    answers: list[int] = Field(min_length=len(SURVEY_STATEMENTS), max_length=len(SURVEY_STATEMENTS))
    program: str | None = None
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("answers")
    @classmethod
    def scores_in_range(cls, value: list[int]) -> list[int]:
        if any(score < 1 or score > 5 for score in value):
            raise ValueError("Çdo notë duhet të jetë nga 1 deri në 5.")
        return value

    @field_validator("program")
    @classmethod
    def known_program(cls, value: str | None) -> str | None:
        return value if value in PROGRAMS else None


@router.get("/survey")
def survey_form():
    return {"statements": SURVEY_STATEMENTS, "programs": PROGRAMS}


@router.post("/survey", status_code=201)
def submit_survey(req: SurveyRequest, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(f"survey:{client_ip(request)}")
    comment = (req.comment or "").strip() or None
    db.add(SurveyResponse(answers=json.dumps(req.answers), program=req.program, comment=comment))
    db.commit()
    return {"ok": True}


@router.get("/admin/survey")
def survey_results(db: Session = Depends(get_db), _: str = Depends(require_admin)):
    rows = db.execute(select(SurveyResponse.answers, SurveyResponse.program, SurveyResponse.comment)).all()
    return summarize([tuple(r) for r in rows])
