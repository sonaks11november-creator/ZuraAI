
import json
import re
from app.services.redis_service import redis_client, SimpleCache
from app.services.therapy_service import get_next_flow_step
from app.services import assessment_service

def get_session_state(user_id: int):
    session_key = f"zura_session:{user_id}"
    try:
        state_data = redis_client.get(session_key)
        if state_data:
            return state_data if isinstance(state_data, dict) else json.loads(state_data)
    except Exception as e:
        print(f"Redis Error (get): {e}")
    return {}

def save_session_state(user_id: int, state: dict):
    session_key = f"zura_session:{user_id}"
    try:
        if isinstance(redis_client, SimpleCache):
            redis_client.set(session_key, state)
        else:
            redis_client.set(session_key, json.dumps(state), ex=3600)
    except Exception as e:
        print(f"Redis Error (save): {e}")

# Flows that require the user to provide specific answers/content
INTERACTIVE_FLOWS = ["grounding", "thought_reframing", "self_esteem"]

def handle_flow_logic(user_message: str, session_state: dict, intent_data: dict = None, emotion_data: dict = None, db=None):
    """
    Returns (reply, updated_state, flow_active)
    If flow_active is True, the reply should be sent and further AI processing skipped.
    """
    user_msg_lower = user_message.lower().strip()
    intent_data = intent_data or {}
    emotion_data = emotion_data or {}
    emotion = emotion_data.get("emotion", "neutral")

    # --- PRIORITY 0: CRISIS MODE INTERVENTION ---
    # If crisis mode is active, ALL logic is overridden to keep the user in the crisis flow.
    if session_state.get("crisis_mode"):
        # "stop" or "cancel" should NOT exit crisis mode. We must keep them engaged.
        # We can interpret it as them wanting to stop the *current question*, not the support.
        is_stop_word = any(word in user_msg_lower for word in ["stop", "cancel", "exit", "quit", "no more", "nevermind", "end this", "don't want to", "no need", "leave me"])

        current_step = session_state.get("current_step", 0)
        # If user says "yes" to acting on thoughts (after step 0), we go to step 1 (emergency).
        # If "no", we go to step 2 (de-escalation).
        if current_step == 1: # We just asked if they will act on thoughts
            if any(w in user_msg_lower for w in ["yes", "i am", "i will", "yeah"]):
                session_state["current_step"] = 1 # Explicitly go to emergency step
            else:
                session_state["current_step"] = 2 # Go to de-escalation step

        next_text = get_next_flow_step("crisis_support", session_state["current_step"])
        session_state["current_step"] += 1
        session_state["active_flow"] = "crisis_support" # Ensure it stays active
        return next_text, session_state, True

    # 0. Identify Continuations and Stops early
    continuations = [
        "ok", "okay", "yes", "yeah", "sure", "done", "next", "continue", "go on",
        "yes please", "we can try", "i would like that", "let's do it", "let's try", 
        "yep", "yup", "give", "i did it", "did it", "done it", "i do it", "completed", "ready",
        "anything", "whatever", "help me", "calm down", "want to calm down", "i want to calm down",
        "go ahead", "let's start", "start", "do it", "try it", "let's try it"
    ]
    is_continuation = any(c == user_msg_lower or user_msg_lower.startswith(c + " ") for c in continuations) or \
                      any(word in user_msg_lower for word in ["done", "finished", "completed"])
    
    # Negative Feedback Detection (No improvement after exercise)
    negative_feedback = ["no change", "no changes", "still stressed", "not working", "didn't help", "no better", "still feel", "no difference"]
    has_negative_feedback = any(f in user_msg_lower for f in negative_feedback)
    is_stop = any(word in user_msg_lower for word in ["stop", "cancel", "exit", "quit", "no more", "nevermind", "end this", "don't want to"])

    # 1. Basic Intent/Stop/Pivot Detection
    greetings = ["hi", "hello", "hey", "hii", "howdy", "sup", "greetings", "good morning", "good evening", "good afternoon"]
    
    # Check for greeting (either AI detected or keyword matched)
    has_greeting_word = any(word == user_msg_lower or user_msg_lower.startswith(word + " ") for word in greetings)
    is_greeting = (intent_data.get("intent") == "General chat" and has_greeting_word) or (has_greeting_word and len(user_msg_lower) < 10)
    
    # Emotional Pivot Detection: Only pivot if NOT a simple continuation
    is_explicit_emotion = any(phrase in user_msg_lower for phrase in ["i feel", "i'm feeling", "i am feeling", "feeling really", "feeling so"])
    is_emotional_pivot = (not is_continuation) and (emotion != "neutral" or is_explicit_emotion)

    # 1a. State Reset (Greeting or Pivot)
    if is_greeting or is_emotional_pivot:
        # Reset everything to allow AI to take over
        session_state["awaiting_confirmation"] = False
        session_state["pending_flow"] = None
        session_state["active_flow"] = None
        session_state["active_assessment"] = None
        session_state["awaiting_escalation"] = False
        session_state["current_step"] = 0
        session_state["last_exercise"] = None
        return None, session_state, False

    # 2. Stop/Cancel Check
    if is_stop:
        active_flow = session_state.get("active_flow")
        if active_flow:
            refused = session_state.get("refused_exercises", [])
            if active_flow not in refused:
                refused.append(active_flow)
            session_state["refused_exercises"] = refused
            
        session_state["active_flow"] = None
        session_state["active_assessment"] = None
        session_state["pending_flow"] = None
        session_state["awaiting_confirmation"] = False
        session_state["awaiting_escalation"] = False
        session_state["current_step"] = 0
        return "Of course. We can stop here. What would you like to do instead?", session_state, True

    # 3. Assessment Logic
    active_assessment = session_state.get("active_assessment")
    if active_assessment:
        current_step = session_state.get("assessment_step", 0)
        total_score = session_state.get("assessment_score", 0)
        assessment_answers = session_state.get("assessment_answers", [])
        
        # Try to parse numeric (0-3) or letter (A-D) answer
        match = re.search(r"\b([0-3a-dA-D])\b", user_msg_lower)
        if match:
            raw_answer = match.group(1).upper()
            
            # Handle emergency override for onboarding Q3
            if active_assessment == "onboarding" and current_step == 2 and raw_answer == 'D':
                session_state["active_assessment"] = None
                session_state["assessment_step"] = 0
                return (
                    "I hear you, and I want you to know you're not alone. I'm here to help you get the support you need right now.\n\n"
                    "Please reach out to a crisis resource immediately:\n"
                    "• **National Crisis Line**: Call or text 988\n"
                    "• **Emergency Services**: Call 911\n\n"
                    "Would you like me to help you connect with a live support person who can talk with you right now?",
                    session_state, True
                )

            # Convert letter to score if needed for standard assessments (A=0, B=1, etc.)
            # Or just store the raw answer for onboarding
            if raw_answer.isdigit():
                score = int(raw_answer)
            else:
                score = ord(raw_answer) - ord('A')
            
            total_score += score
            assessment_answers.append(raw_answer)
            current_step += 1
            
            next_question = assessment_service.get_assessment_question(active_assessment, current_step)
            if next_question:
                session_state["assessment_step"] = current_step
                session_state["assessment_score"] = total_score
                session_state["assessment_answers"] = assessment_answers
                
                # Special empathy touches for onboarding
                if active_assessment == "onboarding":
                    if current_step == 4: # After Q4, before Q5
                        next_question = "Thanks for being honest. Almost done.\n\n" + next_question
                
                return next_question, session_state, True
            else:
                # Assessment finished
                user_id = session_state.get("user_id", 1) # Default for safety, should be set in session

                if active_assessment == "onboarding":
                    route = assessment_service.calculate_onboarding_route(assessment_answers)
                    result_category = route["tier"]
                    
                    if db:
                        try:
                            from app.models.user_model import User
                            user = db.query(User).filter(User.id == user_id).first()
                            if user:
                                user.onboarding_completed = True
                                user.tier = route["tier"]
                                user.onboarding_layer = route["layer"]
                                user.support_preference = route.get("privacy_preference")
                                if route["tier"] == "Premium":
                                    user.premium_status = True
                            
                            from app.models.assessment_model import UserIntakeAssessment
                            intake_record = UserIntakeAssessment(
                                user_id=user_id,
                                q1=assessment_answers[0] if len(assessment_answers) > 0 else None,
                                q2=assessment_answers[1] if len(assessment_answers) > 1 else None,
                                q3=assessment_answers[2] if len(assessment_answers) > 2 else None,
                                q4=assessment_answers[3] if len(assessment_answers) > 3 else None,
                                q5=assessment_answers[4] if len(assessment_answers) > 4 else None,
                                q6=assessment_answers[5] if len(assessment_answers) > 5 else None,
                                q7=assessment_answers[6] if len(assessment_answers) > 6 else None,
                                route_tier=route["tier"],
                                route_layer=route["layer"],
                                interest_tags=route.get("interest_tags"),
                                privacy_preference=route.get("privacy_preference")
                            )
                            db.add(intake_record)
                            db.commit()
                        except Exception as e:
                            print(f"Error saving onboarding result: {e}")
                            db.rollback()

                    # Mapping tiers to friendly results
                    tier_responses = {
                        "Psychiatric": "Based on what you've shared, I recommend starting with our clinical team for a clinical assessment and possible medication support.",
                        "Psychological": "It sounds like psychological support through therapy and counseling would be a great next step for you.",
                        "Premium": "Welcome to The Prime Project. We'll provide you with private, concierge-level care.",
                        "Non-clinical": "I've tailored a plan focused on mindfulness, sleep, mood, courses, and habits to help you feel your best."
                    }
                    reply = (
                        f"Thank you for completing the check-in. {tier_responses.get(result_category, '')}\n\n"
                        f"I've set your primary focus to **{route.get('layer', 'Mibo Main')}**.\n\n"
                        "How would you like to begin? I can show you how to book a session, or we can start with a calming activity."
                    )
                else:
                    result_category = assessment_service.get_assessment_result(active_assessment, total_score)
                    
                    if db:
                        try:
                            from app.models.assessment_model import AssessmentResult
                            res = AssessmentResult(
                                user_id=user_id,
                                assessment_type=active_assessment,
                                score=total_score,
                                result_category=result_category
                            )
                            db.add(res)
                            db.commit()
                        except Exception as e:
                            print(f"Error saving assessment result: {e}")
                            db.rollback()

                    # Opinionated next steps based on result
                    next_flow = None
                    if active_assessment == "stress":
                        if result_category == "Moderate Stress":
                            next_flow = "compact_breathing"
                        elif result_category == "High Stress":
                            next_flow = "box_breathing"
                        else:
                            next_flow = "breathing"
                    elif active_assessment == "anxiety":
                        if result_category in ["Moderate Anxiety", "Severe Anxiety"]:
                            next_flow = "grounding"
                        else:
                            next_flow = "478_breathing"

                    if next_flow:
                        session_state["pending_flow"] = next_flow
                        session_state["awaiting_confirmation"] = True
                        
                        flow_label = next_flow.replace("_", " ").capitalize()
                        reply = (
                            f"**{active_assessment.capitalize()} Check Result: {result_category}**\n\n"
                            f"It sounds like {active_assessment} has been weighing on you lately. Knowing this helps me support you better.\n\n"
                            f"Let's take a moment together to settle your mind. I'd like to guide you through a quick {flow_label}. Ready to try?"
                        )
                    else:
                        reply = (
                            f"**{active_assessment.capitalize()} Check Result: {result_category}**\n\n"
                            f"It sounds like {active_assessment} has been affecting you more than usual recently. Knowing this helps me support you better.\n\n"
                            "I can guide you through some techniques that may help right now, such as a short breathing exercise or a grounding activity. What would you like to try?"
                        )
                
                # Store result for database persistence
                session_state["last_assessment_result"] = {
                    "assessment_type": active_assessment,
                    "score": total_score,
                    "result_category": result_category,
                    "answers": assessment_answers
                }

                # Reset assessment state
                session_state["active_assessment"] = None
                session_state["assessment_step"] = 0
                session_state["assessment_score"] = 0
                session_state["assessment_answers"] = []
                
                return reply, session_state, True
        else:
            valid_range = "A to D" if active_assessment == "onboarding" else "0 to 3"
            return f"Please provide an answer from {valid_range} so I can calculate your result accurately.", session_state, True

    # 4. Media Session Follow-up
    if user_msg_lower == "media_finished":
        session_state["media_session_active"] = False
        return "Welcome back. How are you feeling now?", session_state, True

    # Step A: Transition from "Awaiting Confirmation" -> "Active Flow"
    just_activated = False
    if not session_state.get("active_flow") and is_continuation and session_state.get("awaiting_confirmation"):
        active_flow = session_state.get("pending_flow")
        current_step = session_state.get("current_step", 0)
        session_state["awaiting_confirmation"] = False
        session_state["pending_flow"] = None
        session_state["active_flow"] = active_flow
        session_state["current_step"] = current_step
        session_state["media_session_active"] = False
        just_activated = True

    # Step B: Flow Execution
    active_flow = session_state.get("active_flow")
    current_step = session_state.get("current_step", 0)

    if active_flow:
        # Rule: If it's an interactive flow, ANY non-greeting/stop input progresses it.
        # EXCEPTION: For interactive flows, a simple "ok" or "yes" should NOT advance the step
        # unless it was the activation message (just_activated).
        is_interactive = active_flow in INTERACTIVE_FLOWS
        
        is_simple_confirmation = user_msg_lower in ["ok", "okay", "yes", "yeah", "sure", "yep", "yup", "ready"]
        
        if is_interactive and is_simple_confirmation and not just_activated:
            # Re-send the current step instructions instead of advancing
            return get_next_flow_step(active_flow, current_step - 1 if current_step > 0 else 0), session_state, True

        # Special Case: User reports no improvement during or after a flow
        if has_negative_feedback:
            # Find a DIFFERENT exercise to suggest
            available_exercises = ["grounding", "tension_release", "body_scan", "478_breathing", "box_breathing"]
            next_flow = "grounding" # Default fallback
            
            last_ex = session_state.get("last_exercise") or active_flow
            for ex in available_exercises:
                if ex != last_ex and ex not in session_state.get("refused_exercises", []):
                    next_flow = ex
                    break
            
            session_state["active_flow"] = None
            session_state["pending_flow"] = next_flow
            session_state["awaiting_confirmation"] = True
            session_state["current_step"] = 0
            
            flow_labels = {
                "grounding": "grounding exercise (5-4-3-2-1)",
                "tension_release": "muscle tension release",
                "body_scan": "gentle body scan",
                "478_breathing": "4-7-8 breathing technique",
                "box_breathing": "box breathing reset"
            }
            label = flow_labels.get(next_flow, "calming technique")
            
            return (
                "Thank you for being honest with me. It's completely okay that the last exercise didn't quite hit the mark—everyone's mind responds differently.\n\n"
                f"Let's try a different approach. How about we try a {label} together? It might help shift things in a way the breathing didn't. Ready to try?"
            ), session_state, True

        if not is_continuation and not is_interactive:
            # User is likely trying to pivot or chat
            session_state["active_flow"] = None
            session_state["current_step"] = 0
            return None, session_state, False

        next_text = get_next_flow_step(active_flow, current_step)
        if next_text:
            session_state["current_step"] = current_step + 1
            session_state["last_exercise"] = active_flow
            return next_text, session_state, True
        else:
            # Flow finished
            completed = session_state.get("completed_exercises", [])
            if active_flow not in completed:
                completed.append(active_flow)
            session_state["completed_exercises"] = completed
            
            session_state["active_flow"] = None
            session_state["current_step"] = 0
            session_state["media_session_active"] = False 
            return None, session_state, False

    return None, session_state, False
