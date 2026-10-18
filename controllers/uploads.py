from fastapi import APIRouter, UploadFile, File, Depends
from fastapi.responses import JSONResponse
import shutil
import os
import uuid

from auth.security import get_current_user

router = APIRouter()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("")
async def upload_file(
    file: UploadFile = File(...), 
    user_data: dict = Depends(get_current_user)
):
    """
    POST /api/upload
    Uploads a file and returns the filename.
    """
    try:
        # Generate a unique filename to prevent collisions
        ext = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{ext}"
        
        file_path = os.path.join(UPLOAD_DIR, unique_filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        return {"filename": unique_filename, "url": f"/uploads/{unique_filename}"}
    except Exception as e:
        return JSONResponse({"error": True, "message": str(e)}, status_code=500)
