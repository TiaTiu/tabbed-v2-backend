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
def get_events(db: Session = Depends(database.get_db)):
    return db.query(models.EventModel).all()

@app.post("/events/", response_model=schemas.EventResponse)
def create_event(event: schemas.EventCreate, db: Session = Depends(database.get_db)):
    db_event = models.EventModel(name=event.name)
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event

@app.delete("/events/{event_id}")
def delete_event(event_id: int, db: Session = Depends(database.get_db)):
    db_event = db.query(models.EventModel).filter(models.EventModel.id == event_id).first()
    if not db_event:
        raise HTTPException(status_code=404, detail="Event not found")

    receipts = db.query(models.ReceiptModel).filter(models.ReceiptModel.event_id == event_id).all()
    for r in receipts:
        db.query(models.ReceiptPayerModel).filter(models.ReceiptPayerModel.receipt_id == r.id).delete()
        db.query(models.ItemModel).filter(models.ItemModel.receipt_id == r.id).delete()
        db.delete(r)

    db.query(models.ParticipantModel).filter(models.ParticipantModel.event_id == event_id).delete()
    
    db.delete(db_event)
    db.commit()
    return {"message": "Event and all associated data deleted successfully"}

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
    
    db.delete(db_receipt)
    db.commit()
    return {"message": "Receipt deleted successfully"}

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
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key={api_key}"
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
                        {"text": "Analyze this food delivery or restaurant receipt image. Extract the store name as 'title', 'subtotal', 'tax' (pajak/PPN), 'service' (servis/resto), 'discount' (diskon/promo/vouchers as negative or positive numbers matching receipt), 'others' (delivery fees, packaging/biaya kemasan, platform/biaya pemesanan), final grand total amount as 'total_amount', and all ordered food/drink items under 'items'. Each item object must have 'name' (string), 'price' (number - total line price), and 'quantity' (integer, look at multipliers like '1x' or '2x', default to 1). Output valid JSON strictly matching this format without markdown code blocks: {\"title\": \"Store Name\", \"subtotal\": 108900.0, \"tax\": 9900.0, \"service\": 0.0, \"discount\": -38115.0, \"others\": 16000.0, \"total_amount\": 77785.0, \"items\": [{\"name\": \"Full Flavored Thai Milk Tea\", \"price\": 40700.0, \"quantity\": 1}]}"},
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