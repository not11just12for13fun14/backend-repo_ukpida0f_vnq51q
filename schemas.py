"""
Database Schemas for Community App

Each Pydantic model represents a MongoDB collection. The collection name is the lowercase of the class name.
"""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, EmailStr
from datetime import datetime

# Auth/User
class AuthUser(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=2, max_length=80)
    password_hash: str
    avatar_url: Optional[str] = None
    locale: Optional[str] = Field("id", description="Preferred locale code")
    role: Literal["user", "admin"] = "user"
    is_active: bool = True

# Community
class Community(BaseModel):
    title: str
    description: str
    category: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    is_public: bool = True
    admins: List[str] = Field(default_factory=list, description="List of user ids as strings")
    member_count: int = 0
    tags: List[str] = Field(default_factory=list)

# Membership (user in community)
class Membership(BaseModel):
    user_id: str
    community_id: str
    role: Literal["member", "admin"] = "member"
    status: Literal["active", "pending"] = "active"

# Event within a community
class Event(BaseModel):
    community_id: str
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    starts_at: datetime
    ends_at: Optional[datetime] = None

# Announcements for a community
class Announcement(BaseModel):
    community_id: str
    title: str
    message: str
    author_id: Optional[str] = None
    pinned: bool = False

# User check-ins
class CheckIn(BaseModel):
    user_id: str
    community_id: Optional[str] = None
    lat: float
    lng: float
    share_status: bool = True
    note: Optional[str] = None
