import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.db import JiraTicket
from app.models.schemas import JiraTicketRequest, JiraTicketResponse

router = APIRouter(prefix="/api/jira", tags=["jira"])


@router.post("/ticket", response_model=JiraTicketResponse)
async def create_ticket(req: JiraTicketRequest, db: AsyncSession = Depends(get_db)):
    ticket_key = f"DXC-{uuid.uuid4().hex[:6].upper()}"
    ticket = JiraTicket(
        key=ticket_key,
        summary=req.summary,
        description=req.description,
        priority=req.priority or "Medium",
        status="Created",
        url=f"https://jira.dxc.com/browse/{ticket_key}",
    )
    db.add(ticket)
    await db.commit()
    return JiraTicketResponse(
        key=ticket_key,
        status="Created",
        url=f"https://jira.dxc.com/browse/{ticket_key}"
    )


@router.get("/status/{ticket_key}", response_model=JiraTicketResponse)
async def get_ticket_status(ticket_key: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(JiraTicket).where(JiraTicket.key == ticket_key))
    ticket = result.scalar_one_or_none()
    if not ticket:
        return JiraTicketResponse(key=ticket_key, status="Not Found", url=f"https://jira.dxc.com/browse/{ticket_key}")
    return JiraTicketResponse(
        key=str(ticket.key),
        status=str(ticket.status),
        url=str(ticket.url or f"https://jira.dxc.com/browse/{ticket_key}")
    )
