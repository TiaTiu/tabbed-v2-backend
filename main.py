import os
import json
import base64
import requests
import database
from fastapi import Depends, FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import models
import schemas
from settlements import calculate_session_debts
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

@app.get("/sessions/", response_model=list[schemas.SessionResponse])
def get_sessions(db: Session = Depends(database.get_db)):
    return db.query(models.SessionModel).all()

@app.post("/sessions/", response_model=schemas.SessionResponse)
def create_session(session: schemas.SessionCreate, db: Session = Depends(database.get_db)):
    db_session = models.SessionModel(name=session.name)
    db.add(db_session)
    db.commit()
    db.refresh(db_session)
    return db_session

@app.post("/participants/", response_model=schemas.ParticipantResponse)
def create_participant(participant: schemas.ParticipantCreate, db: Session = Depends(database.get_db)):
    db_participant = models.ParticipantModel(name=participant.name, session_id=participant.session_id)
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
        session_id=receipt.session_id,
    )
    db.add(db_receipt)
    db.commit()
    db.refresh(db_receipt)
    return db_receipt

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

@app.get("/sessions/{session_id}", response_model=schemas.SessionDetailResponse)
def get_session_details(session_id: int, db: Session = Depends(database.get_db)):
    db_session = db.query(models.SessionModel).filter(models.SessionModel.id == session_id).first()
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")
    return db_session

@app.get("/sessions/{session_id}/settlement")
def get_session_settlement(session_id: int, db: Session = Depends(database.get_db)):
    db_session = db.query(models.SessionModel).filter(models.SessionModel.id == session_id).first()
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")

    return calculate_session_debts(db_session)

@app.post("/sessions/{session_id}/receipts/gemini-bulk-upload")
async def gemini_bulk_upload_receipts(
    session_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(database.get_db)
):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is missing on Railway.")
        
    # CHANGE THIS:
    # url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"

    # TO THIS:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
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
                        {"text": "Analyze this food delivery receipt or invoice image. Look for the store name as 'title', the final grand total amount as a number under 'total_amount', and all ordered food/drink items under 'items'. Each item object must have 'name' (string), 'price' (number - total price for that line), and 'quantity' (integer, look at multipliers like '1x' or '2x' at the start of the item name, default to 1). Output valid JSON strictly matching this format without markdown code blocks: {\"title\": \"Store Name\", \"total_amount\": 77785.0, \"items\": [{\"name\": \"Full Flavored Thai Milk Tea\", \"price\": 40700.0, \"quantity\": 1}]}"},
                        {"inline_data": {"mime_type": mime_type, "data": base64_image}}
                    ]
                }],
                "generationConfig": {
                    "response_mime_type": "application/json",
                    "thinking_config": {"thinking_level": "low"}
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
            
            raw_total = data.get("total_amount", 0)
            if isinstance(raw_total, str):
                raw_total = raw_total.replace(",", "").replace(".", "").replace("Rp", "").strip()
            total_amount = float(raw_total or 0.0)
            
            items = data.get("items", [])

            db_receipt = models.ReceiptModel(
                title=title,
                total_amount=total_amount,
                image_url=image_url,
                session_id=session_id
            )
            db.add(db_receipt)
            db.commit()
            db.refresh(db_receipt)

            for item in items:
                raw_price = item.get("price", 0)
                if isinstance(raw_price, str):
                    raw_price = raw_price.replace(",", "").replace(".", "").replace("Rp", "").strip()
                item_price = float(raw_price or 0.0)
                
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