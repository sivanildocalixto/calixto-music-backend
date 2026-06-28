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
import re

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

VOICE_TAGS = {
    "masculino": "male vocals, male singer",
    "feminino": "female vocals, female singer"
}

VOICE_METATAG = {
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

# Tags em INGLES para cada ritmo - o que o Suno entende
RHYTHM_TAGS = {
    "Forro": "forro, brazilian accordion dance music, northeastern brazil",
    "Forro Universitario": "forro universitario, modern upbeat forro, electric guitar forro",
    "Forro Pe de Serra": "forro pe de serra, traditional accordion forro, rural northeastern brazil",
    "Baiao": "baiao, northeastern brazil folk, syncopated accordion rhythm",
    "Xote": "xote, slow romantic forro, gentle northeastern dance",
    "Arrocha": "arrocha, slow romantic brazilian ballad, sentimental",
    "Sertanejo Universitario": "sertanejo universitario, modern brazilian country pop",
    "Sertanejo Raiz": "sertanejo raiz, traditional brazilian country, acoustic viola caipira",
    "Sertanejo Romantico": "sertanejo romantico, romantic brazilian country ballad",
    "Pagode": "pagode, brazilian samba pagode, cavaquinho, pandeiro, partido alto",
    "Samba": "samba, classic brazilian samba, surdo, tamborim, percussion",
    "Samba Enredo": "samba enredo, carnival escola de samba, epic brass percussion",
    "Boteco": "pagode boteco, casual laid back samba pagode",
    "Axe": "axe, bahian carnival afro-brazilian music, festive brass",
    "MPB": "mpb, musica popular brasileira, bossa nova influenced, sophisticated acoustic",
    "Gospel Adoracao": "christian worship, soft gospel, intimate piano worship, praise and worship",
    "Gospel Louvor": "gospel praise, powerful choir, uplifting christian, energetic gospel",
    "Gospel Infantil": "christian children music, kids gospel, playful joyful worship",
    "Kidis": "kids christian music, animated gospel children, fun praise",
    "Funk Carioca": "funk carioca, baile funk rio de janeiro, 150bpm heavy 808 bass",
    "Funk Ostentacao": "funk ostentacao, ostentation funk brazil, heavy bass 808, rap funk 130bpm",
    "Brega Funk": "brega funk, pernambuco melodic funk, romantic chorus funk, northeastern brazil funk",
    "Piseiro": "piseiro, forro piseiro electronic, dance floor northeastern",
    "Eletronico": "edm electronic dance music, synthesizer, house techno",
    "Pop Nacional": "brazilian pop, pop nacional, catchy radio friendly",
    "Rock Nacional": "rock nacional, hard rock brazil, electric guitar distortion, loud drums",
    "Reggae": "reggae, jamaican rhythm, offbeat guitar skank, bass groove",
    "Reggaeton": "reggaeton, latin urban, dembow beat, perreo",
    "Balada": "power ballad, slow emotional piano, heartfelt strings",
    "RnB Nacional": "r&b soul, smooth groove contemporary, brazilian rnb",
    "Soul Brasileiro": "soul music brazil, funk groove, emotional soul",
    "Pisadinha": "pisadinha, forro pisadinha electronic beat, dance northeastern brazil"
}

def converter_numeros(texto):
    """Converte números em texto para evitar que o Suno leia algarismos."""
    # Lista ordenada do maior para o menor para evitar substituições parciais
    substituicoes = [
        ("1000", "mil"), ("900", "novecentos"), ("800", "oitocentos"),
        ("700", "setecentos"), ("600", "seiscentos"), ("500", "quinhentos"),
        ("400", "quatrocentos"), ("300", "trezentos"), ("200", "duzentos"),
        ("100", "cem"), ("90", "noventa"), ("80", "oitenta"),
        ("70", "setenta"), ("60", "sessenta"), ("50", "cinquenta"),
        ("40", "quarenta"), ("30", "trinta"), ("29", "vinte e nove"),
        ("28", "vinte e oito"), ("27", "vinte e sete"), ("26", "vinte e seis"),
        ("25", "vinte e cinco"), ("24", "vinte e quatro"), ("23", "vinte e tres"),
        ("22", "vinte e dois"), ("21", "vinte e um"), ("20", "vinte"),
        ("19", "dezenove"), ("18", "dezoito"), ("17", "dezessete"),
        ("16", "dezesseis"), ("15", "quinze"), ("14", "quatorze"),
        ("13", "treze"), ("12", "doze"), ("11", "onze"), ("10", "dez"),
        ("9", "nove"), ("8", "oito"), ("7", "sete"), ("6", "seis"),
        ("5", "cinco"), ("4", "quatro"), ("3", "tres"), ("2", "dois"),
        ("1", "um"), ("0", "zero")
    ]
    for num, texto_num in substituicoes:
        # Substituir número isolado (sem dígito adjacente)
        padrao = r'(?<![0-9])' + re.escape(num) + r'(?![0-9])'
        texto = re.sub(padrao, texto_num, texto)
    return texto

def limpar_letra(lyrics):
    """Remove marcações estruturais da letra que o Suno cantaria literalmente."""
    linhas = lyrics.split('\n')
    resultado = []
    for linha in linhas:
        linha_sem_espacos = linha.strip()
        # Remover linhas que são APENAS marcações estruturais
        if re.match(r'^\[?(verso|verse|copla)\s*\d*\]?\s*:?\s*$', linha_sem_espacos, re.IGNORECASE):
            continue
        if re.match(r'^\[?(refrao|refrão|chorus|coro)\s*\d*\]?\s*:?\s*$', linha_sem_espacos, re.IGNORECASE):
            continue
        if re.match(r'^\[?(ponte|bridge|intro|outro|pre.refrao|interludio|solo|hook)\s*\d*\]?\s*:?\s*$', linha_sem_espacos, re.IGNORECASE):
            continue
        if re.match(r'^(titulo|title|nome)\s*[:\-]', linha_sem_espacos, re.IGNORECASE):
            continue
        resultado.append(linha)
    return '\n'.join(resultado).strip()

def build_prompt(lyrics, voice, rhythm):
    """Monta o prompt com metatags que o Suno respeita."""
    voice_meta = VOICE_METATAG.get(voice.lower(), "male vocals")
    rhythm_tags = RHYTHM_TAGS.get(rhythm, rhythm)

    # Limpar letra e converter números
    lyrics_clean = limpar_letra(lyrics)
    lyrics_clean = converter_numeros(lyrics_clean)

    # Metatag com voz e ritmo em inglês - Suno prioriza isso
    prompt = f"[{voice_meta}]\n[{rhythm_tags}]\n{lyrics_clean}"
    logging.info(f"Prompt metatags: [{voice_meta}] [{rhythm_tags[:50]}...]")
    return prompt

def call_suno_generate(lyrics, tags, voice, rhythm):
    headers = {
        "Authorization": f"Bearer {SUNO_API_KEY}",
        "Content-Type": "application/json"
    }
    prompt = build_prompt(lyrics, voice, rhythm)
    payload = {
        "prompt": prompt,
        "tags": tags,
        "customMode": True,
        "instrumental": False,
        "model": "V4_5ALL",
        "callBackUrl": "https://webhook.site/placeholder"
    }
    logging.info(f"Calling Suno - voice: {voice}, rhythm: {rhythm}")
    logging.info(f"Tags: {tags}")
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

def check_suno_status(task_id):
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
    return {"message": "Calixto Music API v3"}

@api_router.post("/music/generate", response_model=GenerateMusicResponse)
async def generate_music(request: GenerateMusicRequest):
    try:
        voice_tag = VOICE_TAGS.get(request.voice.lower(), "male vocals, male singer")
        mood_tag = MOOD_TAGS.get(request.mood.lower(), request.mood)
        rhythm_tag = RHYTHM_TAGS.get(request.rhythm, request.rhythm)

        # Voz PRIMEIRO nas tags externas também
        tags = f"{voice_tag}, {rhythm_tag}, {mood_tag}"

        logging.info(f"Generating music - voice: {request.voice}, rhythm: {request.rhythm}")
        logging.info(f"Final tags: {tags[:100]}")

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
