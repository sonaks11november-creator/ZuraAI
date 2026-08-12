from typing import List, Dict, Optional
from app.services.mibo_knowledge_base import EXPERTS

def map_concern_to_role_and_specialization(concern: str, severity: str) -> (Optional[str], List[str]):
    """
    Maps a user's concern and its severity to a recommended professional role
    and required specializations.
    """
    concern_lower = concern.lower()
    
    # New: Handle direct requests for doctors or physical symptoms
    if any(c in concern_lower for c in ["headache", "physical", "medical", "doctor", "physician"]):
        return "Psychiatrist", ["General Psychiatry"]
    
    if severity in ["critical", "severe"] or any(c in concern_lower for c in ["severe depression", "suicidal", "bipolar", "schizophrenia"]):
        return "Psychiatrist", [concern]

    if "relationship" in concern_lower or "family" in concern_lower or "couples" in concern_lower:
        return "Clinical Psychologist", ["Relationship Issues", "Couples Therapy", "Family Therapy"]

    if "child" in concern_lower or "teen" in concern_lower or "adolescent" in concern_lower:
        return "Clinical Psychologist", ["Child and Adolescent Psychiatry", "Behavioural Issues"]

    if "stress" in concern_lower or "work burnout" in concern_lower:
        return "Clinical Psychologist", ["Stress", "Anxiety", "Burnout", "Cognitive Behaviour Therapy (CBT)"]
    if "anxiety" in concern_lower:
        return "Clinical Psychologist", ["Anxiety", "Stress", "Cognitive Behaviour Therapy (CBT)", "Dialectical Behaviour Therapy (DBT)"]
    if "depression" in concern_lower:
        return "Clinical Psychologist", ["Depression", "Mood disorders", "Cognitive Behaviour Therapy (CBT)"]
    if "trauma" in concern_lower:
        return "Clinical Psychologist", ["Trauma", "PTSD", "Dialectical Behaviour Therapy (DBT)"]

    # Default fallback
    return "Clinical Psychologist", [concern.title()]

def find_experts(
    concern: str,
    severity: str = "moderate",
    preferences: Dict = None,
    role_override: Optional[str] = None
) -> List[Dict]:
    """
    Finds and ranks suitable experts based on user's concern and preferences using a scoring model.
    
    :param concern: The primary issue the user is facing (e.g., "Anxiety", "Relationship problems").
    :param severity: The severity of the issue ("mild", "moderate", "severe", "critical").
    :param preferences: A dict with user preferences like 'city', 'language', 'consultation_type'.
    :param role_override: Force a search for a specific role (e.g., "Psychiatrist").
    """
    if preferences is None:
        preferences = {}

    role, specializations = map_concern_to_role_and_specialization(concern, severity)
    
    if not role:
        role = "Clinical Psychologist" # Fallback role

    # --- Scoring-based matching instead of filtering ---
    scored_experts = []
    for expert in EXPERTS:
        # Role is a mandatory filter. A psychiatrist and psychologist are not interchangeable for certain severities.
        if expert["role"] != role:
            continue
        
        score = 0
        
        # 1. Specialization Score (+50 for a primary match, +25 for a secondary one)
        primary_spec = specializations[0].lower()
        expert_specs_lower = {s.lower() for s in expert["specializations"]}
        
        if primary_spec in expert_specs_lower:
            score += 50
        elif any(s.lower() in expert_specs_lower for s in specializations):
            score += 25

        # 2. Language Score (+30)
        pref_lang = preferences.get("language")
        if pref_lang and pref_lang.lower() in [l.lower() for l in expert["languages"]]:
            score += 30

        # 3. Consultation Type Score (+20)
        pref_ctype = preferences.get("consultation_type")
        if pref_ctype and pref_ctype in expert["consultation_types"]:
            score += 20
        # Bonus for online availability if in-person was preferred but not available for this expert
        elif pref_ctype == "In-person" and "Online" in expert["consultation_types"]:
            score += 5

        # 4. City Score (+10 for in-person)
        pref_city = preferences.get("city")
        if pref_ctype == "In-person" and pref_city and expert["city"].lower() == pref_city.lower():
            score += 10

        # 5. Experience as a tie-breaker
        try:
            experience = int(expert["experience"].split('+')[0])
            score += experience
        except (ValueError, IndexError):
            pass

        if score > 0:
            scored_experts.append({"expert": expert, "score": score})

    # Sort by score descending
    scored_experts.sort(key=lambda x: x["score"], reverse=True)

    # Return top 3 experts' data
    return [item["expert"] for item in scored_experts[:3]]