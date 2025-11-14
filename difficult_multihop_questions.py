#!/usr/bin/env python3
"""
Collection of difficult multi-hop questions for testing.

These questions are based on standard multi-hop QA benchmarks:
- HotpotQA (bridge-entity, comparison questions)
- 2WikiMultihopQA (compositional questions)
- MuSiQue (multi-step reasoning)
"""

DIFFICULT_QUESTIONS = [
    # Bridge-entity questions (2-hop)
    {
        "question": "What college did the President who attended Minneapolis High School go to?",
        "answer": "University of Minnesota",
        "reasoning_type": "bridge-entity",
        "hops": 2,
        "intermediate_entity": "Hubert Humphrey",
        "difficulty": "hard",
        "path": "Minneapolis High School → Hubert Humphrey → University of Minnesota"
    },
    {
        "question": "What year was the director of Titanic born?",
        "answer": "1954",
        "reasoning_type": "bridge-entity",
        "hops": 2,
        "intermediate_entity": "James Cameron",
        "difficulty": "medium",
        "path": "Titanic → James Cameron → born 1954"
    },
    {
        "question": "In what city was the singer of 'Thriller' born?",
        "answer": "Gary, Indiana",
        "reasoning_type": "bridge-entity",
        "hops": 2,
        "intermediate_entity": "Michael Jackson",
        "difficulty": "medium",
        "path": "Thriller → Michael Jackson → Gary, Indiana"
    },
    {
        "question": "What is the population of the capital of France?",
        "answer": "2.2 million (city proper)",
        "reasoning_type": "bridge-entity",
        "hops": 2,
        "intermediate_entity": "Paris",
        "difficulty": "easy",
        "path": "France → Paris (capital) → population"
    },
    {
        "question": "When did the team that led by Giuseppe Marotta win the champions league?",
        "answer": "1996",
        "reasoning_type": "bridge-entity",
        "hops": 2,
        "intermediate_entity": "Juventus",
        "difficulty": "hard",
        "path": "Giuseppe Marotta → Juventus → 1996 Champions League"
    },

    # Compositional questions (intersection/conjunction)
    {
        "question": "Which country has Mohamed Morsi in a government post and is the location of the Giza Pyramids?",
        "answer": "Egypt",
        "reasoning_type": "compositional-intersection",
        "hops": 2,
        "difficulty": "hard",
        "path": "Mohamed Morsi → Egypt ∩ Giza Pyramids → Egypt"
    },
    {
        "question": "The country that contains Balochistan, Pakistan had what President in 1980?",
        "answer": "Muhammad Zia-ul-Haq",
        "reasoning_type": "compositional-bridge",
        "hops": 2,
        "intermediate_entity": "Pakistan",
        "difficulty": "hard",
        "path": "Balochistan → Pakistan → President in 1980"
    },
    {
        "question": "Which country whose religious organization is led by the Ukrainian Orthodox Church of the Kyivan Patriarchate borders Slovakia?",
        "answer": "Ukraine",
        "reasoning_type": "compositional-intersection",
        "hops": 2,
        "difficulty": "very_hard",
        "path": "Ukrainian Orthodox Church → Ukraine ∩ borders Slovakia → Ukraine"
    },

    # Comparison questions (2-hop + comparison)
    {
        "question": "Are there more people in the capital of China or the capital of India?",
        "answer": "Beijing (China's capital) has more people",
        "reasoning_type": "comparison",
        "hops": 3,
        "intermediate_entities": ["Beijing", "New Delhi"],
        "difficulty": "hard",
        "path": "China → Beijing, India → New Delhi → compare populations"
    },
    {
        "question": "Which has more members, the band that wrote 'Hey Jude' or the band that wrote 'Bohemian Rhapsody'?",
        "answer": "The Beatles (4 members) vs Queen (4 members) - tie",
        "reasoning_type": "comparison",
        "hops": 3,
        "intermediate_entities": ["The Beatles", "Queen"],
        "difficulty": "medium",
        "path": "'Hey Jude' → The Beatles, 'Bohemian Rhapsody' → Queen → compare"
    },

    # Temporal/event-based questions
    {
        "question": "What year did the author of 'Harry Potter' publish the first book?",
        "answer": "1997",
        "reasoning_type": "bridge-entity",
        "hops": 2,
        "intermediate_entity": "J.K. Rowling",
        "difficulty": "medium",
        "path": "Harry Potter → J.K. Rowling → published 1997"
    },
    {
        "question": "In what decade was the inventor of the telephone born?",
        "answer": "1840s",
        "reasoning_type": "bridge-entity",
        "hops": 2,
        "intermediate_entity": "Alexander Graham Bell",
        "difficulty": "medium",
        "path": "telephone → Alexander Graham Bell → born 1847"
    },

    # Complex compositional (3+ hops)
    {
        "question": "What language is spoken in the country where the inventor of pizza was born?",
        "answer": "Italian",
        "reasoning_type": "bridge-entity-chain",
        "hops": 3,
        "intermediate_entities": ["Raffaele Esposito", "Italy"],
        "difficulty": "hard",
        "path": "pizza inventor → Raffaele Esposito → Italy → Italian language"
    },
    {
        "question": "What is the birth year of the spouse of the first female Prime Minister of the United Kingdom?",
        "answer": "1915",
        "reasoning_type": "bridge-entity-chain",
        "hops": 3,
        "intermediate_entities": ["Margaret Thatcher", "Denis Thatcher"],
        "difficulty": "very_hard",
        "path": "First female PM UK → Margaret Thatcher → Denis Thatcher → born 1915"
    },

    # Property-based questions (requires specific Wikidata properties)
    {
        "question": "What university did the 44th President of the United States attend?",
        "answer": "Columbia University and Harvard Law School",
        "reasoning_type": "bridge-entity",
        "hops": 2,
        "intermediate_entity": "Barack Obama",
        "difficulty": "medium",
        "path": "44th President → Barack Obama → educated at Columbia/Harvard",
        "requires_properties": ["P69 (educated at)"]
    },
    {
        "question": "What is the official language of the country where the Taj Mahal is located?",
        "answer": "Hindi and English",
        "reasoning_type": "bridge-entity",
        "hops": 2,
        "intermediate_entity": "India",
        "difficulty": "medium",
        "path": "Taj Mahal → India → official languages",
        "requires_properties": ["P17 (country)", "P37 (official language)"]
    }
]


# Additional questions by difficulty level
EASY_QUESTIONS = [q for q in DIFFICULT_QUESTIONS if q["difficulty"] == "easy"]
MEDIUM_QUESTIONS = [q for q in DIFFICULT_QUESTIONS if q["difficulty"] == "medium"]
HARD_QUESTIONS = [q for q in DIFFICULT_QUESTIONS if q["difficulty"] in ["hard", "very_hard"]]

# Questions requiring specific Wikidata properties
EDUCATIONAL_QUESTIONS = [
    q for q in DIFFICULT_QUESTIONS
    if "requires_properties" in q and any("P69" in p for p in q.get("requires_properties", []))
]


def get_questions_by_type(reasoning_type=None, difficulty=None, min_hops=None):
    """Filter questions by criteria."""
    questions = DIFFICULT_QUESTIONS

    if reasoning_type:
        questions = [q for q in questions if q["reasoning_type"] == reasoning_type]

    if difficulty:
        questions = [q for q in questions if q["difficulty"] == difficulty]

    if min_hops:
        questions = [q for q in questions if q["hops"] >= min_hops]

    return questions


if __name__ == "__main__":
    print("="*80)
    print("DIFFICULT MULTI-HOP QUESTIONS TEST SET")
    print("="*80)
    print(f"\nTotal questions: {len(DIFFICULT_QUESTIONS)}")
    print(f"  - Easy: {len(EASY_QUESTIONS)}")
    print(f"  - Medium: {len(MEDIUM_QUESTIONS)}")
    print(f"  - Hard/Very Hard: {len(HARD_QUESTIONS)}")
    print(f"  - Requiring educational properties: {len(EDUCATIONAL_QUESTIONS)}")

    print("\n" + "="*80)
    print("SAMPLE QUESTIONS BY TYPE")
    print("="*80)

    for reasoning_type in ["bridge-entity", "compositional-intersection", "comparison"]:
        questions = get_questions_by_type(reasoning_type=reasoning_type)
        if questions:
            print(f"\n{reasoning_type.upper()}:")
            q = questions[0]
            print(f"  Q: {q['question']}")
            print(f"  A: {q['answer']}")
            print(f"  Path: {q['path']}")
