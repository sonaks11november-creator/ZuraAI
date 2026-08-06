from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import SessionLocal

from app.utils.get_current_user import (
    get_current_user,
    security,
    ALGORITHM,
    JWT_SECRET
)
from jose import jwt

from app.services.therapy_service import (
    get_therapeutic_recommendation
)

from app.services.action_router import (
    route_action
)

from app.services.personalization_service import (
    personality_mode,
    get_personalized_prompt_extension
)

from app.services.mood_service import (
    track_mood,
    get_mood_insights,
    get_wellness_summary,
    get_exercise_effectiveness,
    track_triggers,
    update_user_name
)

from app.services.memory_service import (
    save_memory
)

from app.services.memory_search_service import (
    search_memory
)

from app.services.chat_history_service import (
    get_chat_history,
    save_chat_history
)

from app.services.openai_service import (
    generate_unified_zura_response,
    extract_name_from_memories
)

router = APIRouter(
    prefix="/chat"
)

def get_db():

    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()

from app.services.flow_service import (
    get_session_state,
    save_session_state,
    handle_flow_logic
)

from app.schemas.chat_schema import ChatSchema, ChatResponseSchema

import asyncio
import os
import time
import base64
from app.models.user_model import User
from app.services import assessment_service

from app.services.voice_service import (
    text_to_speech
)

async def construct_chat_response(
    reply: str, emotion: str, intent: str, risk_level: str, 
    recommended_feature: str, action: dict, therapy: dict, 
    voice_enabled: bool, user_id: int, pre_generated_audio: str = None
) -> dict:
    audio_base64 = pre_generated_audio
    if voice_enabled and reply and not audio_base64:
        try:
            # Only generate if not pre-provided
            audio_base64 = await text_to_speech(reply, voice="nova")
        except Exception as e:
            print(f"Voice Generation Error: {e}")
            
    return {
        "reply": reply,
        "emotion": emotion,
        "intent": intent,
        "risk_level": risk_level,
        "recommended_feature": recommended_feature,
        "action": action,
        "therapy": therapy,
        "audio_base64": audio_base64
    }

@router.post("/", response_model=ChatResponseSchema)
async def chat(
    data: ChatSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    token = Depends(security)
):
    t_start = time.time()
    
    # --- User Resolution (Token or Visitor ID) ---
    current_user = None
    if token and token.credentials:
        try:
            payload = jwt.decode(token.credentials, JWT_SECRET, algorithms=[ALGORITHM])
            user_id = payload.get("user_id")
            if user_id:
                current_user = db.query(User).filter(User.id == user_id).first()
        except Exception:
            db.rollback() # Clear the poisoned transaction
            pass # Fallback to visitor_id

    if not current_user and data.visitor_id:
        current_user = db.query(User).filter(User.visitor_id == data.visitor_id).first()
        if not current_user:
            # Create new guest user
            current_user = User(visitor_id=data.visitor_id)
            db.add(current_user)
            db.commit()
            db.refresh(current_user)

    if not current_user:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="User identification required (Token or Visitor ID)")

    # --- Ensure current_user is persistent ---
    current_user = db.merge(current_user, load=False)
    session_state = get_session_state(current_user.id)
    user_name_val = current_user.name or session_state.get("user_name")
    session_state["user_id"] = current_user.id
    
    voice_enabled = data.voice_enabled if data.voice_enabled is not None else session_state.get("voice_enabled", False)
    session_state["voice_enabled"] = voice_enabled
    
    user_message = data.message.strip()

    # 1. Flow Interception (PRIORITY - BEFORE AI)
    # Check if we should handle this purely as a flow step to save tokens and prevent AI greeting loops
    flow_reply = None
    flow_active = False
    
    # Identify low-complexity keywords or assessment answers
    is_numeric = user_message.isdigit() and len(user_message) == 1
    is_onboarding_choice = len(user_message) == 1 and user_message.upper() in ["A", "B", "C", "D"]
    continuations = ["yes", "no", "ok", "okay", "next", "sure", "yep", "yup", "done", "stop", "cancel"]
    is_simple_word = user_message.lower() in continuations
    
    in_flow_state = (
        session_state.get("active_flow") or 
        session_state.get("awaiting_confirmation") or 
        session_state.get("active_assessment")
    )

    if (is_simple_word or is_numeric or is_onboarding_choice) and in_flow_state:
        # Fast-track flow handling without AI analysis
        flow_reply, session_state, flow_active = handle_flow_logic(user_message, session_state, db=db, user_name=user_name_val)
        if flow_active:
            # Skip AI entirely for simple flow steps
            save_chat_history(db, current_user.id, user_message, flow_reply, session_state.get("last_emotion", "neutral"))
            save_session_state(current_user.id, session_state)
            return await construct_chat_response(
                flow_reply, session_state.get("last_emotion", "neutral"), "continuation", "low", "FLOW",
                {"type": "CONTINUE_FLOW", "flow": session_state.get("active_flow")},
                {"exercise": flow_reply, "type": "Flow"}, voice_enabled, current_user.id
            )

    # 2. Context Gathering (Safe & Sequential)
    t_context = time.time()
    # Memory search is async and safe to parallelize with local IO/CPU logic, 
    # but DB sessions are NOT thread-safe.
    is_substantive = len(user_message) > 10
    memory_results = await search_memory(user_message) if is_substantive else None
    
    # DB reads are fast enough to be sequential (<10ms)
    history = get_chat_history(db, current_user.id, limit=3)
    insights = get_mood_insights(db, current_user.id)
    wellness_count = get_wellness_summary(db, current_user.id)
    exercise_eff = get_exercise_effectiveness(db, current_user.id)
    
    retrieved_memories = memory_results.get("documents", [[]])[0] if memory_results else []
    print(f"DEBUG: Context took {time.time() - t_context:.4f}s")

    # 2. Unified Zura Response (Single AI Call)
    t_ai = time.time()
    personalized_context = get_personalized_prompt_extension(
        user_name=user_name_val, insights=insights, wellness_count=wellness_count,
        user_profile={"tier": current_user.tier, "onboarding_layer": current_user.onboarding_layer, "support_preference": current_user.support_preference},
        exercise_effectiveness=exercise_eff
    )

    unified_output = await generate_unified_zura_response(
        message=user_message,
        previous_emotion=session_state.get("last_emotion"),
        memories=retrieved_memories,
        history=history,
        last_exercise=session_state.get("last_exercise"),
        completed_exercises=session_state.get("completed_exercises", []),
        refused_exercises=session_state.get("refused_exercises", []),
        personalized_context=personalized_context
    )
    print(f"DEBUG: AI Unified took {time.time() - t_ai:.4f}s")

    if not unified_output:
        return {
            "reply": "I'm here for you. Let's take a slow breath together.", "emotion": "neutral", 
            "intent": "chat", "risk_level": "low", "recommended_feature": "BREATHE", 
            "action": {"type": "NONE"}, "therapy": get_therapeutic_recommendation("neutral"), "audio_base64": None
        }

    final_reply = unified_output.get("reply") or "I'm here for you. How are you feeling?"
    analysis = unified_output.get("analysis", {})
    current_emotion = analysis.get("emotion") or "neutral"
    severity = analysis.get("severity_score") if analysis.get("severity_score") is not None else 0.2
    
    # --- PRIORITY: State Reset on Greeting ---
    # If the AI detects a simple greeting, forcefully reset any lingering crisis/flow state
    # This is the primary fix for the "stuck in crisis mode" bug.
    is_greeting_intent = analysis.get("intent") == "General chat" and len(user_message) < 10
    if is_greeting_intent and analysis.get("crisis_mode") is False:
        session_state["crisis_mode"] = False
        session_state["active_flow"] = None
        session_state["pending_flow"] = None
        session_state["awaiting_confirmation"] = False
        session_state["current_step"] = 0
        print("DEBUG: Greeting detected, forcing crisis_mode OFF.")

    # --- PRIORITY: Activate Crisis Mode if detected by AI ---
    if analysis.get("crisis_mode") or (analysis.get("risk_level") == "critical"):
        session_state["crisis_mode"] = True
        session_state["active_flow"] = "crisis_support"
        session_state["pending_flow"] = None
        session_state["awaiting_confirmation"] = False
        session_state["current_step"] = 0

    # 2.5 Start Voice Generation IMMEDIATELY
    voice_task = None
    if voice_enabled and final_reply:
        voice_task = asyncio.create_task(text_to_speech(final_reply, voice="nova"))

    # 3. DB Updates (Synchronous but fast, to avoid session closure issues)
    # We do these here before returning to ensure session stability
    track_triggers(db, current_user.id, analysis.get("triggers", []))
    if analysis.get("name"):
        current_user.name = analysis.get("name")
        update_user_name(db, current_user.id, analysis.get("name"))
    track_mood(db, current_user.id, current_emotion, severity, context=user_message)

    # Track Exercise Feedback if provided
    feedback = analysis.get("exercise_feedback")
    last_ex = session_state.get("last_exercise")
    if feedback and feedback != "none" and last_ex:
        from app.services.mood_service import track_wellness_progress
        track_wellness_progress(db, current_user.id, last_ex, last_ex.replace("_", " ").capitalize(), feedback=user_message)
        # Clear last_exercise after feedback is recorded to prevent double-tracking
        session_state["last_exercise"] = None

    # 4. Flow Interception
    t_flow = time.time()
    intent_data = {"intent": analysis.get("intent") or "General chat"}
    emotion_data = {"emotion": current_emotion, "severity": severity}
    
    flow_reply, session_state, flow_active = handle_flow_logic(user_message, session_state, intent_data, emotion_data, db=db, user_name=user_name_val)
    
    if flow_active:
        if voice_task: voice_task.cancel()
        save_chat_history(db, current_user.id, user_message, flow_reply, current_emotion)
        save_session_state(current_user.id, session_state)
        return await construct_chat_response(
            flow_reply, current_emotion, "continuation", "low", "FLOW",
            {"type": "CONTINUE_FLOW", "flow": session_state.get("active_flow")},
            {"exercise": flow_reply, "type": "Flow"}, voice_enabled, current_user.id
        )
    print(f"DEBUG: Flow Logic took {time.time() - t_flow:.4f}s")

    # 5. Final State Save
    suggested_flow = unified_output.get("suggested_flow")
    session_state["last_emotion"] = current_emotion
    if suggested_flow and suggested_flow != "null":
        session_state.update({"active_flow": None, "pending_flow": suggested_flow, "awaiting_confirmation": True, "current_step": 0})
    
    save_chat_history(db, current_user.id, user_message, final_reply, current_emotion)
    save_session_state(current_user.id, session_state)
    
    # Background task for vector memory only (as it's non-SQLAlchemy)
    background_tasks.add_task(save_memory, current_user.id, user_message, current_emotion, intent_data["intent"])

    # Wait for voice task
    audio_base64 = None
    if voice_task:
        t_voice = time.time()
        try:
            audio_base64 = await voice_task
        except Exception as e:
            print(f"Async Voice Error: {e}")
        print(f"DEBUG: Voice Wait took {time.time() - t_voice:.4f}s")

    print(f"DEBUG: TOTAL Processing took {time.time() - t_start:.4f}s")
    return {
        "reply": final_reply,
        "emotion": current_emotion,
        "intent": intent_data["intent"],
        "risk_level": analysis.get("risk_level") or "low",
        "recommended_feature": unified_output.get("recommended_feature") or "NONE",
        "action": unified_output.get("action") or {"type": "NONE"},
        "therapy": get_therapeutic_recommendation(current_emotion),
        "audio_base64": audio_base64
    }
