from fastapi import APIRouter, Body, HTTPException
from typing import Dict, Any
from py.affection_system import load_affection_data, save_affection_data

# Create affection system data routes
router = APIRouter(prefix="/api/affection", tags=["Affection System"])

@router.get("/get_data")
async def get_affection_data_api():
    """
    Get affection data for all users
    Returns format: {"UserA": {"love": 10, "Familiarity": 5}, "UserB": {"love": 2}}
    """
    try:
        data = await load_affection_data()
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read affection data: {str(e)}")

@router.post("/save_data")
async def save_affection_data_api(data: Dict[str, Any] = Body(...)):
    """
    Save all affection data (overwrite save)
    Accepts format: {"UserA": {"love": 10, "Familiarity": 5}}
    """
    try:
        await save_affection_data(data)
        return {"status": "success", "message": "Affection data saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save affection data: {str(e)}")