# intent_analyzer.py
"""
Intelligent intent analysis for graph expansion queries.
Recognizes semantic patterns in user questions to guide graph expansion strategy.
"""

from typing import Dict, List, Tuple, Optional
import re
from dataclasses import dataclass


@dataclass
class QueryIntent:
    """Structured representation of user query intent."""

    # Core entities mentioned in question
    entities: List[str]

    # Expansion depth requested (1-hop, 2-hop, etc.)
    expansion_depth: int

    # Types of relations to explore
    relation_types: List[str]

    # Whether user wants comprehensive expansion
    comprehensive: bool

    # Focus areas (biographical, temporal, spatial, etc.)
    focus_areas: List[str]

    # Original question
    original_question: str


def analyze_expansion_intent(question: str, triples: List[Dict]) -> QueryIntent:
    """
    Analyze user question to determine graph expansion strategy.

    Args:
        question: User's input question
        triples: Extracted triples from relation extraction

    Returns:
        QueryIntent with expansion parameters
    """
    question_lower = question.lower()

    # Extract entities from triples
    entities = []
    for t in triples:
        entities.extend([t["head"], t["tail"]])
    entities = list(set(entities))

    # 1. Detect expansion depth
    expansion_depth = _detect_expansion_depth(question_lower)

    # 2. Detect relation types of interest
    relation_types = _detect_relation_types(question_lower, triples)

    # 3. Detect if comprehensive expansion needed
    comprehensive = _is_comprehensive_query(question_lower)

    # 4. Detect focus areas
    focus_areas = _detect_focus_areas(question_lower)

    return QueryIntent(
        entities=entities,
        expansion_depth=expansion_depth,
        relation_types=relation_types,
        comprehensive=comprehensive,
        focus_areas=focus_areas,
        original_question=question
    )


def _detect_expansion_depth(question: str) -> int:
    """
    Detect how many hops to expand based on question complexity.

    Returns:
        1-3 (number of hops to expand)
    """
    # Keywords suggesting multi-hop reasoning
    multihop_indicators = [
        r"connessioni indirette",
        r"attraverso",
        r"tramite",
        r"passando per",
        r"collegat[oi]",
        r"relazionat[oi]",
        r"che ha a che fare con",
        # English
        r"connected to",
        r"related to",
        r"through",
        r"via",
        r"associated with"
    ]

    # Count nesting depth in question
    nesting_patterns = [
        r"del .* del",  # "del padre del presidente"
        r"of .* of",    # "of father of president"
        r"che .* che",  # "che ha vissuto che era"
    ]

    depth = 1  # Default: 1-hop

    # Check for multi-hop indicators
    for pattern in multihop_indicators:
        if re.search(pattern, question):
            depth = max(depth, 2)

    # Check for nested structures
    nesting_count = 0
    for pattern in nesting_patterns:
        nesting_count += len(re.findall(pattern, question))

    if nesting_count >= 2:
        depth = 3
    elif nesting_count >= 1:
        depth = max(depth, 2)

    # Expansion keywords
    if re.search(r"allarg[aoi]|espand[aoi]|amplia|tutto|completo|comprehensive|expand|broaden", question):
        depth = max(depth, 2)

    return min(depth, 3)  # Cap at 3 hops


def _detect_relation_types(question: str, triples: List[Dict]) -> List[str]:
    """
    Determine which types of relations are relevant to the question.

    Returns:
        List of relation categories (biographical, temporal, spatial, etc.)
    """
    relation_types = set()

    # Biographical indicators
    biographical_keywords = [
        r"nato|nascita|morte|morto|vita|famiglia|genitori|figli|spouse|coniuge|married|born|death|family",
        r"padre|madre|fratello|sorella|parent|sibling|child"
    ]

    # Temporal indicators
    temporal_keywords = [
        r"quando|data|anno|periodo|tempo|epoca|secolo|during|time|period|year|date",
        r"prima|dopo|mentre|contemporaneo|before|after|while|contemporary"
    ]

    # Spatial/Geographic indicators
    spatial_keywords = [
        r"dove|luogo|citt[àa]|paese|nazione|stato|regione|where|place|city|country|location",
        r"nato a|vissuto a|situato|located|based"
    ]

    # Professional/Career indicators
    professional_keywords = [
        r"lavoro|professione|carriera|occupazione|ruolo|position|work|job|career|occupation",
        r"presidente|ministro|direttore|ceo|manager|leader"
    ]

    # Educational indicators
    educational_keywords = [
        r"studi|università|laurea|dottorato|education|university|degree|phd|studied",
        r"diplomato|laureato|graduate|student"
    ]

    # Organizational indicators
    organizational_keywords = [
        r"organizzazione|azienda|compagnia|istituzione|organization|company|institution",
        r"membro di|parte di|affiliato|member of|part of|affiliated"
    ]

    # Check question for each category
    keyword_categories = [
        ("biographical", biographical_keywords),
        ("temporal", temporal_keywords),
        ("spatial", spatial_keywords),
        ("professional", professional_keywords),
        ("educational", educational_keywords),
        ("organizational", organizational_keywords)
    ]

    for category, keywords in keyword_categories:
        for kw in keywords:
            if re.search(kw, question, re.IGNORECASE):
                relation_types.add(category)
                break

    # Also check extracted relations
    for triple in triples:
        rel = triple["relation"].lower()

        if any(x in rel for x in ["born", "birth", "death", "spouse", "parent", "child", "family"]):
            relation_types.add("biographical")
        if any(x in rel for x in ["date", "time", "year", "period"]):
            relation_types.add("temporal")
        if any(x in rel for x in ["place", "location", "city", "country"]):
            relation_types.add("spatial")
        if any(x in rel for x in ["work", "position", "occupation", "president", "director"]):
            relation_types.add("professional")
        if any(x in rel for x in ["education", "university", "degree"]):
            relation_types.add("educational")
        if any(x in rel for x in ["member", "organization", "institution"]):
            relation_types.add("organizational")

    # If no specific type detected, use general
    if not relation_types:
        relation_types.add("general")

    return list(relation_types)


def _is_comprehensive_query(question: str) -> bool:
    """
    Detect if user wants comprehensive/exhaustive information.

    Returns:
        True if comprehensive expansion needed
    """
    comprehensive_indicators = [
        r"tutt[oie]",
        r"ogni",
        r"qualsiasi",
        r"completo",
        r"dettagliato",
        r"esaustivo",
        r"tutto il possibile",
        r"il pi[ùu] possibile",
        # English
        r"\ball\b",
        r"\bevery\b",
        r"\bany\b",
        r"comprehensive",
        r"detailed",
        r"exhaustive",
        r"complete",
        r"as much as possible"
    ]

    for pattern in comprehensive_indicators:
        if re.search(pattern, question, re.IGNORECASE):
            return True

    return False


def _detect_focus_areas(question: str) -> List[str]:
    """
    Detect specific focus areas mentioned in the question.

    Returns:
        List of focus keywords
    """
    focus_areas = []

    # Extract quoted phrases (user-specified important terms)
    quoted = re.findall(r'"([^"]+)"', question)
    focus_areas.extend(quoted)

    # Extract capitalized entities (proper nouns)
    capitalized = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', question)
    focus_areas.extend(capitalized)

    # Common focus keywords
    focus_keywords = [
        r"politic[oa]",
        r"economic[oa]",
        r"scientific[oa]",
        r"artistic[oa]",
        r"cultur[ae]",
        r"sport",
        r"religion",
        r"technology",
        r"history"
    ]

    for kw in focus_keywords:
        if re.search(kw, question, re.IGNORECASE):
            focus_areas.append(kw)

    return list(set(focus_areas))


def get_relevant_wikidata_properties(intent: QueryIntent) -> List[str]:
    """
    Map query intent to relevant Wikidata properties.

    Args:
        intent: Analyzed query intent

    Returns:
        List of Wikidata property IDs (PIDs) or labels
    """
    # Category to Wikidata property mapping
    property_mapping = {
        "biographical": [
            "P26",   # spouse
            "P40",   # child
            "P22",   # father
            "P25",   # mother
            "P3373", # sibling
            "P19",   # place of birth
            "P20",   # place of death
            "P569",  # date of birth
            "P570",  # date of death
        ],
        "temporal": [
            "P569",  # date of birth
            "P570",  # date of death
            "P580",  # start time
            "P582",  # end time
            "P585",  # point in time
        ],
        "spatial": [
            "P19",   # place of birth
            "P20",   # place of death
            "P27",   # country of citizenship
            "P551",  # residence
            "P276",  # location
            "P131",  # located in administrative entity
        ],
        "professional": [
            "P39",   # position held
            "P106",  # occupation
            "P108",  # employer
            "P463",  # member of
            "P102",  # member of political party
        ],
        "educational": [
            "P69",   # educated at
            "P512",  # academic degree
            "P184",  # doctoral advisor
            "P185",  # doctoral student
        ],
        "organizational": [
            "P463",  # member of
            "P108",  # employer
            "P1416", # affiliation
            "P127",  # owned by
            "P749",  # parent organization
        ],
        "general": [
            "P31",   # instance of
            "P279",  # subclass of
            "P361",  # part of
            "P527",  # has part
        ]
    }

    # Collect all relevant properties
    properties = set()

    for rel_type in intent.relation_types:
        if rel_type in property_mapping:
            properties.update(property_mapping[rel_type])

    # If comprehensive, add more properties
    if intent.comprehensive:
        properties.update(property_mapping["general"])
        # Add all from detected categories
        for rel_type in intent.relation_types:
            if rel_type in property_mapping:
                properties.update(property_mapping[rel_type])

    # If no properties found, use general set
    if not properties:
        properties.update([
            "P31",  # instance of
            "P26",  # spouse
            "P27",  # country of citizenship
            "P19",  # place of birth
            "P106", # occupation
        ])

    return list(properties)


def estimate_max_edges_per_qid(intent: QueryIntent) -> int:
    """
    Determine how many edges to retrieve per QID based on intent.

    Args:
        intent: Query intent

    Returns:
        Max edges per QID (between 5 and 30)
    """
    base_edges = 8

    # Increase for comprehensive queries
    if intent.comprehensive:
        base_edges = 20

    # Increase based on expansion depth
    base_edges += (intent.expansion_depth - 1) * 5

    # Increase based on number of relation types
    base_edges += len(intent.relation_types) * 2

    return min(max(base_edges, 5), 30)  # Clamp between 5 and 30
