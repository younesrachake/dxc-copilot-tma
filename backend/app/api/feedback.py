from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt

from app.core.database import get_db
from app.core.config import JWT_SECRET, JWT_ALGORITHM
from app.models.db import Feedback
from app.models.schemas import FeedbackRequest, FeedbackResponse

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


async def _get_current_user_id(request: Request) -> int:
    """Require valid authentication — never fall back to a default user."""
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Non authentifié")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(str(payload.get("sub", 0)))
        if user_id <= 0:
            raise ValueError("Invalid user id")
        return user_id
    except Exception:
        raise HTTPException(status_code=401, detail="Token invalide")


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(req: FeedbackRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = await _get_current_user_id(request)
    fb = Feedback(message_id=req.message_id, user_id=user_id, rating=req.rating, reason=req.reason)
    db.add(fb)
    await db.commit()
    return FeedbackResponse(status="success", message="Feedback enregistré")
