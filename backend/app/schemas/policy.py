from pydantic import BaseModel, ConfigDict


class PolicyResponse(BaseModel):
    id: int
    hotel_id: int
    policy_type: str
    title: str
    description: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class PolicyCreate(BaseModel):
    hotel_id: int
    policy_type: str
    title: str
    description: str
    is_active: bool = True


class PolicyUpdate(BaseModel):
    policy_type: str | None = None
    title: str | None = None
    description: str | None = None
    is_active: bool | None = None
