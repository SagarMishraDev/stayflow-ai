from pydantic import BaseModel, ConfigDict


class FAQResponse(BaseModel):
    id: int
    hotel_id: int
    question: str
    answer: str
    category: str | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class FAQCreate(BaseModel):
    hotel_id: int
    question: str
    answer: str
    category: str | None = None
    is_active: bool = True


class FAQUpdate(BaseModel):
    question: str | None = None
    answer: str | None = None
    category: str | None = None
    is_active: bool | None = None
