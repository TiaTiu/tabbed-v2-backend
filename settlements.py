def calculate_session_debts(session_data):
    participants = session_data.participants
    receipts = session_data.receipts

    if not participants:
        return {"total_session_spend": 0, "share_per_person": 0, "participant_breakdown": [], "settlements": []}

    num_participants = len(participants)
    total_spend = sum(receipt.total_amount for receipt in receipts)
    share_per_person = total_spend / num_participants if num_participants > 0 else 0

    balances = {p.id: {"name": p.name, "net": 0.0} for p in participants}
    
    participant_breakdown_map = {
        p.id: {"name": p.name, "total_spent": 0.0, "total_paid": 0.0, "items": []} 
        for p in participants
    }

    for receipt in receipts:
        receipt_paid_total = 0.0
        for payer_info in receipt.payers:
            if payer_info.participant_id in balances:
                balances[payer_info.participant_id]["net"] += payer_info.amount_paid
                receipt_paid_total += payer_info.amount_paid
                if payer_info.participant_id in participant_breakdown_map:
                    participant_breakdown_map[payer_info.participant_id]["total_paid"] += payer_info.amount_paid

        if receipt_paid_total == 0 and num_participants > 0:
            even_paid = receipt.total_amount / num_participants
            for p_id in balances:
                balances[p_id]["net"] += even_paid
                if p_id in participant_breakdown_map:
                    participant_breakdown_map[p_id]["total_paid"] += even_paid

        assigned_total = 0.0
        has_assignments = any(len(item.participants) > 0 for item in receipt.items)

        # Collect all unique participants involved in this specific receipt
        receipt_participant_ids = set()
        for item in receipt.items:
            for p in item.participants:
                receipt_participant_ids.add(p.id)

        if has_assignments:
            for item in receipt.items:
                if item.participants:
                    item_total_price = item.price 
                    split_amount = item_total_price / len(item.participants)
                    item_qty = int(item.quantity) if (item.quantity and len(item.participants) == 1) else 1
                    
                    for p in item.participants:
                        if p.id in balances:
                            balances[p.id]["net"] -= split_amount
                            if p.id in participant_breakdown_map:
                                participant_breakdown_map[p.id]["total_spent"] += split_amount
                                participant_breakdown_map[p.id]["items"].append({
                                    "name": item.name,
                                    "quantity": item_qty,
                                    "price": split_amount
                                })
                    assigned_total += item_total_price

            # Distribute unassigned remainder (tax/tip/discounts) ONLY among participants of this receipt
            remainder = receipt.total_amount - assigned_total
            if remainder != 0 and len(receipt_participant_ids) > 0:
                even_split = remainder / len(receipt_participant_ids)
                for p_id in receipt_participant_ids:
                    if p_id in balances:
                        balances[p_id]["net"] -= even_split
                        if p_id in participant_breakdown_map:
                            participant_breakdown_map[p_id]["total_spent"] += even_split
                            participant_breakdown_map[p_id]["items"].append({
                                "name": "Tax / Discount / Other (Split)",
                                "quantity": 1,
                                "price": even_split
                            })
        else:
            if num_participants > 0:
                even_split = receipt.total_amount / num_participants
                for p_id in balances:
                    balances[p_id]["net"] -= even_split
                    if p_id in participant_breakdown_map:
                        participant_breakdown_map[p_id]["total_spent"] += even_split
                        participant_breakdown_map[p_id]["items"].append({
                            "name": f"{receipt.title} (Unassigned Split)",
                            "quantity": 1,
                            "price": even_split
                        })

    debtors = []
    creditors = []
    for p_id, data in balances.items():
        if p_id in participant_breakdown_map:
            participant_breakdown_map[p_id]["net_balance"] = data["net"]

        if data["net"] < -0.01:
            debtors.append({"id": p_id, "name": data["name"], "amount": -data["net"]})
        elif data["net"] > 0.01:
            creditors.append({"id": p_id, "name": data["name"], "amount": data["net"]})

    settlements = []
    d_idx = 0
    c_idx = 0

    while d_idx < len(debtors) and c_idx < len(creditors):
        debtor = debtors[d_idx]
        creditor = creditors[c_idx]

        transfer_amount = min(debtor["amount"], creditor["amount"])
        
        settlements.append({
            "from": debtor["name"],
            "to": creditor["name"],
            "amount": transfer_amount
        })

        debtor["amount"] -= transfer_amount
        creditor["amount"] -= transfer_amount

        if debtor["amount"] < 0.01:
            d_idx += 1
        if creditor["amount"] < 0.01:
            c_idx += 1

    return {
        "total_session_spend": total_spend,
        "share_per_person": share_per_person,
        "participant_breakdown": list(participant_breakdown_map.values()),
        "settlements": settlements
    }