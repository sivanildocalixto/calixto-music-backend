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
    style_tags: Optional[str] = None
    prompt_prefix: Optional[str] = None

class GenerateMusicResponse(BaseModel):
    project_id: str
    task_id: str
    message: str

class MusicStatusResponse(BaseModel):
    status: str
    variations: Optional[List[MusicVariation]] = None

# Tags de voz para o campo tags do Suno
VOICE_TAGS = {
    "masculino": "male vocals, male singer, man voice",
    "feminino": "female vocals, female singer, woman voice"
}

# Instrução de voz para colocar na letra (metatag Suno)
VOICE_STYLE = {
    "masculino": "male vocals",
    "feminino": "female vocals"
}

MOOD_TAGS = {
    "alegre": "happy, upbeat, joyful",
    "romantico": "romantic, tender, love",
    "melancolico": "melancholic, sad, emotional",
    "animado": "energetic, exciting, powerful",
    "reflexivo": "reflective, thoughtful, calm",
    "saudade": "nostalgic, longing, saudade"
}

# Mapa de ritmos para tags Suno precisas
RHYTHM_TAGS = {
    "Forro": "forro, accordion, zabumba, forró brasileiro",
    "Forro Universitario": "forro universitario, modern forro, electric guitar",
    "Forro Pe de Serra": "forro pe de serra, traditional forro, accordion",
    "Baiao": "baiao, northeastern brazil, accordion",
    "Xote": "xote, slow forro, romantic northeastern",
    "Arrocha": "arrocha, romantic brazilian, slow",
    "Sertanejo Universitario": "sertanejo universitario, modern brazilian country",
    "Sertanejo Raiz": "sertanejo raiz, traditional country, acoustic guitar",
    "Sertanejo Romantico": "sertanejo romantico, romantic country ballad",
    "Pagode": "pagode, samba pagode, cavaquinho, pandeiro",
    "Samba": "samba, brazilian samba, percussion",
    "Samba Enredo": "samba enredo, carnival samba, epic",
    "Boteco": "pagode boteco, casual samba",
    "Axe": "axe music, bahian carnival, festive",
    "MPB": "mpb, musica popular brasileira, acoustic",
    "Gospel Adoracao": "gospel worship, christian, spiritual, piano",
    "Gospel Louvor": "gospel praise, christian, uplifting, choir",
    "Gospel Infantil": "gospel kids, christian children, joyful",
    "Kidis": "christian kids music, animated, fun",
    "Funk Carioca": "funk carioca, baile funk, 150bpm, heavy bass",
    "Funk Ostentacao": "funk ostentacao, brazilian funk, heavy bass, 150bpm",
    "Brega Funk": "brega funk, pernambuco funk, melodic",
    "Piseiro": "piseiro, forro piseiro, electronic beat",
    "Eletronico": "electronic, EDM, synthesizer, dance",
    "Pop Nacional": "brazilian pop, pop nacional, catchy",
    "Rock Nacional": "rock nacional, brazilian rock, electric guitar",
    "Reggae": "reggae, relaxed, bass guitar",
    "Reggaeton": "reggaeton, latin urban, dembow",
    "Balada": "ballad, slow, emotional, piano",
    "RnB Nacional": "rnb, soul, smooth, groove",
    "Soul Brasileiro": "soul, brazilian soul, groove",
    "Pisadinha": "pisadinha, forro eletrônico, beat"
}

def build_prompt_with_metatags(lyrics: str, voice: str, rhythm: str) -> str:
    """
    Suno respeita metatags dentro da letra no formato [estilo].
    Isso garante voz e ritmo corretos mesmo quando as tags externas são ignoradas.
    """
    voice_style = VOICE_STYLE.get(voice.lower(), "male vocals")
    
    # Adicionar metatags do Suno no início da letra
    # O Suno usa [Verse], [Chorus], [Bridge] etc.
    # Também respeita instruções de estilo no início
    prompt = f"[{voice_style}]\n{lyrics}"
    return prompt

def call_suno_generate(lyrics: str, tags: str, voice: str, rhythm: str) -> dict:
    headers = {
        "Authorization": f"Bearer {SUNO_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Construir prompt com metatags para forçar voz correta
    prompt = build_prompt_with_metatags(lyrics, voice, rhythm)
    
    payload = {
        "prompt": prompt,
        "tags": tags,
        "customMode": True,
        "instrumental": False,
        "model": "V4_5ALL",
        "callBackUrl": "https://webhook.site/placeholder"
    }
    
    logging.info(f"Calling Suno with tags: {tags}")
    logging.info(f"Calling Suno with voice metatag: [{VOICE_STYLE.get(voice.lower(), 'male vocals')}]")
    logging.info(f"Prompt preview: {prompt[:100]}")
    
    response = requests.post(
        f"{SUNO_BASE_URL}/generate",
        json=payload,
        headers=headers,
        timeout=60
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
        timeout=60
    )
    if response.status_code == 404:
        return {"code": 404, "msg": "Processing"}
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Suno API error: {response.text}")
    return response.json()

@api_router.get("/")
async def root():
    return {"message": "Calixto Music API v2"}

@api_router.post("/music/generate", response_model=GenerateMusicResponse)
async def generate_music(request: GenerateMusicRequest):
    try:
        voice_tag = VOICE_TAGS.get(request.voice.lower(), "male vocals, male singer")
        mood_tag = MOOD_TAGS.get(request.mood.lower(), request.mood)
        
        # Pegar tags precisas do ritmo
        rhythm_tag = RHYTHM_TAGS.get(request.rhythm, request.rhythm)
        
        # IMPORTANTE: voz PRIMEIRO nas tags
        tags = f"{voice_tag}, {rhythm_tag}, {mood_tag}"
        
        logging.info(f"Generating music - voice: {request.voice}, rhythm: {request.rhythm}")
        logging.info(f"Final tags: {tags}")

        suno_response = call_suno_generate(request.lyrics, tags, request.voice, request.rhythm)
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
            message="Musica sendo gerada! Aguarde 1-3 minutos."
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
        logging.info(f"Suno status for {project_id}: {str(suno_response)[:200]}")

        if suno_response.get("code") == 404:
            return MusicStatusResponse(status="processing")

        if suno_response.get("code") == 200:
            response_data = suno_response.get("data", {})
            suno_status = response_data.get("status", "")
            logging.info(f"Suno task status: {suno_status}")

            success_statuses = ["FIRST_SUCCESS", "SUCCESS", "COMPLETE", "COMPLETED"]
            
            if suno_status.upper() in success_statuses:
                suno_data = (
                    response_data.get("response", {}).get("sunoData", []) or
                    response_data.get("sunoData", []) or
                    response_data.get("data", []) or
                    response_data.get("songs", []) or []
                )
                
                logging.info(f"Suno data found: {len(suno_data)} songs")
                
                if suno_data:
                    variations = []
                    for song in suno_data[:2]:
                        variations.append(MusicVariation(
                            id=song.get("id", str(uuid.uuid4())),
                            audio_url=song.get("audioUrl") or song.get("audio_url"),
                            image_url=song.get("imageUrl") or song.get("image_url"),
                            title=song.get("title"),
                            duration=song.get("duration")
                        ))
                    await db.music_projects.update_one(
                        {"id": project_id},
                        {"$set": {"status": "completed", "variations": [v.model_dump() for v in variations]}}
                    )
                    return MusicStatusResponse(status="completed", variations=variations)

            if suno_status and suno_status.upper() not in ["PENDING", "PROCESSING", ""]:
                logging.warning(f"Unknown Suno status: {suno_status}")

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
