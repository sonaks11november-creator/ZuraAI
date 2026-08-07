from typing import List, Dict, Optional
from app.services.mibo_knowledge_base import EXPERTS

def map_concern_to_role_and_specialization(concern: str, severity: str) -> (Optional[str], List[str]):
    """
    Maps a user's concern and its severity to a recommended professional role
    and required specializations.
    """
    concern_lower = concern.lower()
    
    if severity in ["critical", "severe"] or any(c in concern_lower for c in ["severe depression", "suicidal", "bipolar", "schizophrenia"]):
        return "Psychiatrist", [concern]

    if "relationship" in concern_lower or "family" in concern_lower or "couples" in concern_lower:
        return "Relationship Counsellor", ["Relationship Issues", "Couples Therapy"]

    if "child" in concern_lower or "teen" in concern_lower or "adolescent" in concern_lower:
        return "Clinical Psychologist", ["Child and Adolescent Psychiatry", "Behavioural Issues"]

    if any(c in concern_lower for c in ["anxiety", "stress", "work burnout", "depression", "trauma"]):
        return "Clinical Psychologist", [concern.title()]

    # Default fallback
    return "Clinical Psychologist", [concern.title()]

def find_experts(
    concern: str,
    severity: str = "moderate",
    preferences: Dict = None
) -> List[Dict]:
    """
    Finds and ranks suitable experts based on user's concern and preferences.
    
    :param concern: The primary issue the user is facing (e.g., "Anxiety", "Relationship problems").
    :param severity: The severity of the issue ("mild", "moderate", "severe", "critical").
    :param preferences: A dict with user preferences like 'city', 'language', 'consultation_type'.
    """
    if preferences is None:
        preferences = {}

    role, specializations = map_concern_to_role_and_specialization(concern, severity)
    
    if not role:
        return []

    # Start with all experts
    filtered_experts = EXPERTS

    # 1. Filter by Role
    filtered_experts = [e for e in filtered_experts if e["role"] == role]

    # 2. Filter by Specialization (must have at least one matching specialization)
    spec_set = set(s.lower() for s in specializations)
    filtered_experts = [
        e for e in filtered_experts 
        if any(s.lower() in spec_set for s in e["specializations"])
    ]

    # 3. Filter by Language (if specified)
    if preferences.get("language"):
        lang = preferences["language"].lower()
        filtered_experts = [
            e for e in filtered_experts 
            if lang in [l.lower() for l in e["languages"]]
        ]

    # 4. Filter by City (if specified and not 'Online' preference)
    if preferences.get("city") and preferences.get("consultation_type") != "Online":
        city = preferences["city"].lower()
        # Include experts in the city OR those who offer online sessions as a fallback
        filtered_experts = [
            e for e in filtered_experts 
            if e["city"].lower() == city or "Online" in e["consultation_types"]
        ]

    # 5. Filter by Consultation Type (if specified)
    if preferences.get("consultation_type"):
        ctype = preferences["consultation_type"]
        filtered_experts = [
            e for e in filtered_experts 
            if ctype in e["consultation_types"]
        ]

    # Simple ranking: more experience is better
    filtered_experts.sort(key=lambda e: int(e["experience"].split('+')[0]), reverse=True)

    return filtered_experts[:3] # Return top 3 matches

def generate_recommendation_text(expert: Dict, concern: str, preferences: Dict) -> str:
    """
    Generates a personalized recommendation string for a given expert.
    """
    reason = f"specializes in areas like {expert['specializations'][0]} and {expert['specializations'][1]}"
    if "Cognitive Behaviour Therapy (CBT)" in expert['specializations']:
        reason += ", and is experienced in approaches like CBT"

    location_pref = f" in {preferences['city']}" if preferences.get('city') else ""
    language_pref = f" who speaks {preferences['language']}" if preferences.get('language') else ""

    return (f"Based on what you've shared about {concern}, I recommend {expert['name']}. "
            f"As a {expert['role']}{location_pref}{language_pref}, they could be a great fit because they {reason}. "
            f"Would you like to know more or see how to book a session?")