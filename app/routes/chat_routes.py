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
    token: str = Depends(security)
):
    t_start = time.time()
    
    # --- User Resolution (Token or Visitor ID) ---
    current_user = None
    if token and token.credentials:
        try:
            payload = jwt.decode(token.credentials, JWT_SECRET, algorithms=[ALGORITHM])
            user_id = payload.get("user_id")
            current_user = db.query(User).filter(User.id == user_id).first() if user_id else None
        except Exception:
            db.rollback()  # Clear any poisoned transaction
            pass  # Fallback to visitor_id
    if not current_user and data.visitor_id:
        current_user = db.query(User).filter(User.visitor_id == data.visitor_id).first()
        if not current_user:
            current_user = User(visitor_id=data.visitor_id)
            db.add(current_user)
            db.commit()
            db.refresh(current_user)

    if not current_user:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="User identification required (Token or Visitor ID)")

    
    current_user = db.merge(current_user, load=False)
    session_state = get_session_state(current_user.id)
    user_name_val = current_user.name or session_state.get("user_name")
    session_state["user_id"] = current_user.id
    
    voice_enabled = data.voice_enabled if data.voice_enabled is not None else session_state.get("voice_enabled", False)
    session_state["voice_enabled"] = voice_enabled
    
    user_message = data.message.strip()

     # 2. Context Gathering for AI
    t_context = time.time()
    is_substantive = len(user_message) > 10
    memory_results = await search_memory(user_message) if is_substantive else None
    
    
    history = get_chat_history(db, current_user.id, limit=3)
    insights = get_mood_insights(db, current_user.id)
    wellness_count = get_wellness_summary(db, current_user.id)
    exercise_eff = get_exercise_effectiveness(db, current_user.id)
    
    retrieved_memories = memory_results.get("documents", [[]])[0] if memory_results else []
    print(f"DEBUG: Context took {time.time() - t_context:.4f}s")

     # 3. Unified Zura Response (Single AI Call)
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
        personalized_context=personalized_context,
        personality=personality_mode(session_state.get("last_emotion", "neutral"))
    )
    print(f"DEBUG: AI Unified took {time.time() - t_ai:.4f}s")

    if not unified_output:
         return await construct_chat_response(
            "I'm here for you. Let's take a slow breath together.", "neutral", "chat", "low", "BREATHE",
            {"type": "NONE"}, get_therapeutic_recommendation("neutral"), voice_enabled, current_user.id
        )

    analysis = unified_output.get("analysis", {})
    current_emotion = analysis.get("emotion", "neutral")

    # 4. Prepare for Flow Logic & Post-AI DB Updates
    voice_task = None
    ai_reply = unified_output.get("reply") or "I'm here for you. How are you feeling?"
    if voice_enabled and ai_reply:
        voice_task = asyncio.create_task(text_to_speech(ai_reply, voice="nova"))


    track_triggers(db, current_user.id, analysis.get("triggers", []))
    if analysis.get("name") and not user_name_val:
        update_user_name(db, current_user.id, analysis.get("name"))

    track_mood(db, current_user.id, current_emotion, analysis.get("severity_score", 0.2), context=user_message)
    
    feedback = analysis.get("exercise_feedback")
    last_ex = session_state.get("last_exercise")
    if feedback and feedback != "none" and last_ex:
        from app.services.mood_service import track_wellness_progress
        track_wellness_progress(db, current_user.id, last_ex, last_ex.replace("_", " ").capitalize(), feedback=user_message)
        session_state["last_exercise"] = None

    # 5. Authoritative Flow Orchestration (Single Call after AI Analysis)
    t_flow = time.time()
    intent_data = {
        "intent": analysis.get("intent", "General chat"),
        "risk_level": analysis.get("risk_level", "low"),
        "user_preferences": analysis.get("user_preferences")
    }
    emotion_data = {"emotion": current_emotion, "severity": analysis.get("severity_score", 0.2)}

    # Handle pending intent from crisis (if any)
    pending_intent_from_session = session_state.get("crisis_state", {}).get("pending_normal_intent_data")
    if pending_intent_from_session:
        intent_data["intent"] = pending_intent_from_session.get("intent")
        intent_data["user_preferences"] = pending_intent_from_session.get("user_preferences", {})
        print(f"DEBUG: Overriding AI intent with pending crisis intent: {intent_data['intent']}")
        session_state["crisis_state"].pop("pending_normal_intent_data", None) # Clear after use

    flow_reply, session_state, flow_active, _ = handle_flow_logic(
        user_message, session_state, intent_data, emotion_data, db=db, user_name=user_name_val
    )
    print(f"DEBUG: Post-AI Flow Logic took {time.time() - t_flow:.4f}s")

    final_reply = ai_reply
    action = unified_output.get("action") or {"type": "NONE"}
    recommended_feature = unified_output.get("recommended_feature") or "NONE"

    if flow_active:
        final_reply = flow_reply
        active_flow_name = session_state.get("active_flow", "FLOW")
        action = {"type": "CONTINUE_FLOW", "flow": active_flow_name}
        recommended_feature = active_flow_name.upper() if active_flow_name else "FLOW"
        # If flow is active, its reply takes precedence, and we might need to generate voice for it.
        if voice_enabled and final_reply:
            if voice_task: voice_task.cancel() # Cancel original AI voice task
            voice_task = asyncio.create_task(text_to_speech(final_reply, voice="nova"))
    else:
        suggested_flow = unified_output.get("suggested_flow")
        if suggested_flow and suggested_flow not in ["null", "flow_id_or_null"]:
            session_state.update({
                "active_flow": None, # Ensure no active flow, it's just pending
                "pending_flow": suggested_flow,
                "awaiting_confirmation": True,
                "current_step": 0,
                "current_need": current_emotion # Store context for potential expert booking
            })

    # 6. Final State Save & Response
    suggested_flow = unified_output.get("suggested_flow")
    session_state["last_emotion"] = current_emotion
    save_chat_history(db, current_user.id, user_message, final_reply, current_emotion)
    save_session_state(current_user.id, session_state)
    
    
    background_tasks.add_task(save_memory, current_user.id, user_message, current_emotion, intent_data["intent"])

    
    audio_base64 = None # Initialize audio_base64
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
        "risk_level": analysis.get("risk_level", "low"),
        "recommended_feature": recommended_feature,
        "action": action,
        "therapy": get_therapeutic_recommendation(current_emotion),
        "audio_base64": audio_base64
    }
