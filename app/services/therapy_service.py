import random

# Therapeutic Activity Engine - Standardized for ZuraAI
ACTIVITIES = {
    "stress": [
        {"id": "stress_relief", "label": "Stress Relief", "type": "FLOW", "description": "A quick way to calm your mind."},
        {"id": "breathing", "label": "Breathing Exercise", "type": "FLOW", "description": "A mindful minute to find your center."},
        {"id": "box_breathing", "label": "Box Breathing", "type": "FLOW", "description": "reset your nervous system with a square breath."},
        {"id": "grounding", "label": "Grounding Activity", "type": "FLOW", "description": "Reconnect with the present moment."},
        {"id": "calming_audio", "label": "Calm Audio", "type": "MEDIA", "description": "Soothing sounds for a busy mind."}
    ],
    "sadness": [
        {"id": "journaling", "label": "Guided Journal", "type": "FEATURE", "description": "Putting feelings into words can help."},
        {"id": "gratitude", "label": "Gratitude Reflection", "type": "FEATURE", "description": "Finding small anchors of light."},
        {"id": "thought_reframing", "label": "Thought Reframing", "type": "FLOW", "description": "Look at things from a kinder angle."},
        {"id": "reflection", "label": "Emotional Reflection", "type": "FLOW", "description": "A gentle space to sit with your feelings."}
    ],
    "anxiety": [
        {"id": "478_breathing", "label": "4-7-8 Breathing", "type": "FLOW", "description": "A natural tranquilizer for the nervous system."},
        {"id": "grounding", "label": "5-4-3-2-1 Grounding", "type": "FLOW", "description": "Bring your focus back to the 'now'."},
        {"id": "tension_release", "label": "Tension Release", "type": "FLOW", "description": "Release physical stress from your body."},
        {"id": "panic_relief", "label": "Panic Relief", "type": "MEDIA", "description": "Immediate support for intense moments."}
    ],
    "burnout": [
        {"id": "body_scan", "label": "Body Scan", "type": "FLOW", "description": "Identify and release tension in your body."},
        {"id": "rest_audit", "label": "Rest Audit", "type": "FEATURE", "description": "Identify what kind of rest you need."},
        {"id": "stillness", "label": "Moment of Stillness", "type": "FLOW", "description": "Permission to just 'be' for a minute."},
        {"id": "calming_audio", "label": "Nature Sounds", "type": "MEDIA", "description": "Escape to a peaceful digital landscape."}
    ],
    "loneliness": [
        {"id": "gratitude", "label": "Gratitude Practice", "type": "FEATURE", "description": "Connecting with what matters to you."},
        {"id": "self_esteem", "label": "Self-Esteem Boost", "type": "FLOW", "description": "A gentle reminder of your worth."},
        {"id": "talking", "label": "Heart-to-Heart", "type": "FLOW", "description": "I'm right here to listen."},
        {"id": "check_in", "label": "Self-Compassion", "type": "FEATURE", "description": "A kind check-in with yourself."}
    ],
    "hopelessness": [
        {"id": "anchor", "label": "Small Anchor", "type": "FEATURE", "description": "Finding one tiny thing to hold onto."},
        {"id": "thought_reframing", "label": "Positive Reframing", "type": "FLOW", "description": "Shifting towards a gentler perspective."},
        {"id": "professional_help", "label": "Expert Support", "type": "FEATURE", "description": "Connect with someone who can help."},
        {"id": "breathing", "label": "Calm Breath", "type": "FLOW", "description": "Focusing on the very next breath."}
    ],
    "sleep": [
        {"id": "sleep_stories", "label": "Sleep Stories", "type": "MEDIA", "description": "Drift off with a soothing tale."},
        {"id": "sleep_meditation", "label": "Sleep Meditation", "type": "MEDIA", "description": "Calm your mind for a restful night."},
        {"id": "body_scan", "label": "Body Scan for Sleep", "type": "FLOW", "description": "Gently release tension before bed."},
        {"id": "relaxation_audio", "label": "Relaxation Audio", "type": "MEDIA", "description": "Pure sounds for deep rest."}
    ]
}

RECOMMENDATION_PROMPTS = {
    "stress": "It sounds like your mind has been carrying a lot. We can try a small grounding exercise together if you'd like. Sometimes it helps bring a little calm back into the moment.",
    "sadness": "Sometimes putting feelings into words can help a little. Would you like to try a short guided journal activity together?",
    "anxiety": "I'm right here with you. Let's try to find a little steadiness together. Would a grounding exercise or some slow breathing feel helpful right now?",
    "panic": "I'm right here. Let’s slow things down together for a moment. Would you like to try a calming exercise with me?",
    "loneliness": "I'm here, and I'm listening. Sometimes focusing on a small positive reflection can make things feel a little less heavy. Would you like to try that?",
    "anger": "I hear that you're feeling angry. Sometimes our bodies hold onto that tension. Would you like to try a quick exercise to release some of that physical stress?",
    "sleep": "Getting good rest is so important. Would you like to try a sleep story, some calming audio, or a gentle body scan to help you drift off?",
    "neutral": "I'm here to support you. Would you like to try a wellness activity together, or just chat for a bit?"
}

WELLNESS_FLOWS = {
    "breathing": [
        "Okay. Let's find a comfortable position. Slowly breathe in through your nose, hold for a second, and exhale slowly through your mouth, letting your shoulders drop.",
        "Good. Let's do that again. Inhale deeply, release all that tension as you exhale, and repeat this cycle 3 times at your own pace.",
        "Take your time. I'll stay right here with you.",
        "Great job taking that moment for yourself. How are you feeling now compared to before we started?"
    ],
    "stress_relief": [
        "I'm here with you. Let's try a quick stress-relief exercise together. Take a slow breath in through your nose for 4 seconds, hold for 2 seconds, and then breathe out gently for 6 seconds.",
        "Repeat this three times at your own pace, and let me know when you're done.",
        "Great job taking that moment for yourself. How are you feeling now compared to before we started?"
    ],
    "compact_breathing": [
        "Let’s slow things down together. Take a deep breath in, hold it softly for a second, and slowly breathe out. Repeat this gently 3 times at your own pace.",
        "Take your time. I’ll stay right here while you try it.",
        "Great job taking that moment for yourself. How are you feeling now compared to before we started?"
    ],
    "box_breathing": [
        "Box breathing is a great way to reset your nervous system. Let's try one round together:\n\n• Breathe in for 4 seconds\n• Hold for 4 seconds\n• Breathe out for 4 seconds\n• Hold for 4 seconds",
        "Repeat this cycle 3 times at your own pace, then let me know how you're feeling.",
        "Great job taking that moment for yourself. How are you feeling now compared to before we started?"
    ],
    "478_breathing": [
        "The 4-7-8 technique is like a natural tranquilizer for the nervous system. Here's how to do it:\n\n• Inhale quietly through your nose for 4 seconds.\n• Hold your breath for 7 seconds.\n• Exhale completely through your mouth with a 'whoosh' sound for 8 seconds.",
        "Try repeating this cycle 3 times at your own pace. I'm right here with you.",
        "Great job taking that moment for yourself. How are you feeling now compared to before we started?"
    ],
    "grounding": [
        "Let's try the 5-4-3-2-1 grounding technique to bring you back to the present. First, can you name 5 things you see right now?",
        "Good. Now, name 4 things you can touch or feel (like the chair or your clothes).",
        "Next, what are 3 things you hear and 2 things you can smell right now?",
        "Finally, name 1 thing you can taste, or your favorite thing to taste.",
        "Take a slow, deep breath. Notice the weight of your body where you're sitting. You're here, and you're safe. How are you feeling now compared to before we started?"
    ],
    "thought_reframing": [
        "I hear how heavy that thought feels. Let's try to look at it from a different angle. What's the main thought on your mind?",
        "I see. Now, if you were your own best friend, what would you say to yourself about this?",
        "That's a much more compassionate view. Try repeating that to yourself: 'It's okay to feel this way, and I'm doing my best.'",
        "How does it feel to hold that kinder thought? Does things feel even slightly lighter now?"
    ],
    "body_scan": [
        "Let's do a quick body scan to release any hidden tension. Close your eyes if you're comfortable.",
        "Starting from your toes, slowly move your attention up through your legs, stomach, and chest, letting each part soften and relax.",
        "Now, drop your shoulders away from your ears and relax your jaw and eyes. Take one last deep breath and feel the relaxation spreading through your whole body.",
        "Take a moment to sit with this feeling. How are you feeling now compared to before we started?"
    ],
    "tension_release": [
        "I hear you. Sometimes our bodies hold onto physical tension when we're feeling a lot. Let's help your body release some of that. Gently shrug your shoulders up toward your ears, hold for 3 seconds, and then let them drop completely. Repeat this three times at your own pace.",
        "Now, let's try one more: squeeze your fists as tight as you can for 3 seconds, then let them go completely and notice the relaxation spreading through your hands.",
        "Take a slow, deep breath. How are you feeling now compared to before we started?"
    ],
    "relaxation_practice": [
        "Let's practice some deep relaxation. Find a comfortable position and close your eyes.",
        "Take a slow, deep breath in and imagine a wave of calm slowly washing down from the top of your head to your toes, softening every muscle as it passes.",
        "Stay with this feeling of calm for a few more breaths. You are safe, and you are at peace.",
        "Whenever you're ready, you can gently open your eyes. How are you feeling now compared to before we started?"
    ],
    "self_esteem": [
        "You've been through a lot lately, and it's okay to feel tired. Can you think of one small thing you did today that you're proud of?",
        "That's wonderful. Even small things count. You're showing up for yourself, and that matters.",
        "Take a moment to acknowledge your strength. You are enough, just as you are. How does it feel to give yourself that credit?",
        "I'm glad we could take this moment. How are you feeling now compared to before we started?"
    ], # 0
    "crisis_support": [
        # Step 0: Immediate, direct escalation. This is sent upon detection and if the user asks for an "expert".
        "{user_name}, I’m really concerned about your safety. Since you’ve told me you want to end your life, please use Mibo’s Crisis Help option now to connect with immediate support.\n\n🆘 Crisis Help — 24/7\nPlease open the Mibo homepage → Crisis Help (24/7) and contact the available crisis-support service.\n\nIf you feel you may hurt yourself right now, do not stay alone. Go to the nearest emergency department or contact local emergency services, and stay with someone you trust.\n\nYou don't need to go through the normal expert-selection questions right now. This is an emergency-support situation.",
        
        # Step 1: Persistent supportive loop. Any other message gets this supportive reminder.
        "I'm still here with you. Your safety is the most important thing. Please use the Mibo Crisis Help (24/7) option on the homepage or seek emergency help. You don't have to go through this alone.",

        # Step 2: Response when user asks for an expert while in crisis.
        "Yes. Mibo provides Crisis Help with 24/7 support. Since you’ve told me you want to end your life, please use Mibo’s Crisis Help option now to connect with immediate support.\n\n🆘 Crisis Help — 24/7\nPlease open the Mibo homepage → Crisis Help (24/7) and contact the available crisis-support service.\n\nIf you feel you may hurt yourself right now, do not stay alone. Go to the nearest emergency department or contact local emergency services, and stay with someone you trust.\n\nYou don't need to go through the normal expert-selection questions right now. This is an emergency-support situation."
    ],
}

SUPPORTIVE_PHRASES = {
    "positive_reinforcement": [
        "That was a good step.",
        "I’m glad you stayed with it.",
        "Even small pauses like this can help.",
        "You handled that gently.",
        "That’s a positive step.",
        "You did really well.",
        "I'm proud of you for taking this moment."
    ],
    "acknowledgment": [
        "I hear you.",
        "I’m right here with you.",
        "It’s okay to feel this way.",
        "Thank you for sharing that with me.",
        "I’m listening."
    ],
    "relief": [
        "I’m glad things feel a little lighter right now.",
        "That’s good to hear. Take that feeling with you.",
        "I'm happy you're feeling a bit better.",
        "It sounds like a small weight has been lifted."
    ]
}

def get_random_support(category: str):
    return random.choice(SUPPORTIVE_PHRASES.get(category, ["I'm here for you."]))

def get_next_flow_step(flow_name: str, current_step: int):
    flow = WELLNESS_FLOWS.get(flow_name)
    if not flow or current_step >= len(flow):
        return None
    return flow[current_step]

def get_therapeutic_recommendation(emotion: str):
    emotion = emotion.lower()
    activities = ACTIVITIES.get(emotion, [
        {"id": "breathing", "label": "Gentle Breathing", "type": "FLOW", "description": "A quick pause for your breath."},
        {"id": "journaling", "label": "Daily Journal", "type": "FEATURE", "description": "Reflect on your day."}
    ])
    
    prompt = RECOMMENDATION_PROMPTS.get(emotion, RECOMMENDATION_PROMPTS["neutral"])
    
    return {
        "prompt": prompt,
        "activities": activities
    }
