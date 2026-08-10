
import json
import re
from app.services.redis_service import redis_client, SimpleCache
from app.services.therapy_service import get_next_flow_step
from app.services import assessment_service
from app.services import care_navigator_service

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
INTERACTIVE_FLOWS = ["grounding", "thought_reframing", "self_esteem", "therapist_booking", "doctor_booking"]
def _get_next_booking_question(preferences: dict):
    """Determines the next question to ask in the booking flow."""
    if not preferences.get("concern"):
        return "What would you like support with today?\n\n• Stress\n• Anxiety\n• Depression\n• Relationship concerns\n• Something else", "concern"
    
    consultation_type = preferences.get("consultation_type")
    if not consultation_type:
        return "Would you prefer:\n\n• Online consultation\n• In-person consultation", "consultation_type"
    
    if not preferences.get("language"):
        return "Do you have a preferred language for your consultation? (e.g., Malayalam, English, Hindi)", "language"
    
    if consultation_type == "In-person" and not preferences.get("city"):
        return "Which Mibo location would you prefer?\n\n• Kochi\n• Bengaluru\n• Mumbai", "city"
    
    return None, None # All info gathered

def _get_next_doctor_booking_question(preferences: dict):
    """Determines the next question to ask in the doctor booking flow."""
    if not preferences.get("concern"):
        return "To help find the right person, could you tell me a bit more about the main health concern you're facing?", "concern"
    
    if not preferences.get("language"):
        return "Do you have a preferred language for your consultation? (e.g., Malayalam, English, Hindi)", "language"

    return None, None # All info gathered

def handle_flow_logic(user_message: str, session_state: dict, intent_data: dict = None, emotion_data: dict = None, db=None, user_name: str = None):
    """
    Returns (reply, updated_state, flow_active)
    If flow_active is True, the reply should be sent and further AI processing skipped.
    """
    user_msg_lower = user_message.lower().strip()
    intent_data = intent_data or {}
    emotion_data = emotion_data or {}

    # --- PRIORITY 0: CRITICAL RISK INTERVENTION ---
    # This block is the absolute authority on critical risk state. It cannot be exited by normal conversation.

    # Activation:
    is_critical_risk_signal = intent_data.get("risk_level") == "critical"
    if is_critical_risk_signal and not session_state.get("crisis_state", {}).get("active"):
        session_state["crisis_state"] = {
            "active": True,
            "help_shown": False,
            "help_unavailable": False,
            "help_contacted": False,
        }
        session_state["active_flow"] = "crisis_support" # Prioritizes this flow

    # Main handler for the critical risk state:
    if session_state.get("crisis_state", {}).get("active"):
        crisis_state = session_state["crisis_state"]
        user_name_for_flow = user_name or session_state.get("user_name", "there")

        # --- PRIORITY 0.1: IMMEDIATE DANGER (Post-Contact Escalation) ---
        # This is the highest priority check *within* an active crisis. It triggers if a user
        # indicates they are not safe *after* we've already asked them about their safety.
        IMMEDIATE_DANGER_PHRASES = [
            "i'm not safe", "i am not safe", "no i'm not safe", "not safe",
            "i'm alone", "i am alone", "always alone",
            "this is my last message", "last message", "last messgase", # Includes user typo
            "goodbye", "good bye", "goodby",
            "i can't go on", "no point", "end it all"
        ]
        # A simple "no" is a strong danger signal after we ask "Are you safe?"
        is_immediate_danger = any(phrase in user_msg_lower for phrase in IMMEDIATE_DANGER_PHRASES) or "no" == user_msg_lower

        if crisis_state.get("help_contacted") and is_immediate_danger:
            crisis_state["immediate_danger"] = True
            session_state["crisis_state"] = crisis_state
            message = get_next_flow_step("crisis_support", 5)
            if message:
                message = message.replace("{user_name}", user_name_for_flow)
            else: # Hardcoded fallback for maximum safety
                message = (f"{user_name_for_flow}, I'm very concerned because you said you're not safe and you're alone. Please don't stay alone right now. "
                           "Move to a place where other people are present and contact emergency support immediately. "
                           "If you can, call someone you trust and ask them to stay with you. Please do not hurt yourself while you're getting help.")
            return message, session_state, True

        # Deactivation check:
        deactivation_keywords = ["i'm safe", "i am safe", "not in danger", "false alarm", "i'm okay now", "i am okay now", "feel better now"]
        if any(keyword in user_msg_lower for keyword in deactivation_keywords):
            session_state["crisis_state"] = {"active": False} # Reset state
            session_state["active_flow"] = None
            reply = "I'm so relieved to hear that you're feeling safer now. Thank you for telling me. I'm still here to support you. What would you like to do next?"
            return reply, session_state, True

        # Check for "help unavailable"
        unavailable_keywords = ["not available", "isn't available", "not working", "unavailable"]
        if any(keyword in user_msg_lower for keyword in unavailable_keywords):
            crisis_state["help_unavailable"] = True
            session_state["crisis_state"] = crisis_state
            message = get_next_flow_step("crisis_support", 3)
            if message is None:
                # Fallback message if the flow step is missing
                message = (
                    "I'm glad you told me. If Mibo Crisis Help isn't available right now, please don't wait for it. "
                    "If you might hurt yourself, stay with someone you trust and go to the nearest emergency department "
                    "or contact emergency services immediately. You can also call Tele-MANAS at 14416 for immediate "
                    "mental-health support in India."
                )
            return message, session_state, True

        # Check for "help contacted"
        contacted_keywords = ["i contacted", "i've contacted", "contacted help", "i called", "i'm talking to"]
        if any(keyword in user_msg_lower for keyword in contacted_keywords):
            crisis_state["help_contacted"] = True
            session_state["crisis_state"] = crisis_state
            message = get_next_flow_step("crisis_support", 4)
            if message:
                message = message.replace("{user_name}", user_name_for_flow)
            else:
                # Fallback message if the flow step is missing
                message = (
                    f"I'm glad you reached out for help, {user_name_for_flow}. Please stay with the person or support service "
                    "you've contacted and avoid being alone right now. If you're still in immediate danger, "
                    "please continue with emergency support.\n\nAre you safe right now?"
                )
            return message, session_state, True

        # If help has been shown, but user says something generic or asks for an expert
        if crisis_state.get("help_shown"):
            # If user asks for an expert, repeat the crisis help message with the expert context.
            talk_to_human_keywords = ["expert", "doctor", "therapist", "someone", "person", "human", "talk", "help"]
            if any(keyword in user_msg_lower for keyword in talk_to_human_keywords):
                message = get_next_flow_step("crisis_support", 2)
                return message, session_state, True
            
            # For generic replies ("ok", "no need to show again"), give the supportive follow-up.
            # This prevents repeating the large initial message.
            message = get_next_flow_step("crisis_support", 1)
            return message, session_state, True

        # Initial Escalation (if help_shown is False)
        if not crisis_state.get("help_shown"):
            message = get_next_flow_step("crisis_support", 0).replace("{user_name}", user_name_for_flow)
            crisis_state["help_shown"] = True
            session_state["crisis_state"] = crisis_state
            return message, session_state, True

        # Fallback (should not be reached if logic is correct, but good for safety)
        message = get_next_flow_step("crisis_support", 1)
        return message, session_state, True

    continuations = [
        "ok", "okay", "yes", "yeah", "sure", "done", "next", "continue", "go on",
        "yes please", "we can try", "i would like that", "let's do it", "let's try", 
        "yep", "yup", "give", "i did it", "did it", "done it", "i do it", "completed", "ready",
        "anything", "whatever", "help me", "calm down", "want to calm down", "i want to calm down",
        "go ahead", "let's start", "start", "do it", "try it", "let's try it"
    ]
    is_continuation = any(c == user_msg_lower or user_msg_lower.startswith(c + " ") for c in continuations) or \
                      any(word in user_msg_lower for word in ["done", "finished", "completed"])

    # --- PRIORITY 0.5: DOCTOR BOOKING FLOW ---
    is_doctor_booking_intent = intent_data.get("intent") == "Doctor Booking"
    active_doctor_booking_flow = session_state.get("active_flow") == "doctor_booking"

    if is_doctor_booking_intent and not active_doctor_booking_flow:
        # The AI has already asked the first question. We just need to set the state.
        session_state["active_flow"] = "doctor_booking"
        session_state["booking_preferences"] = intent_data.get("user_preferences", {})
        session_state["booking_step"] = "concern" # Ready to receive the answer to the concern question
        # The AI reply from the main loop will be sent, so we return None here to not override it.
        # But we must return flow_active=True to prevent further processing.
        # However, the AI reply is generated *after* this call in some loops.
        # Let's return the first question from here to be safe and consistent with the therapist flow.
        ai_reply = intent_data.get("reply") or "Of course, I can help with that. To find the right Mibo expert, could you tell me a bit more about the main health concern you're facing?"
        return ai_reply, session_state, True

    if active_doctor_booking_flow:
        preferences = session_state.get("booking_preferences", {})
        booking_step = session_state.get("booking_step")

        # This block handles the user's ANSWER to the previously asked question.
        if booking_step:
            if booking_step == "concern":
                preferences["concern"] = user_message.strip()
            elif booking_step == "language":
                preferences["language"] = user_message.strip().capitalize()

        # Ask the next question if needed
        next_question, question_type = _get_next_doctor_booking_question(preferences)
        if next_question:
            session_state["booking_step"] = question_type
            session_state["booking_preferences"] = preferences
            return next_question, session_state, True
        else:
            # All info gathered, find an expert
            concern = preferences.get("concern", "general medical support")
            # For doctors, we default to finding a Psychiatrist as they are MDs
            experts = care_navigator_service.find_experts(
                concern=concern,
                severity="critical", # Prioritize MDs
                preferences=preferences,
                role_override="Psychiatrist" # Force search for Psychiatrists
            )

            if not experts:
                reply = (
                    "I'm sorry, I couldn't find a doctor available for a consultation right now. "
                    "This is unusual. I would recommend reaching out to a local medical clinic or emergency services if your concern is urgent."
                )
            else:
                expert = experts[0] # Recommend the top match
                reply = (
                    f"Based on your concern, I'd recommend consulting with **Dr. {expert['name']}**, who is a Psychiatrist. "
                    f"As a medical doctor, they can help assess both physical and mental health concerns.\n\n"
                    f"Dr. {expert['name']} speaks {', '.join(expert['languages'])} and is available for {', '.join(expert['consultation_types'])} consultations.\n\n"
                    "Would you like to book an appointment? I can guide you to the booking page in the Mibo app."
                )
                session_state["selected_expert"] = expert
                session_state["booking_step"] = "doctor_recommendation_shown"

            return reply, session_state, True

    if session_state.get("booking_step") == "doctor_recommendation_shown":
        if is_continuation or "book" in user_msg_lower:
            expert_name = session_state.get("selected_expert", {}).get("name", "the doctor")
            session_state["active_flow"] = None # End flow
            return f"Great! To book an appointment with Dr. {expert_name}, please visit the Mibo app. I can guide you there.", session_state, True
        else:
            session_state["active_flow"] = None # End flow
            return "Okay. What would you like to do instead?", session_state, True

    # --- PRIORITY 1: THERAPIST BOOKING FLOW ---
    is_booking_intent = intent_data.get("intent") == "Therapist Booking"
    active_booking_flow = session_state.get("active_flow") == "therapist_booking"

    if is_booking_intent and not active_booking_flow:
        # Step 1 & 2: Detect intent and Acknowledge
        session_state["active_flow"] = "therapist_booking"
        session_state["booking_preferences"] = intent_data.get("user_preferences", {})
        session_state["booking_step"] = "intro" # Start with the intro acknowledgment
        return (
            "I'd be happy to help you find the right Mibo expert. To recommend someone who best matches your needs, "
            "I'll just need to ask a few quick questions. Is that okay?"
        ), session_state, True

    if active_booking_flow:
        booking_step = session_state.get("booking_step", "intro")
        preferences = session_state.get("booking_preferences", {})

        # This block handles the user's ANSWER to the previously asked question.
        if booking_step != "intro":
            question_type = booking_step

            if question_type == "recommendations_shown":
                recommended_experts = session_state.get("recommended_experts", [])
                if not recommended_experts: # Safety check
                    session_state["active_flow"] = None
                    return "Something went wrong, let's start over.", session_state, True

                # NEW: Check if user is booking a specific expert by name
                if "book" in user_msg_lower:
                    chosen_expert = None
                    for expert in recommended_experts:
                        if expert['name'].lower() in user_msg_lower:
                            chosen_expert = expert
                            break
                    if chosen_expert:
                        session_state["selected_expert"] = chosen_expert
                        session_state["booking_step"] = "booking_guidance_shown"
                        return f"Great! To book an appointment with {chosen_expert['name']}, please visit the Mibo app. I can guide you there.", session_state, True

                if "compare" in user_msg_lower:
                    comparison_text = "Here’s a comparison of the recommended experts:\n\n"
                    for i, expert in enumerate(recommended_experts):
                        comparison_text += (
                            f"**{i+1}. {expert['name']} – {expert['role']}**\n"
                            f"- **Specialties:** {', '.join(expert['specializations'][:3])}\n"
                            f"- **Languages:** {', '.join(expert['languages'])}\n\n"
                        )
                    comparison_text += "Would you like to view a specific expert's full profile or book an appointment?"
                    session_state["booking_step"] = "compare_shown"
                    return comparison_text, session_state, True
                elif any(w in user_msg_lower for w in ["view", "profile", "details", "more"]):
                    session_state["booking_step"] = "awaiting_profile_choice"
                    expert_names = [f"{i+1}. {expert['name']}" for i, expert in enumerate(recommended_experts)]
                    reply = "Sure! Which expert would you like to know more about?\n\n" + "\n".join(expert_names)
                    return reply, session_state, True
                elif any(w in user_msg_lower for w in ["book", "appointment"]):
                    # Ask which expert to book
                    session_state["booking_step"] = "awaiting_profile_choice" # Re-use this to select an expert
                    expert_names = [f"{i+1}. {expert['name']}" for i, expert in enumerate(recommended_experts)]
                    reply = "Of course. Which expert would you like to book an appointment with?\n\n" + "\n".join(expert_names)
                    return reply, session_state, True
                else:
                    # Unrecognized intent, let the main AI loop handle it.
                    session_state["active_flow"] = None
                    return None, session_state, False

            elif question_type == "compare_shown":
                # After comparison, user can view profile or book. This logic is similar to recommendations_shown.
                if any(w in user_msg_lower for w in ["view", "profile", "details", "more"]):
                    session_state["booking_step"] = "awaiting_profile_choice"
                    recommended_experts = session_state.get("recommended_experts", [])
                    expert_names = [f"{i+1}. {expert['name']}" for i, expert in enumerate(recommended_experts)]
                    reply = "Sure! Which expert's full profile would you like to view?\n\n" + "\n".join(expert_names)
                    return reply, session_state, True
                # Fallback to let AI handle other intents
                session_state["active_flow"] = None
                return None, session_state, False

            elif question_type == "awaiting_profile_choice":
                recommended_experts = session_state.get("recommended_experts", [])
                chosen_expert = None
                # Find by number
                match = re.search(r'\b(\d+)\b', user_msg_lower)
                if match:
                    try:
                        choice_index = int(match.group(1)) - 1
                        if 0 <= choice_index < len(recommended_experts):
                            chosen_expert = recommended_experts[choice_index]
                    except (ValueError, IndexError): pass
                
                # Find by name if not by number
                if not chosen_expert:
                    for expert in recommended_experts:
                        if expert['name'].lower() in user_msg_lower:
                            chosen_expert = expert
                            break
                
                if chosen_expert:
                    session_state["selected_expert"] = chosen_expert
                    profile_reply = (
                        f"**{chosen_expert['name']}**\n{chosen_expert['role']}\n\n"
                        f"**Experience:** {chosen_expert['experience']}\n"
                        f"**Languages:** {', '.join(chosen_expert['languages'])}\n"
                        f"**Consultation:** {', '.join(chosen_expert['consultation_types'])}\n"
                        f"**Areas of expertise:**\n• " + "\n• ".join(chosen_expert['specializations']) +
                        "\n\nWould you like to:\n• Book an appointment\n• Compare with another expert\n• View another profile"
                    )
                    session_state["booking_step"] = "profile_shown"
                    return profile_reply, session_state, True
                else:
                    expert_names = [f"{i+1}. {expert['name']}" for i, expert in enumerate(recommended_experts)]
                    reply = "I'm sorry, I didn't recognize that choice. Please select an expert from the list by name or number:\n\n" + "\n".join(expert_names)
                    return reply, session_state, True
            
            elif question_type == "profile_shown":
                selected_expert = session_state.get("selected_expert", {})
                if not selected_expert: # Safety check
                    session_state["active_flow"] = None
                    return "Something went wrong, let's start over.", session_state, True
                
                if "fee" in user_msg_lower or "fees" in user_msg_lower or "how much" in user_msg_lower:
                    fee = selected_expert.get("fee", "₹1500 per session") # Mock fee for demonstration
                    reply = f"The consultation fee for {selected_expert['name']} is {fee}. Would you like to book an appointment?"
                    session_state["booking_step"] = "fee_shown"
                    return reply, session_state, True

                if any(w in user_msg_lower for w in ["book", "appointment"]):
                    session_state["booking_step"] = "booking_guidance_shown"
                    return f"To book an appointment with {selected_expert['name']}, please visit the Mibo app. I can guide you there.", session_state, True

                # If intent is not recognized, end the booking flow and provide a neutral response.
                session_state["active_flow"] = None
                return "Okay. What would you like to do instead?", session_state, True

            elif question_type == "fee_shown":
                selected_expert = session_state.get("selected_expert")
                if is_continuation or "book" in user_msg_lower:
                    session_state["booking_step"] = "booking_guidance_shown"
                    return f"Great! To book an appointment with {selected_expert['name']}, please visit the Mibo app. I can guide you there.", session_state, True
                else:
                    session_state["active_flow"] = None
                    return "Okay. What would you like to do instead?", session_state, True

            elif question_type == "booking_guidance_shown":
                selected_expert = session_state.get("selected_expert")
                if is_continuation:
                    # Fully reset the flow state here after the final message
                    session_state["active_flow"] = None
                    session_state["booking_step"] = None
                    session_state["booking_preferences"] = {}
                    session_state["recommended_experts"] = []
                    session_state["selected_expert"] = None
                    
                    expert_name = selected_expert['name'] if selected_expert else "the expert"
                    
                    return (
                        f"You're welcome! I hope you're able to connect with {expert_name} soon.\n\n"
                        "If you need any help before or after your appointment, or if you'd like support with anything else, I'm here for you."
                    ), session_state, True
                else:
                    # If they ask something else, let the AI handle it by ending the flow.
                    session_state["active_flow"] = None
                    return None, session_state, False

            answer = user_msg_lower
            
            if question_type == "concern":
                preferences["concern"] = user_message.strip()
            elif question_type == "consultation_type":
                if "online" in answer:
                    preferences["consultation_type"] = "Online"
                elif "person" in answer:
                    preferences["consultation_type"] = "In-person"
                else: # Invalid answer, re-ask
                    question, _ = _get_next_booking_question({"concern": preferences.get("concern")})
                    return f"I didn't quite catch that. {question}", session_state, True
            elif question_type == "language":
                cleaned_lang = answer
                for prefix in ["yes, ", "sure, ", "i prefer ", "please ", "i speak "]:
                    if cleaned_lang.startswith(prefix):
                        cleaned_lang = cleaned_lang[len(prefix):]
                cleaned_lang = cleaned_lang.replace(" please", "").strip()
                if cleaned_lang:
                    preferences["language"] = cleaned_lang.capitalize()
                else: # Invalid answer, re-ask
                    question, _ = _get_next_booking_question({"concern": preferences.get("concern"), "consultation_type": preferences.get("consultation_type")})
                    return f"Sorry, which language was that?", session_state, True
            elif question_type == "city":
                known_cities = ["kochi", "bengaluru", "mumbai"]
                found_city = next((city for city in known_cities if city in answer), None)
                if found_city:
                    preferences["city"] = found_city.capitalize()
                else:
                    return "I'm sorry, I can only search in Kochi, Bengaluru, or Mumbai right now. Which would you prefer?", session_state, True

        # Handle the intro step
        if booking_step == "intro":
            if not is_continuation: # User said "no" or something else
                session_state["active_flow"] = None
                return "Okay, no problem. What would you like to do instead?", session_state, True
        
        # Step 3: Collect missing information by asking the next question
        next_question, question_type = _get_next_booking_question(preferences)

        if next_question:
            session_state["booking_step"] = question_type
            session_state["booking_preferences"] = preferences
            return next_question, session_state, True
        else:
            # Step 4 & 5: All info gathered, search, rank, and explain recommendations
            concern = preferences.get("concern", "general support")
            severity = emotion_data.get("severity_level", "moderate")
            experts = care_navigator_service.find_experts(
                concern=concern,
                severity=severity.lower(),
                preferences=preferences
            )

            recommendation_intro = ""
            final_reply = ""

            if not experts:
                recommendation_intro = (
                    "I'm sorry, but I couldn't find any experts matching your primary need right now. "
                    "This is unusual. We can try another wellness activity, or I can connect you with "
                    "our support team to look into this."
                )
                final_reply = recommendation_intro
            else:
                recommendation_intro = "Based on what you've shared, here are the experts I'd recommend:\n\n"
                
                # Determine mapped specializations once before the loop for efficiency
                _, mapped_specs_list = care_navigator_service.map_concern_to_role_and_specialization(concern, severity)
                mapped_specs = set(s.lower() for s in mapped_specs_list)
                recommendations = []
                for expert in experts:
                    rec_points = []
                    expert_specs_lower = {s.lower() for s in expert["specializations"]}
                    matches = mapped_specs.intersection(expert_specs_lower)
                    
                    if matches:
                        display_matches = [s.title().replace("Cbt", "CBT").replace("Dbt", "DBT") for s in matches]
                        rec_points.append(f"• Supports with {', '.join(display_matches[:2])} and emotional well-being")
                    else:
                        rec_points.append(f"• Experienced in {expert['specializations'][0]}")

                    # Consultation type
                    if preferences.get("consultation_type") in expert["consultation_types"]:
                        rec_points.append(f"• Available for {preferences['consultation_type'].lower()} consultations")

                    # Language
                    rec_points.append(f"• Speaks {', '.join(expert['languages'])}")

                    rec_text = (
                        f"**{expert['name']} – {expert['role']}**\n" +
                        "\n".join(rec_points)
                    )
                    recommendations.append(rec_text)
                
                final_reply = recommendation_intro + "\n\n---\n\n".join(recommendations)
                # Step 6: Next action
                final_reply += (
                    "\n\nWould you like to:\n\n"
                    "• View an expert's full profile\n"
                    "• Compare the recommended experts\n"
                    "• Book an appointment"
                )

            # Transition to the next state instead of ending the flow
            session_state["active_flow"] = "therapist_booking"
            session_state["booking_step"] = "recommendations_shown"
            session_state["recommended_experts"] = experts
            return final_reply, session_state, True

    # --- NEW: Decline handling for pending flows ---
    is_decline = user_msg_lower in ["no", "no thanks", "not now"]
    if session_state.get("awaiting_confirmation") and is_decline:
        # User declined the pending flow.
        
        # Mark the exercise as refused
        pending_flow = session_state.get("pending_flow")
        if pending_flow:
            refused = session_state.get("refused_exercises", [])
            if pending_flow not in refused:
                refused.append(pending_flow)
            session_state["refused_exercises"] = refused

        # Reset confirmation state so we don't get stuck here
        session_state["awaiting_confirmation"] = False
        session_state["pending_flow"] = None
        
        # Offer alternatives and let the next AI turn figure out the intent
        reply = (
            "That's completely okay. We don't have to do that.\n\n"
            "Would you prefer to talk about what's on your mind, try a different kind of calming technique, or perhaps get some support from a Mibo expert?"
        )
        return reply, session_state, True

    # 0. Identify Continuations and Stops early
    # Negative Feedback Detection (No improvement after exercise)
    negative_feedback = ["no change", "no changes", "still stressed", "not working", "didn't help", "no better", "still feel", "no difference"]
    has_negative_feedback = any(f in user_msg_lower for f in negative_feedback)
    is_stop = any(word in user_msg_lower for word in ["stop", "cancel", "exit", "quit", "no more", "nevermind", "end this", "don't want to"])

    # 1. Basic Intent/Stop/Pivot Detection
    greetings = ["hi", "hello", "hey", "hii", "howdy", "sup", "greetings", "good morning", "good evening", "good afternoon"]
    
    # Check for greeting (either AI detected or keyword matched)
    has_greeting_word = any(word == user_msg_lower or user_msg_lower.startswith(word + " ") for word in greetings)
    is_greeting = (intent_data.get("emotion") == "neutral" and has_greeting_word) or (has_greeting_word and len(user_msg_lower) < 10)
    
    # Emotional Pivot Detection: Only pivot if NOT a simple continuation
    is_explicit_emotion = any(phrase in user_msg_lower for phrase in ["i feel", "i'm feeling", "i am feeling", "feeling really", "feeling so"])
    emotion = emotion_data.get("emotion", "neutral")
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
                # This is a critical risk signal. Activate the full crisis protocol.
                session_state["active_assessment"] = None # Exit assessment
                session_state["critical_risk_active"] = True
                session_state["active_flow"] = "crisis_support"
                session_state["current_step"] = 0 # Start the crisis flow from the beginning

                # Return the first message of the crisis flow directly.
                user_name_for_flow = user_name or session_state.get("user_name", "there")
                escalation_message = get_next_flow_step("crisis_support", 0).replace("{user_name}", user_name_for_flow)
                session_state["current_step"] = 1 # We've sent step 0, now waiting for response.
                return escalation_message, session_state, True

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
