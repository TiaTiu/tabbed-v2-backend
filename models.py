from database import Base
from sqlalchemy import Column, Float, ForeignKey, Integer, String, Table, Boolean
from sqlalchemy.orm import relationship, deferred

item_participant_association = Table(
    "item_participants",
    Base.metadata,
    Column("item_id", Integer, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
    Column("participant_id", Integer, ForeignKey("participants.id", ondelete="CASCADE"), primary_key=True)
)

class EventModel(Base):
  __tablename__ = "events"
  id = Column(Integer, primary_key=True, index=True)
  name = Column(String, index=True)
  owner_token = Column(String, nullable=True, index=True)

  receipts = relationship("ReceiptModel", back_populates="event", cascade="all, delete-orphan")
  participants = relationship("ParticipantModel", back_populates="event", cascade="all, delete-orphan")

class ParticipantModel(Base):
  __tablename__ = "participants"
  id = Column(Integer, primary_key=True, index=True)
  name = Column(String, index=True)
  event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"))

  event = relationship("EventModel", back_populates="participants")
  items = relationship("ItemModel", secondary=item_participant_association, back_populates="participants")

class ReceiptModel(Base):
  __tablename__ = "receipts"
  id = Column(Integer, primary_key=True, index=True)
  title = Column(String)
  total_amount = Column(Float)
  
  # Heavy image column deferred to fix the 15-second lag
  image_url = deferred(Column(String, nullable=True))
  
  # Real column so Pydantic can read it instantly without triggering a heavy query
  has_image = Column(Boolean, default=False)
  
  event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"))

  subtotal = Column(Float, default=0.0)
  tax = Column(Float, default=0.0)
  service = Column(Float, default=0.0)
  discount = Column(Float, default=0.0)
  others = Column(Float, default=0.0)

  event = relationship("EventModel", back_populates="receipts")
  items = relationship("ItemModel", back_populates="receipt", cascade="all, delete-orphan")
  payers = relationship("ReceiptPayerModel", back_populates="receipt", cascade="all, delete-orphan")

class ReceiptPayerModel(Base):
  __tablename__ = "receipt_payers"
  receipt_id = Column(Integer, ForeignKey("receipts.id", ondelete="CASCADE"), primary_key=True)
  participant_id = Column(Integer, ForeignKey("participants.id", ondelete="CASCADE"), primary_key=True)
  amount_paid = Column(Float, default=0.0)

  receipt = relationship("ReceiptModel", back_populates="payers")
  participant = relationship("ParticipantModel")

class ItemModel(Base):
  __tablename__ = "items"
  __table_args__ = {'extend_existing': True}
  id = Column(Integer, primary_key=True, index=True)
  name = Column(String)
  price = Column(Float)
  quantity = Column(Integer, default=1)
  receipt_id = Column(Integer, ForeignKey("receipts.id", ondelete="CASCADE"))

  receipt = relationship("ReceiptModel", back_populates="items")
  participants = relationship("ParticipantModel", secondary=item_participant_association, back_populates="items")