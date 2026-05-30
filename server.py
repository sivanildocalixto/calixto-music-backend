from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone
import requests

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url, tlsAllowInvalidCertificates=True)
db = client[os.environ['DB_NAME']]

SUNO_API_KEY = os.environ.get('SUNO_API_KEY')
SUNO_BASE_URL = "https://api.sunoapi.org/api/v1"

app = FastAPI()
api_router = APIRouter(prefix="/api")

class MusicVariation(BaseModel):
    id: str
    audio_url: Optional[str] = None
    image_url: Optional[str] = None
    title: Optional[str] = None
    duration: Optional[float] = None

class MusicProject(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    lyrics: str
    rhythm: str
    voice: str
    mood: str
    task_id: Optional[str] = None
    status: str = "pending"
    variations: List[MusicVariation] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class GenerateMusicRequest(BaseModel):
    lyrics: str
    rhythm: str
    voice: str
    mood: str
    voice_tag: Optional[str] = None

class GenerateMusicResponse(BaseModel):
    project_id: str
    task_id: str
    message: str

class MusicStatusResponse(BaseModel):
    status: str
    variations: Optional[List[MusicVariation]] = None

VOICE_MAP = {
    "masculino": "male voice, male singer, man singing",
    "feminino": "female voice, female singer, woman singing"
}

MOOD_MAP = {
    "alegre": "happy, upbeat, joyful",
    "romantico": "romantic, tender, love song",
    "melancolico": "melancholic, sad, emotional",
    "animado": "energetic, exciting, powerful",
    "reflexivo": "reflective, thoughtful, calm",
    "saudade": "nostalgic, longing, saudade"
}

def call_suno_generate(lyrics: str, tags: str) -> dict:
    headers = {
        "Authorization": f"Bearer {SUNO_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "prompt": lyrics,
        "tags": tags,
        "customMode": True,
        "instrumental": False,
        "model": "V4_5ALL",
        "callBackUrl": "https://webhook.site/placeholder"
    }
    logging.info(f"Calling Suno with tags: {tags}")
    response = requests.post(
        f"{SUNO_BASE_URL}/generate",
        json=payload,
        headers=headers,
        timeout=30
    )
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Suno API error: {response.text}")
    data = response.json()
    if data.get("code") != 200:
        raise HTTPException(status_code=500, detail=f"Suno API error: {data.get('msg', 'Unknown error')}")
    return data

def check_suno_status(task_id: str) -> dict:
    headers = {"Authorization": f"Bearer {SUNO_API_KEY}"}
    response = requests.get(
        f"{SUNO_BASE_URL}/generate/record-info",
        params={"taskId": task_id},
        headers=headers,
        timeout=30
    )
    if response.status_code == 404:
        return {"code": 404, "msg": "Processing"}
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Suno API error: {response.text}")
    return response.json()

@api_router.get("/")
async def root():
    return {"message": "Calixto Music API"}

@api_router.post("/music/generate", response_model=GenerateMusicResponse)
async def generate_music(request: GenerateMusicRequest):
    try:
        voice_tag = VOICE_MAP.get(request.voice.lower(), request.voice_tag or "male voice")
        mood_tag = MOOD_MAP.get(request.mood.lower(), request.mood)
        tags = f"{request.rhythm}, {voice_tag}, {mood_tag}"

        suno_response = call_suno_generate(request.lyrics, tags)
        task_id = suno_response.get("data", {}).get("taskId")

        if not task_id:
            raise HTTPException(status_code=500, detail="Failed to get task ID from Suno")

        project = MusicProject(
            lyrics=request.lyrics,
            rhythm=request.rhythm,
            voice=request.voice,
            mood=request.mood,
            task_id=task_id,
            status="processing"
        )
        doc = project.model_dump()
        doc['created_at'] = doc['created_at'].isoformat()
        await db.music_projects.insert_one(doc)

        return GenerateMusicResponse(
            project_id=project.id,
            task_id=task_id,
            message="Musica sendo gerada! Aguarde 1-2 minutos."
        )
    except Exception as e:
        logging.error(f"Error generating music: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/music/status/{project_id}", response_model=MusicStatusResponse)
async def check_music_status(project_id: str):
    try:
        if not project_id or project_id == "undefined":
            raise HTTPException(status_code=400, detail="Invalid project ID")

        project = await db.music_projects.find_one({"id": project_id}, {"_id": 0})
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        if project.get("status") == "completed":
            variations = [MusicVariation(**v) for v in project.get("variations", [])]
            return MusicStatusResponse(status="completed", variations=variations)

        suno_response = check_suno_status(project.get("task_id"))

        if suno_response.get("code") == 404:
            return MusicStatusResponse(status="processing")

        if suno_response.get("code") == 200:
            response_data = suno_response.get("data", {})
            if response_data.get("status") == "FIRST_SUCCESS":
                suno_data = response_data.get("response", {}).get("sunoData", [])
                if suno_data:
                    variations = []
                    for song in suno_data[:2]:
                        variations.append(MusicVariation(
                            id=song.get("id", str(uuid.uuid4())),
                            audio_url=song.get("audioUrl"),
                            image_url=song.get("imageUrl"),
                            title=song.get("title"),
                            duration=song.get("duration")
                        ))
                    await db.music_projects.update_one(
                        {"id": project_id},
                        {"$set": {"status": "completed", "variations": [v.model_dump() for v in variations]}}
                    )
                    return MusicStatusResponse(status="completed", variations=variations)

        return MusicStatusResponse(status="processing")
    except Exception as e:
        logging.error(f"Error checking status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/music/projects", response_model=List[MusicProject])
async def get_projects():
    try:
        projects = await db.music_projects.find({}, {"_id": 0}).sort("created_at", -1).to_list(100)
        for project in projects:
            if isinstance(project.get('created_at'), str):
                project['created_at'] = datetime.fromisoformat(project['created_at'])
        return projects
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.delete("/music/projects/{project_id}")
async def delete_project(project_id: str):
    try:
        await db.music_projects.delete_one({"id": project_id})
        return {"message": "Projeto deletado"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

app.include_router(api_router)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
