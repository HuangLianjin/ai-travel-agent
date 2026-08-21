"""API 请求/响应模型。"""

from typing import Any

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=64)


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    session_id: str = ""
    trip_id: str = ""


class GuideCreate(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    city: str = ""
    content: str = Field(min_length=10, max_length=20000)
    source: str = "user"
    trip_id: str = ""
    images: list[str] = []


class CommentCreate(BaseModel):
    content: str = Field(min_length=1, max_length=1000)


class DepartureDateUpdate(BaseModel):
    departure_date: str


class ReviewDecision(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")
    note: str = ""


class ProfileUpdate(BaseModel):
    nickname: str = Field(default="", max_length=40)
    avatar: str = Field(default="", max_length=500)


class FollowUpdate(BaseModel):
    follow: bool = True


class TripResponse(BaseModel):
    id: str
    title: str
    city: str
    params: dict[str, Any]
    itinerary: dict[str, Any]
    version: int
    status: str


class GuideResponse(BaseModel):
    id: str
    title: str
    city: str
    content: str
    status: str
    likes: int
    favorites: int
    created_at: str

