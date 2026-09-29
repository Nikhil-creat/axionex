"""Trust & Compliance Auditor endpoints."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.compliance_scanner import CHECKLIST, ComplianceScanner

router = APIRouter(prefix="/compliance", tags=["compliance"])


class ScanRequest(BaseModel):
    url: str = Field(min_length=3, max_length=2000, description="Storefront URL to audit, e.g. https://yourbrand.com")


@router.get("/checklist")
async def checklist() -> list[dict]:
    return [{"key": k, "label": label} for k, label in CHECKLIST]


@router.post("/scan")
async def scan(body: ScanRequest) -> dict:
    try:
        return await ComplianceScanner().scan(body.url)
    except Exception as exc:
        raise HTTPException(422, f"Could not fetch or parse that URL: {exc}")
