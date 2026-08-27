import os
import json
import base64
import requests
import database
from fastapi import Depends, FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import models
import schemas
from settlements import calculate_event_debts
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Tabbed V2 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Welcome to Tabbed V2 API - Multi-Receipt Ledger System"}

@app.get("/events/", response_model=list[schemas.EventResponse])
def get_events(owner_token: Optional[str] = None, db: Session = Depends(database.get_db)):
    query = db.query(models.EventModel)
    if owner_token:
        query = query.filter(models.EventModel.owner_token == owner_token)
    return query.all()

@app.post("/events/", response_model=schemas.EventResponse)
def create_event(event: schemas.EventCreate, db: Session = Depends(database.get_db)):
    db_event = models.EventModel(
        name=event.name, 
        owner_token=event.owner_token
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event

@app.delete("/events/{event_id}")
def delete_event(event_id: int, db: Session = Depends(database.get_db)):
    db_event = db.query(models.EventModel).filter(models.EventModel.id == event_id).first()
    if not db_event:
        raise HTTPException(status_code=404, detail="Event not found")
        
    for receipt in db.query(models.ReceiptModel).filter(models.ReceiptModel.event_id == event_id).all():
        db.query(models.ReceiptPayerModel).filter(models.ReceiptPayerModel.receipt_id == receipt.id).delete()
        items = db.query(models.ItemModel).filter(models.ItemModel.receipt_id == receipt.id).all()
        for item in items:
            item.participants = [] 
            db.delete(item)
        db.delete(receipt)
        
    db.query(models.ParticipantModel).filter(models.ParticipantModel.event_id == event_id).delete()
    db.delete(db_event)
    db.commit()
    return {"message": "Event and all associated data deleted successfully"}

@app.delete("/events/delete-all")
def delete_all_events(db: Session = Depends(database.get_db)):
    db.query(models.ReceiptPayerModel).delete()
    items = db.query(models.ItemModel).all()
    for item in items:
        item.participants = []
    db.commit()

    db.query(models.ItemModel).delete()
    db.query(models.ReceiptModel).delete()
    db.query(models.ParticipantModel).delete()
    db.query(models.EventModel).delete()
    db.commit()
    return {"message": "All events and related data deleted successfully."}

@app.post("/participants/", response_model=schemas.ParticipantResponse)
def create_participant(participant: schemas.ParticipantCreate, db: Session = Depends(database.get_db)):
    db_participant = models.ParticipantModel(name=participant.name, event_id=participant.event_id)
    db.add(db_participant)
    db.commit()
    db.refresh(db_participant)
    return db_participant

@app.delete("/participants/{participant_id}")
def delete_participant(participant_id: int, db: Session = Depends(database.get_db)):
    db_participant = db.query(models.ParticipantModel).filter(models.ParticipantModel.id == participant_id).first()
    if not db_participant:
        raise HTTPException(status_code=404, detail="Participant not found")
    
    db.query(models.ReceiptPayerModel).filter(models.ReceiptPayerModel.participant_id == participant_id).delete()
    
    items = db.query(models.ItemModel).filter(models.ItemModel.participants.any(id=participant_id)).all()
    for item in items:
        item.participants.remove(db_participant)
        
    db.delete(db_participant)
    db.commit()
    return {"message": "Participant deleted successfully"}

@app.post("/receipts/", response_model=schemas.ReceiptResponse)
def create_receipt(receipt: schemas.ReceiptCreate, db: Session = Depends(database.get_db)):
    db_receipt = models.ReceiptModel(
        title=receipt.title,
        total_amount=receipt.total_amount,
        event_id=receipt.event_id,
    )
    db.add(db_receipt)
    db.commit()
    db.refresh(db_receipt)
    return db_receipt

@app.delete("/receipts/{receipt_id}")
def delete_receipt(receipt_id: int, db: Session = Depends(database.get_db)):
    db_receipt = db.query(models.ReceiptModel).filter(models.ReceiptModel.id == receipt_id).first()
    if not db_receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    
    db.query(models.ReceiptPayerModel).filter(models.ReceiptPayerModel.receipt_id == receipt_id).delete()
    
    items = db.query(models.ItemModel).filter(models.ItemModel.receipt_id == receipt_id).all()
    for item in items:
        item.participants = [] 
        db.delete(item)
        
    db.delete(db_receipt)
    db.commit()
    return {"message": "Receipt and all associated items deleted successfully"}

@app.put("/receipts/{receipt_id}/payers", response_model=schemas.ReceiptDetail)
def update_receipt_payers(
    receipt_id: int,
    payload: schemas.ReceiptPayersUpdate,
    db: Session = Depends(database.get_db)
):
    db_receipt = db.query(models.ReceiptModel).filter(models.ReceiptModel.id == receipt_id).first()
    if not db_receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    
    db.query(models.ReceiptPayerModel).filter(models.ReceiptPayerModel.receipt_id == receipt_id).delete()
    
    for p_info in payload.payers:
        if p_info.amount_paid > 0:
            db_payer = models.ReceiptPayerModel(
                receipt_id=receipt_id,
                participant_id=p_info.participant_id,
                amount_paid=p_info.amount_paid
            )
            db.add(db_payer)
            
    db.commit()
    db.refresh(db_receipt)
    return db_receipt

# Safe static route defined before any parameterized {field} routes
@app.get("/receipts/{receipt_id}/image")
def get_receipt_image(receipt_id: int, db: Session = Depends(database.get_db)):
    db_receipt = db.query(models.ReceiptModel).filter(models.ReceiptModel.id == receipt_id).first()
    if not db_receipt or not db_receipt.image_url:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"image_url": str(db_receipt.image_url)}

@app.post("/items/", response_model=schemas.ItemResponse)
def create_item(item: schemas.ItemCreate, db: Session = Depends(database.get_db)):
    db_item = models.ItemModel(name=item.name, price=item.price, quantity=item.quantity, receipt_id=item.receipt_id)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

@app.put("/items/{item_id}/assign", response_model=schemas.ItemDetail)
def assign_item_to_participants(
    item_id: int,
    payload: schemas.ItemAssign,
    db: Session = Depends(database.get_db)
):
    db_item = db.query(models.ItemModel).filter(models.ItemModel.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    participants = db.query(models.ParticipantModel).filter(
        models.ParticipantModel.id.in_(payload.participant_ids)
    ).all()
    
    db_item.participants = participants
    db.commit()
    db.refresh(db_item)
    return db_item

@app.put("/items/{item_id}/price")
def update_item_price(item_id: int, payload: dict, db: Session = Depends(database.get_db)):
    db_item = db.query(models.ItemModel).filter(models.ItemModel.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    if "price" in payload:
        db_item.price = float(payload["price"])
        db.commit()
    return {"message": "Price updated"}

@app.post("/items/{item_id}/split")
def split_item(item_id: int, db: Session = Depends(database.get_db)):
    item = db.query(models.ItemModel).filter(models.ItemModel.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    if item.quantity <= 1:
        raise HTTPException(status_code=400, detail="Item quantity must be greater than 1 to split")
    
    unit_price = item.price / item.quantity
    
    new_items = []
    for _ in range(item.quantity):
        new_item = models.ItemModel(
            receipt_id=item.receipt_id,
            name=item.name, 
            price=unit_price,
            quantity=1
        )
        new_item.participants = item.participants[:] 
        db.add(new_item)
        new_items.append(new_item)
        
    db.delete(item)
    db.commit()
    
    return {"message": f"Item split into {item.quantity} individual items successfully."}

@app.put("/receipts/{receipt_id}/{field}")
def update_receipt_fee(receipt_id: int, field: str, payload: dict, db: Session = Depends(database.get_db)):
    db_receipt = db.query(models.ReceiptModel).filter(models.ReceiptModel.id == receipt_id).first()
    if not db_receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    
    allowed_fields = ["tax", "service", "discount", "others", "total_amount", "subtotal"]
    if field in allowed_fields and field in payload:
        setattr(db_receipt, field, float(payload[field]))
        db.commit()
        return {"message": f"{field} updated"}
    raise HTTPException(status_code=400, detail="Invalid field")

@app.get("/events/{event_id}", response_model=schemas.EventDetailResponse)
def get_event_details(event_id: int, db: Session = Depends(database.get_db)):
    db_event = db.query(models.EventModel).filter(models.EventModel.id == event_id).first()
    if not db_event:
        raise HTTPException(status_code=404, detail="Event not found")
    return db_event

@app.get("/events/{event_id}/settlement")
def get_event_settlement(event_id: int, db: Session = Depends(database.get_db)):
    db_event = db.query(models.EventModel).filter(models.EventModel.id == event_id).first()
    if not db_event:
        raise HTTPException(status_code=404, detail="Event not found")

    return calculate_event_debts(db_event)

@app.post("/events/{event_id}/receipts/gemini-bulk-upload")
async def gemini_bulk_upload_receipts(
    event_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(database.get_db)
):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is missing on Railway.")
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    created_receipts = []
    
    for file in files:
        try:
            image_bytes = await file.read()
            base64_image = base64.b64encode(image_bytes).decode("utf-8")
            mime_type = file.content_type or "image/jpeg"
            image_url = f"data:{mime_type};base64,{base64_image}"
            
            payload = {
                "contents": [{
                    "parts": [
                        {
                            "text": (
                                "Analyze this Indonesian food delivery (GrabFood/GoFood) or restaurant receipt image. Extract exactly these fields:\n"
                                "1. 'title': Store name.\n"
                                "2. 'subtotal': Total of food items before fees/taxes.\n"
                                "3. 'tax': 'Pajak', 'PB1', or 'PPN' amount.\n"
                                "4. 'service': 'Service charge' or 'Biaya kemasan resto' (packaging fee).\n"
                                "5. 'discount': Sum of ALL negative (-) amounts (e.g., promo codes, 'Delivery disc'). Ignore distracting text like '10rb' in the name, ONLY read the final minus value on the right.\n"
                                "6. 'others': Sum of ALL positive additional fees (e.g., 'Biaya Pengiriman' / delivery, 'Biaya Pemesanan' / order fee, platform fees).\n"
                                "7. 'total_amount': The exact final 'TOTAL (INCL. TAX)' or 'TOTAL' printed at the bottom of the receipt.\n"
                                "8. 'items': Array of ordered items. 'name' (string), 'price' (total line price, number), 'quantity' (integer). Ignore fees/discounts in the items list.\n\n"
                                "Output strictly valid JSON matching this format without markdown:\n"
                                '{"title": "Store Name", "subtotal": 0.0, "tax": 0.0, "service": 0.0, "discount": 0.0, "others": 0.0, "total_amount": 0.0, "items": [{"name": "Item Name", "price": 0.0, "quantity": 1}]}'
                            )
                        },
                        {"inline_data": {"mime_type": mime_type, "data": base64_image}}
                    ]
                }],
                "generationConfig": {
                    "response_mime_type": "application/json"
                }
            }
            
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, json=payload, headers=headers)
            response_data = response.json()
            
            if "error" in response_data:
                error_msg = response_data["error"].get("message", "Unknown API Error")
                raise HTTPException(status_code=400, detail=f"Gemini API rejected the image: {error_msg}")
            
            text_response = ""
            if "candidates" in response_data and len(response_data["candidates"]) > 0:
                candidate = response_data["candidates"][0]
                parts = candidate.get("content", {}).get("parts", [])
                text_response = "".join(
                    p.get("text", "") for p in parts if not p.get("thought")
                )
            
            cleaned_text = text_response.strip()
            if cleaned_text.startswith("```json"):
                cleaned_text = cleaned_text[7:]
            if cleaned_text.startswith("```"):
                cleaned_text = cleaned_text[3:]
            if cleaned_text.endswith("```"):
                cleaned_text = cleaned_text[:-3]
            cleaned_text = cleaned_text.strip()

            if not cleaned_text:
                continue

            data = json.loads(cleaned_text)
            title = data.get("title", file.filename.split('.')[0])
            
            def parse_float(val):
                if isinstance(val, str):
                    val = val.replace(",", "").replace(".", "").replace("Rp", "").strip()
                try:
                    return float(val or 0.0)
                except (ValueError, TypeError):
                    return 0.0

            total_amount = parse_float(data.get("total_amount", 0))
            subtotal = parse_float(data.get("subtotal", 0))
            tax = parse_float(data.get("tax", 0))
            service = parse_float(data.get("service", 0))
            discount = parse_float(data.get("discount", 0))
            others = parse_float(data.get("others", 0))
            
            items = data.get("items", [])

            db_receipt = models.ReceiptModel(
                title=title,
                total_amount=total_amount,
                subtotal=subtotal,
                tax=tax,
                service=service,
                discount=discount,
                others=others,
                image_url=image_url,
                event_id=event_id
            )
            db.add(db_receipt)
            db.commit()
            db.refresh(db_receipt)

            for item in items:
                item_price = parse_float(item.get("price", 0))
                
                raw_qty = item.get("quantity", 1)
                try:
                    item_qty = int(raw_qty)
                except (ValueError, TypeError):
                    item_qty = 1

                db_item = models.ItemModel(
                    name=item.get("name", "Unknown Item"),
                    price=item_price,
                    quantity=item_qty,
                    receipt_id=db_receipt.id
                )
                db.add(db_item)
            
            db.commit()
            db.refresh(db_receipt)
            created_receipts.append(db_receipt)
            
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            print(f"Error processing {file.filename}: {e}")
            raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
            
    return {"uploaded": len(created_receipts), "receipts": created_receipts}