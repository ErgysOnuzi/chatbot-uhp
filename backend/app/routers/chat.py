"""Endpoint-et publike për studentët."""

import json
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..llm import stream_chat
from ..models import Conversation, Message
from ..rag import NO_ANSWER, NO_ANSWER_MARK, build_messages, retrieval_query, retrieve, sources_from
from ..ratelimit import check_rate_limit, client_ip

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

GENERATION_ERROR = "Ndodhi një gabim gjatë gjenerimit të përgjigjes. Ju lutem provoni përsëri më vonë."


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    conversation_id: str | None = Field(default=None, max_length=36)


class FeedbackRequest(BaseModel):
    value: Literal[1, -1]


def _line(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


@router.post("/chat")
def chat(req: ChatRequest, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(client_ip(request))
    question = req.message.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Pyetja nuk mund të jetë e zbrazët.")

    conversation = db.get(Conversation, req.conversation_id) if req.conversation_id else None
    if conversation is None:
        conversation = Conversation(id=str(uuid.uuid4()))
        db.add(conversation)
        db.commit()

    recent = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.id.desc())
        .limit(6)
    ).all()
    history = [{"role": m.role, "content": m.content} for m in reversed(recent)]

    hits = retrieve(db, retrieval_query(question, history))
    sources = sources_from(hits)
    llm_messages = build_messages(question, hits, history) if hits else None

    db.add(Message(conversation_id=conversation.id, role="user", content=question))
    db.commit()
    conversation_id = conversation.id

    def generate():
        yield _line({"type": "meta", "conversation_id": conversation_id, "sources": sources})
        parts: list[str] = []
        failed = False
        if llm_messages is None:
            parts.append(NO_ANSWER)
            yield _line({"type": "token", "text": NO_ANSWER})
        else:
            try:
                for token in stream_chat(llm_messages):
                    parts.append(token)
                    yield _line({"type": "token", "text": token})
            except Exception:
                logger.exception("Gabim gjatë thirrjes së LLM")
                failed = True
                yield _line({"type": "error", "text": GENERATION_ERROR})

        answer = "".join(parts) if not failed else GENERATION_ERROR
        answered = bool(llm_messages) and not failed and NO_ANSWER_MARK not in answer
        with SessionLocal() as session:
            reply = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=answer,
                question=question,
                answered=answered,
                sources=json.dumps(sources if answered else [], ensure_ascii=False),
            )
            session.add(reply)
            session.commit()
            yield _line({"type": "done", "message_id": reply.id, "answered": answered})

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@router.post("/messages/{message_id}/feedback")
def feedback(message_id: int, req: FeedbackRequest, db: Session = Depends(get_db)):
    message = db.get(Message, message_id)
    if message is None or message.role != "assistant":
        raise HTTPException(status_code=404, detail="Mesazhi nuk u gjet.")
    message.feedback = req.value
    db.commit()
    return {"ok": True}
