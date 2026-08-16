from pydantic import BaseModel

class SessionCreate(BaseModel):
  name: str

class SessionResponse(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True

class ParticipantCreate(BaseModel):
  name: str
  session_id: int

class ParticipantResponse(BaseModel):
  id: int
  name: str
  session_id: int

  class Config:
    from_attributes = True

class ReceiptCreate(BaseModel):
  title: str
  total_amount: float
  session_id: int

class PayerContribution(BaseModel):
  participant_id: int
  amount_paid: float

class ReceiptPayersUpdate(BaseModel):
  payers: list[PayerContribution]

class ParticipantDetail(BaseModel):
  id: int
  name: str

  class Config:
    from_attributes = True

class ReceiptPayerDetail(BaseModel):
  participant_id: int
  amount_paid: float
  participant: ParticipantDetail | None = None

  class Config:
    from_attributes = True

class ItemCreate(BaseModel):
  name: str
  price: float
  quantity: int = 1
  receipt_id: int

class ItemAssign(BaseModel):
  participant_ids: list[int]

class ItemResponse(BaseModel):
  id: int
  name: str
  price: float
  quantity: int = 1
  receipt_id: int
  participants: list[ParticipantDetail] = []

  class Config:
    from_attributes = True

class ItemDetail(BaseModel):
  id: int
  name: str
  price: float
  quantity: int = 1
  participants: list[ParticipantDetail] = []

  class Config:
    from_attributes = True

class ReceiptDetail(BaseModel):
  id: int
  title: str
  total_amount: float
  image_url: str | None = None
  subtotal: float = 0.0
  tax: float = 0.0
  service: float = 0.0
  discount: float = 0.0
  others: float = 0.0
  payers: list[ReceiptPayerDetail] = []
  items: list[ItemDetail] = []

  class Config:
    from_attributes = True

class ReceiptResponse(BaseModel):
  id: int
  title: str
  total_amount: float
  session_id: int
  image_url: str | None = None
  subtotal: float = 0.0
  tax: float = 0.0
  service: float = 0.0
  discount: float = 0.0
  others: float = 0.0
  payers: list[ReceiptPayerDetail] = []

  class Config:
    from_attributes = True

class SessionDetailResponse(BaseModel):
  id: int
  name: str
  participants: list[ParticipantDetail] = []
  receipts: list[ReceiptDetail] = []

  class Config:
    from_attributes = True