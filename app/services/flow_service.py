
import json
import re
from app.services.redis_service import redis_client, SimpleCache
from datetime import date, timedelta
from app.services.therapy_service import get_next_flow_step
from app.services import assessment_service
from app.services import care_navigator_service, therapy_service

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

# Crisis Flow States
CRISIS_STATUS_DETECTED = "CRISIS_DETECTED"
CRISIS_STATUS_HELP_SHOWN = "CRISIS_HELP_SHOWN"
CRISIS_STATUS_HELP_UNAVAILABLE = "CRISIS_HELP_UNAVAILABLE"
CRISIS_STATUS_HELP_CONTACTED = "CRISIS_HELP_CONTACTED"
CRISIS_STATUS_SAFETY_CHECK = "CRISIS_SAFETY_CHECK"
CRISIS_STATUS_IMMEDIATE_DANGER = "CRISIS_IMMEDIATE_DANGER"
CRISIS_STATUS_EMERGENCY_CONTACT_INFO_PROVIDED = "CRISIS_EMERGENCY_CONTACT_INFO_PROVIDED" # NEW
CRISIS_STATUS_PENDING_RESOLUTION = "CRISIS_PENDING_RESOLUTION" # NEW
CRISIS_STATUS_RESOLVED = "CRISIS_RESOLVED"

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

    if not preferences.get("language") and preferences.get("concern"): # Only ask language after concern
        return "Do you have a preferred language for your consultation? (e.g., Malayalam, English, Hindi)", "language"

    return None, None # All info gathered

def _format_expert_profile(expert: dict):
    """Formats an expert's profile into a readable string."""
    if not expert:
        return "No expert details available."
    
    profile = f"**{expert.get('name', 'N/A')}**\n"
    profile += f"_{expert.get('role', 'Expert')}_\n\n"
    profile += f"**Experience:** {expert.get('experience', 'N/A')}\n"
    profile += f"**Specializations:** {', '.join(expert.get('specializations', ['N/A']))}\n"
    profile += f"**Languages:** {', '.join(expert.get('languages', ['N/A']))}\n"
    profile += f"**Consultation Types:** {', '.join(expert.get('consultation_types', ['N/A']))}\n"
    if "In-person" in expert.get('consultation_types', []):
        profile += f"**Location:** {expert.get('city', 'N/A')}\n"
    
    return profile

def _format_expert_comparison(experts: list):
    """Formats a comparison of multiple experts into a readable string."""
    if not experts:
        return "No experts available to compare."

    reply = "Here's a comparison of the recommended experts:\n\n"
    
    for i, expert in enumerate(experts):
        reply += f"**{i+1}. {expert.get('name', 'N/A')}** ({expert.get('role', 'Expert')})\n"
        reply += f"  • **Specializations:** {', '.join(expert.get('specializations', ['N/A']))}\n"
        reply += f"  • **Experience:** {expert.get('experience', 'N/A')}\n"
        reply += f"  • **Languages:** {', '.join(expert.get('languages', ['N/A']))}\n"
        reply += f"  • **Consultation:** {', '.join(expert.get('consultation_types', ['N/A']))}\n"
        if "In-person" in expert.get('consultation_types', []):
            reply += f"  • **Location:** {expert.get('city', 'N/A')}\n"
        reply += "\n"
        
    return reply

def _parse_booking_date(message: str) -> date | None:
    """
    Parses a natural language or formatted date string into a datetime.date object.
    Handles "today", "tomorrow", "day after tomorrow", YYYY-MM-DD, DD-MM, DD/MM,
    Month Day, Day Month, and day of week.
    """
    message_lower = message.lower().strip()
    today = date.today()

    if message_lower == "today":
        return today
    elif message_lower == "tomorrow":
        return today + timedelta(days=1)
    elif message_lower == "day after tomorrow":
        return today + timedelta(days=2)
    
    # YYYY-MM-DD format
    date_match = re.match(r"(\d{4})-(\d{2})-(\d{2})", message_lower)
    if date_match:
        try:
            year, month, day = map(int, date_match.groups())
            return date(year, month, day)
        except ValueError:
            pass

    # DD-MM or DD/MM (assuming current year)
    date_match_dm = re.match(r"(\d{1,2})[/-](\d{1,2})", message_lower)
    if date_match_dm:
        try:
            day, month = map(int, date_match_dm.groups())
            return date(today.year, month, day)
        except ValueError:
            pass

    # Month Day (e.g., "August 15", "15 August")
    month_names = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
    }
    
    # "August 15"
    month_day_match = re.match(r"([a-z]+)\s+(\d{1,2})", message_lower)
    if month_day_match:
        month_str, day_str = month_day_match.groups()
        month_num = month_names.get(month_str)
        if month_num:
            try:
                return date(today.year, month_num, int(day_str))
            except ValueError:
                pass
    
    # "15 August"
    day_month_match = re.match(r"(\d{1,2})\s+([a-z]+)", message_lower)
    if day_month_match:
        day_str, month_str = day_month_match.groups()
        month_num = month_names.get(month_str)
        if month_num:
            try:
                return date(today.year, month_num, int(day_str))
            except ValueError:
                pass

    # Day of week (e.g., "Monday") - for simplicity, assume next occurrence
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    if message_lower in day_names:
        current_weekday = today.weekday() # Monday is 0, Sunday is 6
        target_weekday = day_names.index(message_lower)
        days_ahead = (target_weekday - current_weekday + 7) % 7
        if days_ahead == 0: # If today is that day, assume next week
            days_ahead = 7
        return today + timedelta(days=days_ahead)

    return None

def handle_flow_logic(user_message: str, session_state: dict, intent_data: dict = None, emotion_data: dict = None, db=None, user_name: str = None):
    """
    Returns (reply, updated_state, flow_active, pending_intent_to_process)
    If flow_active is True, the reply should be sent and further AI processing skipped.
    pending_intent_to_process is a dict to be processed by the main loop after crisis resolution.
    """
    user_msg_lower = user_message.lower().strip()
    intent_data = intent_data or {}
    emotion_data = emotion_data or {}

    # --- DEBUG LOGGING ---
    print(f"USER: {user_message}")
    print(f"INTENT: {intent_data.get('intent')}")
    print(f"ACTIVE FLOW: {session_state.get('active_flow')}")
    print(f"BOOKING STEP: {session_state.get('booking_step')}")

    # --- PRIORITY -2: GREETING AND PIVOT RESET ---
    # A simple greeting or a clear emotional pivot should reset any stale state
    # that might have been restored from a previous session (e.g., a stuck crisis flow).
    # This ensures that a new conversation starts fresh.
    greetings = ["hi", "hello", "hey", "hii", "howdy", "sup", "greetings", "good morning", "good evening", "good afternoon"]
    continuations_for_reset_check = [
        "ok", "okay", "yeah", "sure", "done", "next", "continue", "go on", "yes"
    ]
    is_not_a_continuation = user_msg_lower not in continuations_for_reset_check

    has_greeting_word = any(word == user_msg_lower or user_msg_lower.startswith(word + " ") for word in greetings)
    is_greeting_reset = is_not_a_continuation and has_greeting_word and len(user_msg_lower) < 20

    is_explicit_emotion = any(phrase in user_msg_lower for phrase in ["i feel", "i'm feeling", "i am feeling"])
    is_emotional_pivot = is_not_a_continuation and is_explicit_emotion

    # If a flow is active from a restored session, but the user is starting over with a greeting or new emotion, reset the state.
    if (is_greeting_reset or is_emotional_pivot) and (session_state.get("active_flow") or session_state.get("awaiting_confirmation")):
        # This is a strong signal that the user is starting a new conversation,
        # ignoring the restored session state. We should reset the flow state.
        user_id = session_state.get("user_id")
        user_name_preserved = session_state.get("user_name")
        # Create a fresh state, but keep essential info
        session_state = {"user_id": user_id, "user_name": user_name_preserved}
        # Fall through to the normal AI response by returning False for flow_active.
        # The AI will then process the greeting or new emotion as the start of a new conversation.
        return None, session_state, False, None

    # --- PRIORITY -1: HARDCODED CRITICAL RISK OVERRIDE ---
    # This is a non-AI, keyword-based check that acts as a final safety net.
    # It overrides any other active flow if a new critical risk message is detected,
    # ensuring that a restored session state with an active flow (e.g., booking)
    # is immediately interrupted by a new crisis.
    CRITICAL_RISK_ENTRY_PHRASES = [
        "i want to end my life", "i want to kill myself", "i want to die",
        "i don't want to live", "i am going to hurt myself", "i'm going to kill myself",
        "i'm going to end it all", "goodbye everyone"
    ]
    is_hardcoded_critical_risk = any(phrase in user_msg_lower for phrase in CRITICAL_RISK_ENTRY_PHRASES)
    is_new_crisis_for_override = session_state.get("active_flow") != "crisis_support"

    if is_hardcoded_critical_risk and is_new_crisis_for_override:
        session_state["crisis_state"] = {"status": CRISIS_STATUS_DETECTED}
        session_state["active_flow"] = "crisis_support"
        user_name_for_flow = user_name or session_state.get("user_name", "there")
        message = get_next_flow_step("crisis_support", 0).replace("{user_name}", user_name_for_flow)
        session_state["crisis_state"]["status"] = CRISIS_STATUS_HELP_SHOWN
        return message, session_state, True, None

    # Define is_continuation early, as it's used in crisis flow logic
    continuations = [
        "ok", "okay", "yeah", "sure", "done", "next", "continue", "go on",
        "yes please", "we can try", "i would like that", "let's do it", "let's try", # "yes" removed from here
        "yep", "yup", "give", "i did it", "did it", "done it", "i do it", "completed", "ready", # "yes" removed from here
        "anything", "whatever", "help me", "calm down", "want to calm down", "i want to calm down", # "yes" removed from here
        "go ahead", "let's start", "start", "do it", "try it", "let's try it", # "yes" removed from here
    ]
    is_continuation = any(c == user_msg_lower or user_msg_lower.startswith(c + " ") for c in continuations) or \
                      any(word in user_msg_lower for word in ["done", "finished", "completed"])

    # Initialize pending intent to process after crisis resolution
    pending_intent_to_process = None

    # Store the active flow and current step for easier access
    active_flow = session_state.get("active_flow")
    current_step = session_state.get("current_step", 0)
    booking_step = session_state.get("booking_step")

    message = None # Initialize message to None
    # --- PRIORITY 0.0: CRISIS RESOLUTION CHECK (from previous turn) ---
    # If the crisis was resolved in the *previous* turn, clear the state and potentially re-process a pending intent.
    if session_state.get("crisis_state", {}).get("status") == CRISIS_STATUS_RESOLVED:
        pending_normal_intent = session_state["crisis_state"].get("pending_normal_intent")
        pending_user_preferences = session_state["crisis_state"].get("pending_user_preferences")

        session_state["crisis_state"] = {} # Clear the crisis state
        session_state["active_flow"] = None # Ensure active_flow is also cleared

        if pending_normal_intent:
            pending_intent_to_process = {
                "intent": pending_normal_intent,
                "user_preferences": pending_user_preferences
            }
            print(f"DEBUG: Crisis resolved, returning pending intent: {pending_normal_intent}")
        # Do NOT return True here. Let the message fall through to other flow logic.

    # --- NEW PRIORITY 0.05: HIGH-PRIORITY INTENT INTERRUPTION (Booking Flow) ---
    # This block checks for booking intents and interrupts any non-crisis flow.
    # It also handles the continuation of an active booking flow.
    is_therapist_booking_intent = intent_data.get("intent") == "Therapist Booking"
    is_doctor_booking_intent = intent_data.get("intent") == "Doctor Booking"

    # Condition to either INITIATE a booking flow (interrupting another) or CONTINUE an existing one.
    should_handle_booking = (
        active_flow in ["therapist_booking", "doctor_booking"] or
        ((is_therapist_booking_intent or is_doctor_booking_intent) and active_flow != "crisis_support")
    )

    if should_handle_booking:
        # A) INITIATE/INTERRUPT: A new booking intent is detected, and it's not already the active flow
        if (is_therapist_booking_intent or is_doctor_booking_intent) and active_flow not in ["therapist_booking", "doctor_booking"]:
            flow_type = "therapist_booking" if is_therapist_booking_intent else "doctor_booking"
            
            # Clean up state from any interrupted wellness flow.
            session_state["active_flow"] = flow_type
            session_state.pop("pending_flow", None)
            session_state.pop("awaiting_confirmation", None)
            session_state.pop("current_step", None)
            
            booking_preferences = intent_data.get("user_preferences", {})
            current_need = session_state.get("current_need")
            
            # Preserve context if the user was in a wellness flow (e.g., for stress).
            if not booking_preferences.get("concern") and current_need:
                booking_preferences["concern"] = current_need
            session_state["booking_preferences"] = booking_preferences
            
            # If we have the concern (from context or intent), we can skip the intro and ask the next relevant question.
            if booking_preferences.get("concern"):
                if flow_type == "therapist_booking":
                    next_question, preference_key = _get_next_booking_question(booking_preferences)
                else: # doctor_booking
                    next_question, preference_key = _get_next_doctor_booking_question(booking_preferences)
                    
                if next_question:
                    session_state["booking_step"] = preference_key
                    reply = f"Of course. Since you mentioned you're feeling {booking_preferences['concern']}, I can help you find an expert for support. {next_question}"
                    return reply, session_state, True, None
                # If no next question, it means all info was in the first message. Fall through to find experts.
            else: # We don't have a concern, so start with the standard confirmation intro.
                session_state["booking_step"] = "intro"
                if flow_type == "doctor_booking":
                    reply = (
                        "Of course, I can help with that. To find the right Mibo expert, "
                        "I'll just need to ask a couple of quick questions. Is that okay?"
                    )
                else:
                    reply = (
                        "I'd be happy to help you find the right Mibo expert. To recommend someone who best matches your needs, "
                        "I'll just need to ask a few quick questions. Is that okay?"
                    )
                return reply, session_state, True, None

        # B) CONTINUE: A booking flow is already active. Process the user's response.
        preferences = session_state.get("booking_preferences", {})
        if booking_step == "intro":
            affirmative_responses = ["yes", "ok", "okay", "sure", "yeah", "yep", "yup", "go ahead", "let's do it"]
            if not any(resp == user_msg_lower or user_msg_lower.startswith(resp + " ") for resp in affirmative_responses):
                # User said no to starting the flow
                session_state["active_flow"] = None
                session_state.pop("booking_step", None)
                session_state.pop("booking_preferences", None)
                return "Okay, no problem. What would you like to do instead?", session_state, True, None
            # If user says yes, we fall through to ask the first question.
            session_state['booking_step'] = None # Clear 'intro' to proceed

        elif booking_step == "expert_action":
            # This is where user interacts with recommendations (view profile, compare, book, refine)
            if "profile" in user_msg_lower or "view" in user_msg_lower:
                session_state["booking_step"] = "expert_profile_selection" # Set state to wait for selection
                return "Which expert's profile would you like to view? You can tell me their name or number from the list.", session_state, True, None
            elif "compare" in user_msg_lower:
                recommended_experts = session_state.get("recommended_experts", [])
                comparison_text = _format_expert_comparison(recommended_experts)
                
                # After showing comparison, present the next actions.
                reply = f"{comparison_text}\nWhat would you like to do next?\n"
                reply += "• View an expert's full profile\n"
                reply += "• Book an appointment\n"
                reply += "• Refine search"
                return reply, session_state, True, None
            elif "book" in user_msg_lower:
                session_state["booking_step"] = "booking_expert_selection" # Set state to wait for selection
                return "Okay, I can help you book. Which expert would you like to book with? You can tell me their name or number.", session_state, True, None
            elif "refine" in user_msg_lower:
                session_state["booking_step"] = "concern" # Go back to the first question
                session_state["booking_preferences"] = {} # Clear preferences to restart
                return "Okay, let's refine your search. What would you like support with today?", session_state, True, None
            # If user says "ok" or something generic, re-prompt the options
            reply = "What would you like to do next?\n"
            reply += "• View an expert's full profile\n"
            reply += "• Compare the recommended experts\n"
            reply += "• Book an appointment\n"
            reply += "• Refine search"
            return reply, session_state, True, None

        elif booking_step == "expert_profile_selection":
            recommended_experts = session_state.get("recommended_experts", [])
            selected_expert = None

            # Try to match by number
            if user_message.strip().isdigit():
                index = int(user_message.strip()) - 1
                if 0 <= index < len(recommended_experts):
                    selected_expert = recommended_experts[index]
            
            # If not found by number, try to match by name
            if not selected_expert:
                name_query = user_message.strip().lower()
                for expert in recommended_experts:
                    expert_name = expert.get("name", "").lower()
                    if name_query in expert_name:
                        selected_expert = expert
                        break
            
            if selected_expert:
                session_state["selected_expert"] = selected_expert
                session_state["booking_step"] = "expert_action" # Return to the main action menu
                profile_details = _format_expert_profile(selected_expert)
                reply = f"{profile_details}\n\nWhat would you like to do next?\n• Book an appointment\n• View another profile\n• Refine your search"
                return reply, session_state, True, None
            else:
                # Could not find the expert. Re-prompt but stay in the selection state.
                return "I'm sorry, I couldn't find an expert with that name or number in the list. Please try again.", session_state, True, None

        elif booking_step == "booking_expert_selection":
            recommended_experts = session_state.get("recommended_experts", [])
            selected_expert = None

            # Try to match by number
            if user_message.strip().isdigit():
                index = int(user_message.strip()) - 1
                if 0 <= index < len(recommended_experts):
                    selected_expert = recommended_experts[index]
            
            # If not found by number, try to match by name
            if not selected_expert:
                name_query = user_message.strip().lower()
                for expert in recommended_experts:
                    expert_name = expert.get("name", "").lower()
                    if name_query in expert_name:
                        selected_expert = expert
                        break
            
            if selected_expert:
                session_state["selected_expert"] = selected_expert
                session_state["booking_step"] = "booking_date_selection" # Transition to the next step in the booking process
                reply = f"Great, you've selected {selected_expert['name']}. What date would you like to book your appointment?"
                return reply, session_state, True, None
            else:
                # Could not find the expert. Re-prompt but stay in the selection state.
                return "I'm sorry, I couldn't find an expert with that name or number in the list. Please try again.", session_state, True, None

        elif booking_step == "booking_date_selection":
            requested_date = _parse_booking_date(user_message)
            if requested_date:
                session_state["booking_date"] = requested_date.isoformat() # Store as ISO format string
                session_state["booking_step"] = "booking_time_selection"
                selected_expert_name = session_state.get("selected_expert", {}).get("name", "the expert")
                # Placeholder for fetching actual available times
                # For now, just ask for a time
                reply = f"Okay, for {selected_expert_name} on {requested_date.strftime('%A, %B %d')}. What time would you prefer? (e.g., 10 AM, 2:30 PM)"
                return reply, session_state, True, None
            else:
                # Invalid date format, re-prompt
                return "I'm sorry, I didn't understand that date. Please tell me the date you'd like to book (e.g., 'tomorrow', 'August 15', or '2024-08-15').", session_state, True, None

        elif booking_step == "booking_time_selection":
            # This is where you would parse the time and confirm the booking
            # For now, just a placeholder to show it's advancing
            session_state["booking_time"] = user_message # Store raw time for now
            session_state["booking_step"] = "booking_confirmation"
            selected_expert_name = session_state.get("selected_expert", {}).get("name", "the expert")
            booking_date = session_state.get("booking_date")
            
            # You would typically fetch available slots here and present them.
            # For now, a simple confirmation.
            reply = f"Confirming your booking with {selected_expert_name} on {booking_date} at {user_message}. Is that correct?"
            return reply, session_state, True, None

        elif booking_step == "booking_confirmation":
            # This state would handle the final 'yes' or 'no' to confirm the booking.
            # For now, we'll just acknowledge and end the flow.
            if user_msg_lower in ["yes", "yep", "confirm"]:
                session_state["active_flow"] = None # End the booking flow
                session_state.pop("booking_step", None)
                session_state.pop("booking_preferences", None)
                session_state.pop("selected_expert", None)
                session_state.pop("booking_date", None)
                session_state.pop("booking_time", None)
                return "Great! Your appointment has been successfully booked. You'll receive a confirmation shortly.", session_state, True, None
            else:
                session_state["active_flow"] = None # End the booking flow
                session_state.pop("booking_step", None)
                session_state.pop("booking_preferences", None)
                session_state.pop("selected_expert", None)
                session_state.pop("booking_date", None)
                session_state.pop("booking_time", None)
                return "Okay, the booking has been cancelled. What would you like to do instead?", session_state, True, None

        elif booking_step: # Gather preference if a step is defined
            preferences[booking_step] = user_message
            session_state["booking_preferences"] = preferences

        # C) DETERMINE NEXT STEP OR FINISH: Get the next question or find experts.
        next_question, preference_key = (_get_next_booking_question(preferences) if active_flow == "therapist_booking" 
                                         else _get_next_doctor_booking_question(preferences))

        if next_question:
            session_state["booking_step"] = preference_key
            return next_question, session_state, True, None
        else:
            # All info gathered, find experts and end the flow.
            role_override = "Psychiatrist" if active_flow == "doctor_booking" else None
            experts = care_navigator_service.find_experts(
                concern=preferences.get("concern", "general support"),
                severity="moderate",
                preferences=preferences,
                role_override=role_override
            )
            if not experts:
                session_state["booking_step"] = "concern" # Reset to first question
                session_state["booking_preferences"] = {}
                reply = "I'm sorry, I couldn't find any experts that match your preferences right now. Would you like to change your preferences and try again? Let's start over: what would you like support with?"
                return reply, session_state, True, None
            else:
                reply = "Great, thank you. Based on what you've told me, here are a few experts who might be a good fit:\n\n"
                for i, expert in enumerate(experts):
                    reply += f"{i+1}. **{expert['name']}** ({expert['role']})\n"
                
                session_state["booking_step"] = "expert_action" # Set state for next turn
                session_state["recommended_experts"] = experts # Store experts

                reply += "\nWhat would you like to do next?\n"
                reply += "• View an expert's full profile\n"
                reply += "• Compare the recommended experts\n"
                reply += "• Book an appointment\n"
                reply += "• Refine search"

            return reply, session_state, True, None


    # --- NEW PRIORITY 0.06: HANDLE PENDING EXPERT CONFIRMATION ---
    # This block handles the user's response after ZuraAI has offered to suggest an expert post-crisis.
    if session_state.get("awaiting_expert_confirmation"):
        # Check if the user's message is a new, strong intent that should override the pending expert confirmation.
        # This prevents "I'm feeling stressed" from being interpreted as an unclear response to "suggest an expert?".
        # We allow booking intents to still be processed here if they are explicit, as they are high priority.
        if intent_data.get("intent") not in ["General chat", "None"] and \
           intent_data.get("intent") not in ["Therapist Booking", "Doctor Booking", "CRISIS_EMERGENCY_CONTACT_REQUEST"] and \
           intent_data.get("risk_level") != "critical":
            
            # A new, non-booking, non-crisis intent detected. Clear pending expert confirmation and let the new intent be processed.
            session_state["awaiting_expert_confirmation"] = False
            print(f"DEBUG: Overriding pending expert confirmation due to new intent: {intent_data.get('intent')}")
            # Fall through to other flow logic (e.g., wellness flow initiation)
            return None, session_state, False, None
        affirmative_responses = ["yes", "yeah", "sure", "yep", "yup", "i would like that", "let's do it", "go ahead", "start", "book", "suggest"]
        negative_responses = ["no", "no thanks", "not now", "not really", "i don't want to", "i don't need"]

        if any(resp == user_msg_lower or user_msg_lower.startswith(resp + " ") for resp in affirmative_responses):
            session_state["awaiting_expert_confirmation"] = False # Clear the flag
            # Initiate Therapist Booking flow
            session_state["active_flow"] = "therapist_booking"
            session_state["booking_preferences"] = {}
            session_state["booking_step"] = "intro"
            reply = (
                "I'd be happy to help you find the right Mibo expert. To recommend someone who best matches your needs, "
                "I'll just need to ask a few quick questions. Is that okay?"
            )
            return reply, session_state, True, None
        elif any(resp == user_msg_lower or user_msg_lower.startswith(resp + " ") for resp in negative_responses):
            session_state["awaiting_expert_confirmation"] = False # Clear the flag
            session_state["active_flow"] = None # Ensure no flow is active
            return "Okay, no problem. What would you like to do instead?", session_state, True, None
        else:
            # User said something unclear, re-ask or clarify
            return "I'm sorry, I didn't quite catch that. Would you like me to suggest a mental-health professional?", session_state, True, None

    # --- NEW PRIORITY 0.07: HANDLE PENDING WELLNESS FLOW CONFIRMATION ---
    # This block handles the user's response after ZuraAI has offered a wellness activity.
    if session_state.get("awaiting_confirmation") and session_state.get("pending_flow") and not should_handle_booking:
        # This check ensures we don't clash with the expert confirmation logic which has its own state.
        if not session_state.get("awaiting_expert_confirmation"):
            affirmative_responses = ["yes", "yeah", "sure", "yep", "yup", "i would like that", "let's do it", "go ahead", "start", "try it", "we can try", "let's try"]
            negative_responses = ["no", "no thanks", "not now", "not really", "i don't want to", "i don't need"]

            if any(resp == user_msg_lower or user_msg_lower.startswith(resp + " ") for resp in affirmative_responses):
                # User confirmed. Start the pending flow.
                active_flow = session_state.pop("pending_flow")
                session_state["awaiting_confirmation"] = False
                session_state["active_flow"] = active_flow
                session_state["current_step"] = 0 # Always start a new flow at step 0
                session_state["media_session_active"] = False

                # Get the first step of the flow and return it.
                next_text = get_next_flow_step(active_flow, 0)
                if next_text:
                    session_state["current_step"] = 1
                    session_state["last_exercise"] = active_flow
                    return next_text, session_state, True, None
                else: # Flow has no steps? End it.
                    session_state["active_flow"] = None
                    return "It seems there was an issue starting that activity. What would you like to do instead?", session_state, True, None

            elif any(resp == user_msg_lower or user_msg_lower.startswith(resp + " ") for resp in negative_responses):
                # User declined the pending flow.
                pending_flow = session_state.pop("pending_flow", "an activity")
                session_state["awaiting_confirmation"] = False
                
                # Mark the exercise as refused
                refused = session_state.get("refused_exercises", [])
                if pending_flow not in refused:
                    refused.append(pending_flow)
                session_state["refused_exercises"] = refused
                
                # Offer alternatives
                reply = (
                    "That's completely okay. We don't have to do that.\n\n"
                    "Would you prefer to talk about what's on your mind, try a different kind of calming technique, or perhaps get some support from a Mibo expert?"
                )
                return reply, session_state, True, None
            else:
                # If the response is unclear, re-prompt for clarity.
                pending_flow_name = session_state.get("pending_flow", "a wellness activity").replace("_", " ")
                return f"Sorry, I didn't quite catch that. Would you like to try the {pending_flow_name} activity?", session_state, True, None

    # --- NEW PRIORITY 0.08: CRITICAL RISK INTERVENTION (main crisis handling) ---
    # This block is the absolute authority on critical risk state. It cannot be exited by normal conversation.
    # Activation:
    # This is the entry point into the crisis flow.
    is_critical_risk_signal = intent_data.get("risk_level") == "critical"
    is_new_crisis = active_flow != "crisis_support"

    if is_critical_risk_signal and is_new_crisis:
        session_state["crisis_state"] = {"status": CRISIS_STATUS_DETECTED}
        session_state["active_flow"] = "crisis_support" # Prioritizes this flow
        user_name_for_flow = user_name or session_state.get("user_name", "there")
        message = get_next_flow_step("crisis_support", 0).replace("{user_name}", user_name_for_flow)
        session_state["crisis_state"]["status"] = CRISIS_STATUS_HELP_SHOWN
        return message, session_state, True, None
    
    if active_flow == "crisis_support":
        crisis_state = session_state["crisis_state"]
        user_name_for_flow = user_name or session_state.get("user_name", "there")
        current_crisis_status = crisis_state.get("status")

        # --- CONTEXT-AWARE BOOLEANS FOR CRISIS FLOW ---
        # These flags determine the meaning of "yes" or "no" based on the question asked (i.e., the current state).

        # 1. Check for explicit safety phrases that are always safe.
        explicit_safety_keywords = ["i'm safe", "i am safe", "not in danger", "i'm okay now", "i am okay now", "i'm fine now", "yes i'm safe", "yes i am safe", "i won't hurt myself"]
        is_explicit_safety_phrase = any(keyword in user_msg_lower for keyword in explicit_safety_keywords)

        # 2. Determine if "yes" means the user is confirming they are safe.
        # This is only true if we asked "Are you safe?".
        is_safety_question_context = current_crisis_status in [
            CRISIS_STATUS_SAFETY_CHECK,
            CRISIS_STATUS_PENDING_RESOLUTION,
            CRISIS_STATUS_HELP_CONTACTED
        ]
        is_yes_as_safe = user_msg_lower == "yes" and is_safety_question_context
        
        # Combine them: user is safe if they use an explicit phrase OR say "yes" to a safety question.
        is_explicit_safety_confirmation = is_explicit_safety_phrase or is_yes_as_safe

        # 3. Check for explicit danger phrases.
        IMMEDIATE_DANGER_PHRASES = [
            "i'm not safe", "i am not safe", "no i'm not safe", "not safe", "i'm not safe now", "i'm not okay", "i am not okay",
            "i'm alone", "i am alone", "always alone", "this is my last message", "last message", "last messgase",
            "i can't do this anymore", "i give up", "i want to die", "i want to end my life", "i'm going to hurt myself",
            "i'm going to kill myself", "i don't want to live", "there's no point", "no point in living", "i wish i was dead",
            "i just want it to end", "i can't go on", "i'm done", "i'm giving up", "i'm so tired of fighting",
            "i'm in so much pain", "i can't take it anymore", "i need to escape", "i'm a burden",
            "everyone would be better off without me", "i don't belong here", "i feel trapped", "i have no hope",
            "i'm worthless", "i'm a failure", "i'm ready to go", "i'm ready to leave", "i'm ready to check out",
            "i'm planning to", "i have a plan", "i'm thinking about how to", "i'm going to do it", "i will do it",
            "i'm serious", "this isn't a joke", "i'm not kidding", "i'm not playing", "i'm not well", "i'm not okay",
            "i'm not good", "i'm not feeling good", "i'm not feeling well", "i'm not feeling okay", "i'm not feeling alright",
            "i'm not feeling right", "i'm not feeling myself", "i'm not feeling like myself", "goodbye", "good bye", "goodby",
            "i can't go on", "no point", "end it all"
        ]
        is_explicit_danger_phrase = any(phrase in user_msg_lower for phrase in IMMEDIATE_DANGER_PHRASES)

        # 4. Determine if "yes" means danger (asked "Are you in danger?") or "no" means danger (asked "Are you safe?").
        is_yes_as_danger = user_msg_lower == "yes" and current_crisis_status == CRISIS_STATUS_HELP_SHOWN
        is_no_as_danger = user_msg_lower == "no" and is_safety_question_context

        # Combine them: user is in danger if they use a danger phrase OR say "yes" to danger question OR "no" to safety question.
        is_immediate_danger = is_explicit_danger_phrase or is_yes_as_danger or is_no_as_danger
        
        # --- INTENT-FIRST HANDLING ---
        # These checks have priority over generic state-based responses.

        # PRIORITY 0.1: Handle explicit request for emergency contacts
        if intent_data.get("intent") == "CRISIS_EMERGENCY_CONTACT_REQUEST":
            crisis_state["status"] = CRISIS_STATUS_EMERGENCY_CONTACT_INFO_PROVIDED
            session_state["crisis_state"] = crisis_state
            message = get_next_flow_step("crisis_support", 2) # Use the dedicated emergency contact message
            return message, session_state, True, None

        # PRIORITY 0.2: Handle explicit safety confirmation
        if is_explicit_safety_confirmation:
            # If a booking was pending, resolving the crisis will automatically
            # re-process that intent on the next turn. We can give a more contextual reply.
            if crisis_state.get("pending_normal_intent"):
                reply = "Thank you for confirming. I'm glad you're safe. We can now continue with finding an expert for you."
            else:
                # If no intent was pending, we proactively offer to start the process.
                reply = "I'm glad you're feeling safer. If you'd like, we can now help you connect with a mental-health professional. Would you like me to suggest an expert?"
                session_state["awaiting_expert_confirmation"] = True # Set the flag here

            session_state["crisis_state"]["status"] = CRISIS_STATUS_RESOLVED # Mark as resolved
            session_state["active_flow"] = None # Exit the crisis flow
            # The top-level CRISIS_RESOLUTION_CHECK will handle clearing the state
            # and processing any pending intents on the *next* message.
            return reply, session_state, True, None

        # PRIORITY 0.3: Handle immediate danger signals (escalation)
        if is_immediate_danger and current_crisis_status != CRISIS_STATUS_IMMEDIATE_DANGER:
            crisis_state["status"] = CRISIS_STATUS_IMMEDIATE_DANGER
            session_state["crisis_state"] = crisis_state
            message_template = get_next_flow_step("crisis_support", 5)
            message = message_template.replace("{user_name}", user_name_for_flow) if message_template else (f"{user_name_for_flow}, I'm very concerned because you said you're not safe and you're alone. Please don't stay alone right now. "
                           "Move to a place where other people are present and contact emergency support immediately. "
                           "If you can, call someone you trust and ask them to stay with you. Please do not hurt yourself while you're getting help.")
            return message, session_state, True, None

        # PRIORITY 0.4: Handle "help unavailable"
        unavailable_keywords = ["not available", "isn't available", "not working", "unavailable"]
        if any(keyword in user_msg_lower for keyword in unavailable_keywords):
            crisis_state["status"] = CRISIS_STATUS_HELP_UNAVAILABLE
            session_state["crisis_state"] = crisis_state
            message = get_next_flow_step("crisis_support", 3)
            return message, session_state, True, None

        # PRIORITY 0.5: Intercept normal booking intents during crisis
        # This is the key change to prevent repeating crisis messages when user tries to pivot.
        is_normal_booking_intent = intent_data.get("intent") in ["Doctor Booking", "Therapist Booking"]
        if is_normal_booking_intent and current_crisis_status in [CRISIS_STATUS_DETECTED, CRISIS_STATUS_HELP_SHOWN, CRISIS_STATUS_HELP_UNAVAILABLE, CRISIS_STATUS_HELP_CONTACTED, CRISIS_STATUS_SAFETY_CHECK]:
            # If a normal intent is detected while in an active crisis state (but not immediate danger)
            # Transition to PENDING_RESOLUTION and ask for safety.
            crisis_state["status"] = CRISIS_STATUS_PENDING_RESOLUTION
            crisis_state["pending_normal_intent"] = intent_data.get("intent") # Store the original intent
            crisis_state["pending_user_preferences"] = intent_data.get("user_preferences", {}) # Store preferences
            session_state["crisis_state"] = crisis_state
            print(f"DEBUG: Intercepted normal intent '{intent_data.get('intent')}' during crisis (status: {current_crisis_status}). Asking for safety.")
            return "I can help you connect with an expert. Before we continue, I need to check one thing: are you safe right now?", session_state, True, None

        # PRIORITY 0.6: Handle "help contacted"
        contacted_keywords = ["i contacted", "i've contacted", "contacted help", "i called", "i'm talking to", "i reached out"]
        if any(keyword in user_msg_lower for keyword in contacted_keywords):
            crisis_state["status"] = CRISIS_STATUS_HELP_CONTACTED
            session_state["crisis_state"] = crisis_state
            message = get_next_flow_step("crisis_support", 4)
            if message:
                message = message.replace("{user_name}", user_name_for_flow)
            else:
                # Fallback message if the flow step is missing
                message = f"I'm so glad you reached out for help, {user_name_for_flow}. Please stay with the person or support service you've contacted. Are you safe right now?"
            return message, session_state, True, None

        # --- STATE-BASED FALLBACKS for generic messages ---
        # These run if no specific intent was detected above.

        # If in immediate danger, and user says something generic, transition to safety check. Otherwise, repeat danger msg.
        if current_crisis_status == CRISIS_STATUS_IMMEDIATE_DANGER:
            if is_continuation:
                crisis_state["status"] = CRISIS_STATUS_SAFETY_CHECK
                session_state["crisis_state"] = crisis_state
                return "I'm still here with you. Your safety is the most important thing. Are you safe right now?", session_state, True, None
            else:
                # Repeat the immediate danger message (ensure message is assigned)
                message = get_next_flow_step("crisis_support", 5).replace("{user_name}", user_name_for_flow)
                return message, session_state, True, None

        # If user tried to book an expert, we are waiting for a safety confirmation.
        if current_crisis_status == CRISIS_STATUS_PENDING_RESOLUTION:
            return "Your safety is my top priority. I need to confirm you are safe before we can move on. Are you safe right now?", session_state, True, pending_intent_to_process

        if current_crisis_status == CRISIS_STATUS_SAFETY_CHECK:
            # If user says "yes" (caught by is_explicit_safety_confirmation above), it resolves.
            # If user says "no" (caught by is_immediate_danger above), it escalates.
            # If user says something else, re-ask for safety.
            # This is the persistent message for safety check.
            if not is_explicit_safety_confirmation and not is_immediate_danger:
                # Provide more context if the user gives an unclear answer like "what" or "no need".
                return "I'm asking because your safety is my highest priority. Before we continue, I need to make sure you are not in immediate danger. Are you safe right now?", session_state, True, pending_intent_to_process
        
        if current_crisis_status == CRISIS_STATUS_HELP_UNAVAILABLE and is_continuation:
            crisis_state["status"] = CRISIS_STATUS_SAFETY_CHECK
            session_state["crisis_state"] = crisis_state
            return "You're welcome. I'm glad you told me what happened. Are you safe right now?", session_state, True, None

        if current_crisis_status == CRISIS_STATUS_HELP_CONTACTED and is_continuation: # Ensure message is assigned
            crisis_state["status"] = CRISIS_STATUS_SAFETY_CHECK
            session_state["crisis_state"] = crisis_state
            return "I'm glad you reached out. Are you safe right now?", session_state, True, None

        if current_crisis_status == CRISIS_STATUS_EMERGENCY_CONTACT_INFO_PROVIDED:
            if is_continuation: # User acknowledged the info, now ask for safety
                crisis_state["status"] = CRISIS_STATUS_SAFETY_CHECK
                session_state["crisis_state"] = crisis_state
                return "Thank you. Are you safe right now?", session_state, True, None
            # If not a continuation, and not a safety confirmation, re-iterate and ask for safety (ensure message is assigned)
            return get_next_flow_step("crisis_support", 2), session_state, True, None # Repeat the emergency info

        if current_crisis_status == CRISIS_STATUS_HELP_SHOWN:
            if is_continuation:
                crisis_state["status"] = CRISIS_STATUS_SAFETY_CHECK # Move to safety check after initial ack
                session_state["crisis_state"] = crisis_state
                return "Thank you for acknowledging. Your safety is the most important thing. Are you safe right now?", session_state, True, None # Ensure message is assigned
            else: # If user says something else, repeat the persistent short message
                return get_next_flow_step("crisis_support", 1), session_state, True, None

        # Final fallback for any unhandled crisis state
        return get_next_flow_step("crisis_support", 1), session_state, True, None

    # --- END CRISIS HANDLING ---
    # 0. Identify Continuations and Stops early
    # Negative Feedback Detection (No improvement after exercise)
    negative_feedback = ["no change", "no changes", "still stressed", "not working", "didn't help", "no better", "still feel", "no difference"]
    has_negative_feedback = any(f in user_msg_lower for f in negative_feedback)
    is_stop = any(word in user_msg_lower for word in ["stop", "cancel", "exit", "quit", "no more", "nevermind", "end this", "don't want to"])

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
        session_state["current_step"] = 0 # Reset current step for the flow
        return "Of course. We can stop here. What would you like to do instead?", session_state, True, None

    # 3. Assessment Logic
    active_assessment = session_state.get("active_assessment")
    if active_assessment:
        current_step = session_state.get("assessment_step", 0)
        total_score = session_state.get("assessment_score", 0)
        assessment_answers = session_state.get("assessment_answers", [])
        
        # Try to parse numeric (0-3) or letter (A-D) answer
        match = re.search(r"\b([0-3a-dA-D])\b", user_msg_lower)
        if match:
            raw_answer = match.group(1).upper() # Ensure raw_answer is uppercase for 'A'-'D'
            
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
                return escalation_message, session_state, True, None

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
                
                # Special empathy touches for onboarding (after Q4, before Q5)
                if active_assessment == "onboarding":
                    if current_step == 4: # After Q4, before Q5
                        next_question = "Thanks for being honest. Almost done.\n\n" + next_question
                
                return next_question, session_state, True, pending_intent_to_process
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
                
                return reply, session_state, True, pending_intent_to_process
        else:
            valid_range = "A to D" if active_assessment == "onboarding" else "0 to 3"
            return f"Please provide an answer from {valid_range} so I can calculate my result accurately.", session_state, True, pending_intent_to_process
    elif user_msg_lower == "media_finished": # 4. Media Session Follow-up
        session_state["media_session_active"] = False
        return "Welcome back. How are you feeling now?", session_state, True, pending_intent_to_process # This was already here.

    # --- NEW PRIORITY 0.5: ACTIVE WELLNESS FLOW CONTINUATION ---
    # This block handles the continuation of interactive wellness flows (not booking or assessment, which are handled above).
    if active_flow and active_flow not in ["therapist_booking", "doctor_booking"]: # Ensure it's not a booking flow
        # Rule: If it's an interactive flow, ANY non-greeting/stop input progresses it.
        # EXCEPTION: For interactive flows, a simple "ok" or "yes" should NOT advance the step
        # unless it was the activation message (just_activated).
        is_interactive = active_flow in INTERACTIVE_FLOWS
        just_activated = False # This flag is no longer set, but the logic below is still valid.
        is_simple_confirmation = user_msg_lower in ["ok", "okay", "yes", "yeah", "sure", "yep", "yup", "ready"]
        
        if is_interactive and is_simple_confirmation and not just_activated:
            # Re-send the current step instructions instead of advancing
            return get_next_flow_step(active_flow, current_step - 1 if current_step > 0 else 0), session_state, True, pending_intent_to_process

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
            ), session_state, True, pending_intent_to_process

        if not is_continuation and not is_interactive:
            # User is likely trying to pivot or chat
            session_state["active_flow"] = None
            session_state["current_step"] = 0
            return None, session_state, False, pending_intent_to_process

        next_text = get_next_flow_step(active_flow, current_step)
        if next_text:
            session_state["current_step"] = current_step + 1
            session_state["last_exercise"] = active_flow # Track the last exercise
            return next_text, session_state, True, None
        else:
            # Flow finished
            completed = session_state.get("completed_exercises", [])
            if active_flow not in completed:
                completed.append(active_flow)
            session_state["completed_exercises"] = completed
            
            session_state["active_flow"] = None
            session_state["current_step"] = 0
            session_state["media_session_active"] = False 
            return None, session_state, False, pending_intent_to_process # Flow finished, let AI take over

    return None, session_state, False, pending_intent_to_process # Default return for handle_flow_logic

    return None, session_state, False, pending_intent_to_process # Default return for handle_flow_logic
