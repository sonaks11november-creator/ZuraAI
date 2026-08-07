from fastapi import WebSocket
import json
import re
from app.services.emotion_service import detect_emotion
from app.services.crisis_service import detect_crisis
from app.services.intent_service import detect_intent
from app.services.therapy_service import get_therapeutic_recommendation
from app.services.action_router import route_action
from app.services.openai_service import generate_ai_response
from app.services.memory_service import save_memory
from app.services.chat_history_service import save_chat_history, get_chat_history
from app.services.flow_service import get_session_state, save_session_state, handle_flow_logic
from app.database import SessionLocal

import asyncio

from app.services.mood_service import (
    track_mood, 
    get_mood_insights, 
    analyze_and_track_triggers, 
    get_wellness_summary, 
    track_wellness_progress, 
    extract_and_update_user_name,
    track_triggers,
    update_user_name
)
from app.services.personalization_service import get_personalized_prompt_extension, personality_mode
from app.models.user_model import User
from app.models.assessment_model import AssessmentResult
from app.services import assessment_service

async def websocket_chat(websocket: WebSocket, user_id: int):
    await websocket.accept()
    db = SessionLocal()
    
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            user_message = message_data.get("message", "").strip()

            # 0. Load Session State & Long-term Insights
            session_state = get_session_state(user_id)
            insights = get_mood_insights(db, user_id)
            wellness_count = get_wellness_summary(db, user_id)
            user = db.query(User).filter(User.id == user_id).first()
            user_name = user.name if user else None

            intent_data = {} # Initialize to prevent NameError on first pass
            # 2. Flow Orchestration (Priority 1)
            flow_reply, session_state, flow_active = handle_flow_logic(user_message, session_state, intent_data, db=db, user_name=user_name)
            
            if flow_active:
                # Track exercise completion if a flow just finished
                if flow_reply is None: # Flow finished in handle_flow_logic returns None, state, False
                    pass # This is handled below when flow_active is False
                
                # Save assessment result if finished
                if session_state.get("last_assessment_result"):
                    res = session_state.pop("last_assessment_result")
                    db_res = AssessmentResult(
                        user_id=user_id,
                        assessment_type=res["assessment_type"],
                        score=res["score"],
                        result_category=res["result_category"]
                    )
                    db.add(db_res)
                    db.commit()

                save_session_state(user_id, session_state)
                save_chat_history(db, user_id, user_message, flow_reply, session_state.get("last_emotion", "neutral"))
                
                active_flow = session_state.get("active_flow")
                await websocket.send_json({
                    "reply": flow_reply,
                    "emotion": session_state.get("last_emotion", "neutral"),
                    "intent": "continuation",
                    "risk_level": "low",
                    "recommended_feature": active_flow.upper() if active_flow else "BREATHE",
                    "action": {
                        "type": "CONTINUE_FLOW", 
                        "feature": active_flow.upper() if active_flow else "BREATHE",
                        "flow": active_flow, 
                        "step": session_state["current_step"]
                    },
                    "therapy": {"exercise": flow_reply, "type": "Flow"}
                })
                continue

            # Check if a flow JUST finished (flow_active was true last time, now it's false)
            if not flow_active and session_state.get("last_exercise") and not session_state.get("active_flow"):
                 # Record wellness progress when a flow finishes
                 track_wellness_progress(db, user_id, session_state["last_exercise"], session_state["last_exercise"], feedback="completed")

            # 3. Contextual Data
            from app.services.memory_search_service import search_memory
            memory_results = search_memory(user_message)
            retrieved_memories = memory_results.get("documents", [[]])[0] if memory_results else []
            history = get_chat_history(db, user_id, limit=5)
            
            personalized_context = get_personalized_prompt_extension(
                user_name=user_name, 
                insights=insights,
                wellness_count=wellness_count,
                user_profile={
                    "tier": user.tier if user else None,
                    "onboarding_layer": user.onboarding_layer if user else None,
                    "support_preference": user.support_preference if user else None
                }
            )

            # 1. Comprehensive AI Response Generation (Single Call)
            ai_output = await generate_ai_response(
                message=user_message,
                memories=retrieved_memories,
                history=history,
                last_exercise=session_state.get("last_exercise"),
                completed_exercises=session_state.get("completed_exercises", []),
                refused_exercises=session_state.get("refused_exercises", []),
                personality=personality_mode(session_state.get("last_emotion", "neutral")),
                personalized_context=personalized_context
            )

            analysis = ai_output.get("analysis", {})
            emotion_data = {
                "emotion": analysis.get("emotion", "neutral"),
                "severity": analysis.get("severity_score", 0.2),
                "severity_level": analysis.get("severity_level", "Mild")
            }
            crisis_data = {
                "risk_level": analysis.get("risk_level", "low"),
                "critical": analysis.get("risk_level") == "critical"
            }
            intent_data = {
                "intent": analysis.get("intent", "General chat")
            }

            # Background tasks for DB updates
            asyncio.create_task(asyncio.to_thread(track_triggers, db, user_id, analysis.get("triggers", [])))
            if analysis.get("name") and not user_name:
                asyncio.create_task(asyncio.to_thread(update_user_name, db, user_id, analysis.get("name")))
                db.refresh(user)
                user_name = user.name

            # Re-run flow logic now that we have AI analysis to detect pivots, greetings, or crisis
            flow_reply, session_state, flow_active = handle_flow_logic(user_message, session_state, intent_data, emotion_data=emotion_data, db=db, user_name=user_name)

            if flow_active:
                # This block will now be entered if a crisis is detected and the flow is activated.
                final_reply = flow_reply
                active_flow = session_state.get("active_flow")
                action_data = {"type": "CONTINUE_FLOW", "feature": active_flow.upper() if active_flow else "BREATHE"}
                recommended_feature = active_flow.upper() if active_flow else "BREATHE"
            else:
                # DEFAULT: AI Chat + Wellness Flow Detection
                current_severity = emotion_data["severity"]
                current_emotion = emotion_data["emotion"]
                # This ensures Stress/Sadness/Sleep issues go through AI validation/support first.

                final_reply = ai_output.get("reply", "I'm here for you.")
                
                # Check if the AI or rules recommended a specific flow
                intent_ai = ai_output.get("intent", "").lower()
                reply_ai = final_reply.lower()
                suggested_flow = ai_output.get("suggested_flow")
                
                flow_name = None
                # Priority 1: Explicitly suggested flow from AI JSON
                if suggested_flow and suggested_flow != "flow_id_or_null" and suggested_flow in ["breathing", "compact_breathing", "box_breathing", "478_breathing", "grounding", "tension_release", "thought_reframing", "body_scan", "self_esteem", "reflection_flow"]:
                    flow_name = suggested_flow
                
                # Priority 2: Keyword matching (Fallback/Safety)
                if not flow_name:
                    if re.search(r"box\s*breath", reply_ai):
                        flow_name = "box_breathing"
                    elif re.search(r"4-7-8", reply_ai):
                        flow_name = "478_breathing"
                    elif re.search(r"reframe|thought\s*refram", reply_ai):
                        flow_name = "thought_reframing"
                    elif re.search(r"body\s*scan", reply_ai):
                        flow_name = "body_scan"
                    elif re.search(r"tension\s*release|muscle\s*relax", reply_ai):
                        flow_name = "tension_release"
                    elif re.search(r"self-esteem|proud\s*of", reply_ai):
                        flow_name = "self_esteem"
                    elif "grounding" in intent_ai or re.search(r"grounding|5-4-3-2-1", reply_ai + user_message.lower()):
                        flow_name = "grounding"
                    elif "breathe" in intent_ai or "breathing" in intent_ai or re.search(r"breath", reply_ai):
                        flow_name = "breathing" if current_emotion == "panic" else "compact_breathing"

                if flow_name:
                    # All flows should start at step 0 to ensure the first instruction is delivered properly after confirmation.
                    current_step = 0

                    session_state.update({
                        "active_flow": None,
                        "pending_flow": flow_name,
                        "awaiting_confirmation": True,
                        "current_step": current_step,
                        "last_emotion": current_emotion,
                        "last_severity": current_severity
                    })
                else:
                    # Ensure no accidental confirmation state if no flow detected
                    session_state["awaiting_confirmation"] = False
                
                save_session_state(user_id, session_state)

                action_routing = route_action(
                    ai_output.get("intent", intent_data["intent"]), 
                    ai_output.get("emotion", emotion_data["emotion"]), 
                    ai_output.get("risk_level", crisis_data["risk_level"])
                )
                action_data = action_routing["action"]
                recommended_feature = action_routing["recommended_feature"]

                if action_data["type"] == "START_ASSESSMENT":
                    assessment_type = action_data["assessment_type"]
                    first_question = assessment_service.get_assessment_question(assessment_type, 0)
                    final_reply = f"{final_reply}\n\n{first_question}"
                    session_state.update({
                        "active_assessment": assessment_type,
                        "assessment_step": 0,
                        "assessment_score": 0
                    })
                    save_session_state(user_id, session_state)

            # 6. Post-Response Tasks
            save_session_state(user_id, session_state)
            track_mood(db, user_id, emotion_data["emotion"], emotion_data["severity"], context=user_message)
            save_chat_history(db, user_id, user_message, final_reply, emotion_data["emotion"])
            asyncio.create_task(asyncio.to_thread(save_memory, user_id, user_message, emotion_data["emotion"], intent_data["intent"]))

            # 7. Send structured response back
            await websocket.send_json({
                "reply": final_reply,
                "emotion": emotion_data["emotion"],
                "intent": intent_data["intent"],
                "risk_level": crisis_data["risk_level"],
                "recommended_feature": recommended_feature,
                "action": action_data,
                "therapy": get_therapeutic_recommendation(emotion_data["emotion"])
            })


    except Exception as e:
        print(f"WebSocket Error: {e}")
    finally:
        db.close()
        await websocket.close()