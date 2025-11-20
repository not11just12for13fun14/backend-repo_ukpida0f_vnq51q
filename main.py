import os
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from hashlib import sha256

from database import db, create_document, get_documents

app = FastAPI(title="Community App API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- Utilities --------------------

def to_str_id(doc: dict):
    if not doc:
        return doc
    d = dict(doc)
    if d.get("_id") is not None:
        d["id"] = str(d.pop("_id"))
    return d

# -------------------- Models --------------------

class RegisterDTO(BaseModel):
    email: EmailStr
    name: str
    password: str

class LoginDTO(BaseModel):
    email: EmailStr
    password: str

class CreateAnnouncementDTO(BaseModel):
    community_id: str
    title: str
    message: str
    author_id: Optional[str] = None

class CreateEventDTO(BaseModel):
    community_id: str
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    starts_at: datetime
    ends_at: Optional[datetime] = None

class JoinCommunityDTO(BaseModel):
    community_id: str
    user_id: str

class CheckInDTO(BaseModel):
    user_id: str
    community_id: Optional[str] = None
    lat: float
    lng: float
    share_status: bool = True
    note: Optional[str] = None

# -------------------- Root/Test --------------------

@app.get("/")
def read_root():
    return {"message": "Community API running"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    return response

# -------------------- Auth --------------------

@app.post("/api/auth/register")
def register(body: RegisterDTO):
    if db is None:
        raise HTTPException(status_code=500, detail="Database unavailable")
    existing = db["authuser"].find_one({"email": body.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    password_hash = sha256(body.password.encode()).hexdigest()
    user = {
        "email": body.email,
        "name": body.name,
        "password_hash": password_hash,
        "avatar_url": None,
        "locale": "id",
        "role": "user",
        "is_active": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    new_id = db["authuser"].insert_one(user).inserted_id
    user_out = {"id": str(new_id), "email": body.email, "name": body.name, "role": "user"}
    return {"user": user_out}

@app.post("/api/auth/login")
def login(body: LoginDTO):
    if db is None:
        raise HTTPException(status_code=500, detail="Database unavailable")
    password_hash = sha256(body.password.encode()).hexdigest()
    user = db["authuser"].find_one({"email": body.email, "password_hash": password_hash})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    u = to_str_id(user)
    # naive session token substitute (NOT for production)
    token = sha256((u["id"] + u["email"]).encode()).hexdigest()
    return {"user": {"id": u["id"], "email": u["email"], "name": u.get("name")}, "token": token}

# -------------------- Dashboard --------------------

@app.get("/api/dashboard")
def dashboard(user_id: Optional[str] = None):
    if db is None:
        return {"active_members": 0, "events_this_month": 0, "new_messages": 0}
    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)
    active_members = db["membership"].count_documents({"status": "active"})
    events_this_month = db["event"].count_documents({"starts_at": {"$gte": month_start}})
    new_messages = db["announcement"].count_documents({"created_at": {"$gte": month_start}})
    upcoming_events = [to_str_id(e) for e in db["event"].find({"starts_at": {"$gte": now}}).sort("starts_at", 1).limit(5)]
    announcements = [to_str_id(a) for a in db["announcement"].find({}).sort("created_at", -1).limit(5)]
    return {
        "stats": {
            "active_members": active_members,
            "events_this_month": events_this_month,
            "new_messages": new_messages,
        },
        "upcoming_events": upcoming_events,
        "announcements": announcements,
    }

# -------------------- Communities --------------------

@app.get("/api/communities")
def list_communities(q: Optional[str] = None, tab: Optional[str] = None, user_id: Optional[str] = None, limit: int = 20):
    if db is None:
        return {"items": [], "count": 0}
    query = {}
    if q:
        query["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}},
        ]
    if tab == "mine" and user_id:
        my_ids = [m["community_id"] for m in db["membership"].find({"user_id": user_id})]
        query["_id"] = {"$in": [c for c in db["community"].find({"_id": {"$in": my_ids}})]}  # will be overridden below
        # Simpler approach: filter after query
    cursor = db["community"].find(query).limit(limit)
    items = [to_str_id(c) for c in cursor]
    if tab == "mine" and user_id:
        member_ids = {m["community_id"] for m in db["membership"].find({"user_id": user_id})}
        items = [c for c in items if c["id"] in member_ids]
    return {"items": items, "count": len(items)}

@app.get("/api/communities/{community_id}")
def community_detail(community_id: str):
    c = db["community"].find_one({"_id": community_id}) if db else None
    if not c and db is not None:
        # try ObjectId as string pattern not enforced, so store id as string in this environment
        c = db["community"].find_one({"_id": community_id})
    if not c:
        raise HTTPException(status_code=404, detail="Community not found")
    members = [to_str_id(m) for m in db["membership"].find({"community_id": community_id})]
    stats = {
        "member_count": len(members),
        "events": db["event"].count_documents({"community_id": community_id}),
        "announcements": db["announcement"].count_documents({"community_id": community_id}),
    }
    return {"community": to_str_id(c), "members": members, "stats": stats}

@app.post("/api/communities/join")
def join_community(body: JoinCommunityDTO):
    if db is None:
        raise HTTPException(status_code=500, detail="Database unavailable")
    existing = db["membership"].find_one({"community_id": body.community_id, "user_id": body.user_id})
    if existing:
        return {"status": "already_member"}
    db["membership"].insert_one({
        "community_id": body.community_id,
        "user_id": body.user_id,
        "role": "member",
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    })
    db["community"].update_one({"_id": body.community_id}, {"$inc": {"member_count": 1}})
    return {"status": "joined"}

# -------------------- Announcements & Events --------------------

@app.get("/api/announcements")
def list_announcements(community_id: Optional[str] = None, limit: int = 20):
    if db is None:
        return {"items": []}
    q = {"community_id": community_id} if community_id else {}
    items = [to_str_id(a) for a in db["announcement"].find(q).sort("created_at", -1).limit(limit)]
    return {"items": items}

@app.post("/api/announcements")
def create_announcement(body: CreateAnnouncementDTO):
    if db is None:
        raise HTTPException(status_code=500, detail="Database unavailable")
    doc = {
        "community_id": body.community_id,
        "title": body.title,
        "message": body.message,
        "author_id": body.author_id,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    new_id = db["announcement"].insert_one(doc).inserted_id
    return {"id": str(new_id)}

@app.get("/api/events")
def list_events(community_id: Optional[str] = None, upcoming: bool = True, limit: int = 20):
    if db is None:
        return {"items": []}
    now = datetime.utcnow()
    q = {"community_id": community_id} if community_id else {}
    if upcoming:
        q["starts_at"] = {"$gte": now}
    items = [to_str_id(e) for e in db["event"].find(q).sort("starts_at", 1).limit(limit)]
    return {"items": items}

@app.post("/api/events")
def create_event(body: CreateEventDTO):
    if db is None:
        raise HTTPException(status_code=500, detail="Database unavailable")
    doc = body.model_dump()
    doc["created_at"] = datetime.utcnow()
    doc["updated_at"] = datetime.utcnow()
    new_id = db["event"].insert_one(doc).inserted_id
    return {"id": str(new_id)}

# -------------------- Check-in --------------------

@app.post("/api/checkin")
def checkin(body: CheckInDTO):
    if db is None:
        raise HTTPException(status_code=500, detail="Database unavailable")
    doc = body.model_dump()
    doc["created_at"] = datetime.utcnow()
    new_id = db["checkin"].insert_one(doc).inserted_id
    return {"status": "ok", "id": str(new_id)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
