"""
Mibo Knowledge Base

This file serves as a structured, in-memory database for Mibo's ecosystem.
It includes information about experts, locations, and services. In a production
environment, this data would ideally be fetched from a dedicated database or API.
"""

LOCATIONS = ["Bengaluru", "Kochi", "Mumbai"]

SERVICES = ["In-Patient", "In-Person", "Online"]

LANGUAGES = ["English", "Malayalam", "Hindi", "Tamil", "Kannada"]

EXPERTS = [
    {
        "id": "abhinand_ps",
        "name": "Abhinand P S",
        "role": "Clinical Psychologist",
        "experience": "2+ years",
        "city": "Bengaluru",
        "languages": ["English", "Malayalam"],
        "specializations": [
            "Anxiety",
            "Depression",
            "Stress",
            "Relationship Issues",
            "Trauma",
            "Cognitive Behaviour Therapy (CBT)",
            "Psychodynamic therapy",
            "Supportive therapy"
        ],
        "consultation_types": ["In-person", "Online"],
        "fee": 2200,
        "qualification": "M.Sc, M.Phil",
        "target_group": ["Adults"]
    },
    {
        "id": "ajay_siby",
        "name": "Ajay Siby",
        "role": "Clinical Psychologist",
        "experience": "2+ years",
        "city": "Bengaluru",
        "languages": ["English", "Hindi", "Malayalam"],
        "specializations": [
            "Adolescent Counseling",
            "Behaviour modification"
        ],
        "consultation_types": ["In-person", "Online"],
        "fee": 2000,
        "qualification": "M.Sc, M.Phil",
        "target_group": ["Adolescents", "Adults"]
    },
    {
        "id": "anet_augustine",
        "name": "Anet Augustine",
        "role": "Clinical Psychologist",
        "experience": "2+ years",
        "city": "Kochi",
        "languages": ["English", "Malayalam", "Hindi"],
        "specializations": [
            "Anxiety Disorders",
            "Psychosis",
            "Neurodivergent adult support",
            "Substance use disorders",
            "Psychological assessments",
            "Diagnostic evaluations",
            "Child Psychology",
            "Dialectical Behaviour Therapy (DBT)",
            "Acceptance and Commitment Therapy (ACT)",
            "Solution-Focused Brief Therapy (SFBT)"
        ],
        "consultation_types": ["In-person", "Online"],
        "fee": 2000,
        "qualification": "M.Sc, M.Phil",
        "target_group": ["Adults", "Children"]
    },
    {
        "id": "anu_sobha_jose",
        "name": "Dr. Anu Sobha Jose",
        "role": "Consultant Psychiatrist",
        "experience": "10+ years",
        "city": "Kochi",
        "languages": ["Malayalam", "English", "Hindi"],
        "specializations": [
            "Child and Adolescent Psychiatry",
            "De-addiction",
            "General Psychiatry",
            "Women's Mental Health"
        ],
        "consultation_types": ["In-person", "Online"],
        "fee": 1200,
        "qualification": "MBBS, DPM, PGDFM",
        "target_group": ["Adults", "Children", "Adolescents"]
    },
    {
        "id": "miller_am",
        "name": "Dr. Miller A M",
        "role": "Consultant Psychiatrist",
        "experience": "5+ years",
        "city": "Bengaluru",
        "languages": ["English", "Tamil", "Kannada", "Hindi"],
        "specializations": [
            "Emergency psychiatry",
            "Community mental health care",
            "Queer mental health",
            "Depression",
            "Anxiety",
            "Addiction",
            "Complex trauma",
            "Burnout"
        ],
        "consultation_types": ["In-person", "Online"],
        "fee": 3000,
        "qualification": "MBBS, MD",
        "target_group": ["Adults"]
    },
    {
        "id": "muhammed_sadik_tm",
        "name": "Dr. Muhammed Sadik TM",
        "role": "Clinical Psychologist",
        "experience": "10+ years",
        "city": "Kochi",
        "languages": ["Malayalam", "English", "Hindi", "Tamil"],
        "specializations": [
            "Self analysis",
            "Dream analysis",
            "Restructuring couple and family system",
            "Interpersonal dynamic",
            "Psychodynamic therapy",
            "Behavioural addictions"
        ],
        "consultation_types": ["In-person", "Online"],
        "fee": 3000,
        "qualification": "M.Sc, M.Phil, Ph.D.",
        "target_group": ["Adults", "Couples", "Family"]
    },
    {
        "id": "sangeetha_os",
        "name": "Dr. Sangeetha OS",
        "role": "Consultant Psychiatrist",
        "experience": "2+ years",
        "city": "Kochi",
        "languages": ["Malayalam", "English"],
        "specializations": [
            "Mood disorders",
            "Depression",
            "Obsessive–Compulsive Disorder (OCD)",
            "Trauma-related concerns",
            "Neurodevelopmental conditions",
            "Substance use disorders",
            "Psychotic disorders",
            "Anxiety Disorders",
            "Personality disorders",
            "Women psychiatry"
        ],
        "consultation_types": ["In-person", "Online"],
        "fee": 1500,
        "qualification": "MBBS, MD, MA",
        "target_group": ["Adults", "Adolescents", "Women"]
    },
    {
        "id": "srinivasa_reddy",
        "name": "Dr. Srinivasa Reddy",
        "role": "Psychiatrist",
        "experience": "15+ years",
        "city": "Bengaluru",
        "languages": ["English", "Telugu", "Kannada", "Hindi"],
        "specializations": [
            "Addiction Counseling",
            "General Psychiatry"
        ],
        "consultation_types": ["In-person", "Online"],
        "fee": 2000,
        "qualification": "MBBS, MRCPsych",
        "target_group": ["Adults"]
    },
    {
        "id": "jerry_p_mathew",
        "name": "Jerry P Mathew",
        "role": "Clinical Psychologist",
        "experience": "5+ years",
        "city": "Kochi",
        "languages": ["English", "Malayalam"],
        "specializations": [
            "Anxiety Disorders",
            "Depression",
            "Obsessive–Compulsive Disorder (OCD)",
            "Neurodivergent adult support",
            "Personality disorders",
            "Trauma & PTSD"
        ],
        "consultation_types": ["In-person", "Online"],
        "fee": 2300,
        "qualification": "M.Sc, M.Phil",
        "target_group": ["Adults"]
    },
    {
        "id": "yashaswini_rs",
        "name": "Ms. Yashaswini",
        "role": "Clinical Psychologist",
        "experience": "3+ years",
        "city": "Bengaluru",
        "languages": ["English", "Kannada"],
        "specializations": [
            "Cognitive Behaviour Therapy (CBT)",
            "Dialectical Behaviour Therapy (DBT)",
            "Mindfulness-based therapy",
            "Anxiety",
            "Depression",
            "Stress"
        ],
        "consultation_types": ["In-person", "Online"],
        "fee": 3000,
        "qualification": "M.Sc, M.Phil",
        "target_group": ["Adults"]
    },
    {
        "id": "naufal_ma",
        "name": "Naufal M. A",
        "role": "Clinical Psychologist",
        "experience": "2+ years",
        "city": "Bengaluru",
        "languages": ["English", "Malayalam"],
        "specializations": [
            "Cognitive Behaviour Therapy (CBT)",
            "Psychodynamic therapy",
            "Anxiety",
            "Depression",
            "Addiction",
            "Psychosis",
            "Couple Therapy"
        ],
        "consultation_types": ["In-person", "Online"],
        "fee": 2200,
        "qualification": "MA, M.Phil",
        "target_group": ["Adults", "Couples"]
    },
    {
        "id": "ria_mary_jojo",
        "name": "Ria Mary Jojo",
        "role": "Clinical Psychologist",
        "experience": "3+ years",
        "city": "Kochi",
        "languages": ["English", "Malayalam", "Hindi", "Tamil"],
        "specializations": [
            "Trauma-focused therapy (EMDR)",
            "Dialectical Behaviour Therapy (DBT)",
            "Behaviour modification",
            "Compassion-focused therapy",
            "Relationship Issues",
            "Anxiety Disorders",
            "Personality disorders",
            "Stress",
            "Mood-related challenges"
        ],
        "consultation_types": ["In-person", "Online"],
        "fee": 2000,
        "qualification": "M.Sc, M.Phil",
        "target_group": ["Adults", "Adolescents"]
    },
    {
        "id": "salini_rt",
        "name": "Salini R T",
        "role": "Clinical Psychologist",
        "experience": "2+ years",
        "city": "Kochi",
        "languages": ["English", "Malayalam", "Tamil"],
        "specializations": [
            "Psychodermatology",
            "Personality disorders",
            "Relationship Issues",
            "Stress Management",
            "Body image-related distress",
            "Anxiety",
            "Self-esteem difficulties"
        ],
        "consultation_types": ["In-person", "Online"],
        "fee": 2000,
        "qualification": "M.Sc, M.Phil",
        "target_group": ["Adults"]
    },
    {
        "id": "shifana_sidheeque_tk",
        "name": "Shifana Sidheeque T. K",
        "role": "Clinical Psychologist",
        "experience": "4+ years",
        "city": "Bengaluru",
        "languages": ["English", "Malayalam"],
        "specializations": [
            "Cognitive Behaviour Therapy (CBT)",
            "Dialectical Behaviour Therapy (DBT)",
            "Solution-Focused Brief Therapy (SFBT)",
            "Behaviour modification",
            "Stress",
            "Anxiety",
            "Depression",
            "Trauma",
            "Grief",
            "Relationship Issues",
            "Self-esteem"
        ],
        "consultation_types": ["In-person", "Online"],
        "fee": 3000,
        "qualification": "M.Sc, M.Phil",
        "target_group": ["Adults", "Couples", "Family"]
    }
]
